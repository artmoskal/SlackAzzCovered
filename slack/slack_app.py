import logging
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache

from icecream import ic
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from llm.llm_caller import LlmCaller
from vectordb.vector_db_helper import VectorDBHelper

class UserInfoCache:
    def __init__(self, slack_client):
        self.slack_client = slack_client

    @lru_cache(maxsize=1024)
    def get_user_name(self, user_id):
        try:
            result = self.slack_client.users_info(user=user_id)
            if result and result['user']:
                return result['user']['name']
        except Exception as e:
            logging.error(f"Error fetching user info: {e}")
        return None

    @lru_cache(maxsize=1024)
    def get_channel_name(self, channel_id):
        try:
            result = self.slack_client.conversations_info(channel=channel_id)
            if result and result['channel']:
                return result['channel']['name']
        except Exception as e:
            logging.error(f"Error fetching channel info: {e}")
        return None

class SlackApp:
    def __init__(self, slack_bolt_app, slack_app_token, vector_db_helper: VectorDBHelper, qa_processor,
                 message_history_fetcher, llm_caller: LlmCaller):
        self.app = slack_bolt_app
        self.vector_db_helper = vector_db_helper
        self.llm_caller = llm_caller
        self.qa_processor = qa_processor
        self.slack_app_token = slack_app_token
        self.message_history_fetcher = message_history_fetcher
        self.user_info_cache = UserInfoCache(self.app.client)

        self.setup_commands_and_events()


    def fetch_and_process_channel_history(self, channel_id, total_limit=1000, days_ago=6*30, say=lambda msg: print(msg)):
        days_ago = datetime.now() - timedelta(days=days_ago)
        oldest = str(int(days_ago.timestamp()))
        latest = str(int(time.time()))

        messages = self.message_history_fetcher.fetch_channel_history(channel_id, say, oldest, latest, total_limit)
        self.message_history_fetcher.save_messages_to_file(messages, channel_id)

        self.clean_and_add_messages(channel_id, messages)

    def clean_messages(self, messages):
        return self.message_history_fetcher.cleanup_messages(messages)

    def add_messages(self, clean_messages, channel_id):
        self.vector_db_helper.add_messages(clean_messages, channel_id)

    def clean_and_add_messages(self, channel_id, messages):
        clean_messages = self.clean_messages(messages)
        self.add_messages(clean_messages, channel_id)

    def setup_commands_and_events(self):
        @self.app.command("/get-channel-history")
        def get_channel_history(ack, say, command):
            ack()
            channel_id = command['channel_id']
            total_limit = 1000
            self.fetch_and_process_channel_history(channel_id, total_limit=total_limit, days_ago=6 * 30,say=say)


        @self.app.event("message")
        def handle_message_events(event, say):
            if event.get("subtype") is None or event.get("subtype") != "bot_message":
                channel_id = event.get('channel')
                user_id = event.get('user')
                text = event.get('text')
                user_name = self.user_info_cache.get_user_name(user_id)
                channel_name = self.user_info_cache.get_channel_name(channel_id)
                clean_messages = self.clean_messages([event])
                message_txt = self.vector_db_helper.msg_array_to_text(clean_messages, is_db_object=False)
                last_messages_history = self.vector_db_helper.get_last_x_messages(channel_id, 5)
                previous_context = self.vector_db_helper.get_relevant_message_groups(channel_id, message_txt, distance=0.7)
                previous_context_merged = [f"{message_group.properties['text']} \n-------\n" for message_group in previous_context.objects]
                response = self.llm_caller.get_gpt_response(message_txt, last_messages_history, previous_context_merged)
                logging.debug(previous_context)
                ic(response)
                say(response.json())

                self.add_messages(clean_messages, channel_id)
                mes = clean_messages[0]
                tts = mes.get("thread_ts")
                if tts and tts != mes.get("ts"):
                    self.vector_db_helper.delete_message_group_by_thread_ts(mes)

                self.vector_db_helper.group_all_in_channel(channel_id)
                logging.info(f"New message from {user_name} in {channel_name}: {text}")


    def start(self):
        handler = SocketModeHandler(self.app, self.slack_app_token)
        handler.start()

