import logging
import time
from datetime import datetime, timedelta

from icecream import ic
from slack_bolt.adapter.socket_mode import SocketModeHandler

from llm.llm_caller import LlmCaller
from slack.event_data import EventData
from slack.message_history_data import MessageHistoryData
from slack.role_assignment import RoleAssignment
from slack.slack_meta_info import SlackMetaInfo
from vectordb.vector_db_helper import VectorDBHelper


class SlackApp:
    def __init__(self, slack_bolt_app, slack_app_token, vector_db_helper: VectorDBHelper, qa_processor,
                 message_history_fetcher, llm_caller: LlmCaller, redis_client, admin_user_ids):
        self.app = slack_bolt_app
        self.vector_db_helper = vector_db_helper
        self.llm_caller = llm_caller
        self.qa_processor = qa_processor
        self.slack_app_token = slack_app_token
        self.message_history_fetcher = message_history_fetcher
        self.slack_meta_info_provider = SlackMetaInfo(self.app.client, redis_client=redis_client)
        self.admin_user_ids = admin_user_ids

        self.role_assignment = RoleAssignment(self.app, slack_meta_info_provider=self.slack_meta_info_provider)
        self.role_assignment.register_interaction_handlers()
        self.setup_commands_and_events()

    def fetch_and_process_channel_history(self, channel_id, total_limit=1000, days_ago=6 * 30,
                                          say=lambda msg: print(msg)):
        days_ago = datetime.now() - timedelta(days=days_ago)
        oldest = str(int(days_ago.timestamp()))
        latest = str(int(time.time()))

        messages = self.message_history_fetcher.fetch_channel_history(channel_id, say, oldest, latest, total_limit)
        self.message_history_fetcher.save_messages_to_file(messages, channel_id)

        self.clean_and_add_messages(channel_id, messages)

    def clean_messages(self, messages, channel_id, slack_meta_info_provider):
        return self.message_history_fetcher.cleanup_messages(messages, channel_id, slack_meta_info_provider)

    def add_messages(self, clean_messages, channel_id):
        self.vector_db_helper.add_messages(clean_messages, channel_id)

    def clean_and_add_messages(self, channel_id, messages):
        clean_messages = self.clean_messages(messages, channel_id,
                                             slack_meta_info_provider=self.slack_meta_info_provider)
        self.add_messages(clean_messages, channel_id)

    def setup_commands_and_events(self):
        @self.app.command("/get-channel-history")
        def get_channel_history(ack, say, command, client):
            channel_id = command['channel_id']
            members_without_role = self.slack_meta_info_provider.get_channel_members_no_role(channel_id)
            if members_without_role:
                ack({"response_type": "ephemeral",
                     "text": "Hey, I will not build any history until all roles are assigned! I'll send you roles, you assign and get back to re-run history fetch."})
                self.role_assignment.send_role_assignment_message(channel_id, members_without_role,
                                                                  command.get('user_id'))
                return

            ack()
            total_limit = 100
            self.fetch_and_process_channel_history(channel_id, total_limit=total_limit, days_ago=6 * 30, say=say)

        @self.app.command("/delete-last-messages")
        def delete_last_messages(ack, say, command, client):
            ack()  # Acknowledge the command request immediately
            channel_id = command['channel_id']
            user_id = command['user_id']
            num_to_delete = command.get('text', 0)
            try:
                messages_to_delete = int(
                    num_to_delete)  # Assuming 'text' is used to specify the number of messages to delete
            except Exception:
                say(f"Please specify a valid number of messages to delete. Got {num_to_delete}")
                return

            if messages_to_delete <= 0:
                say(f"Please specify a valid number of messages to delete.")
                return

            def del_message(ts, as_user=False):
                try:
                    client.chat_delete(channel=channel_id, ts=ts, as_user=as_user)
                except Exception as e:
                    logging.debug(f"Can't delete message, error: {e}")
                    if not as_user:
                        logging.debug(f"Will retry as user")
                        del_message(ts, as_user=True)

            # Fetch the last x messages from the channel history
            response = client.conversations_history(channel=channel_id, limit=messages_to_delete)
            messages = response.get('messages', [])

            for message in messages:
                # Check for and delete threaded messages first
                thread_ts = message.get('thread_ts')
                if thread_ts:
                    thread_response = client.conversations_replies(channel=channel_id, ts=thread_ts)
                    thread_messages = thread_response.get('messages', [])
                    for thread_message in thread_messages:
                        del_message(thread_message['ts'])

                # Then delete the message itself
                del_message(message['ts'])

        @self.app.event("message")
        def handle_message_events(event, say):
            st = event.get("subtype")
            if st is not None and (st == "bot_message" or st == "message_deleted"):
                logging.debug(f"Message subtype is {st}, stopping further processing")
                return
            ed = self.get_data_from_event(event)
            if not ed.user_role and not self.slack_meta_info_provider.is_bot(ed.user_id):
                logging.warning(f"User {ed.user_id} has no role assigned in channel {ed.channel_id} .")
                members_without_role = self.slack_meta_info_provider.get_channel_members_no_role(ed.channel_id)
                if members_without_role:
                    for admin_user_id in self.admin_user_ids:
                        self.app.client.chat_postMessage(channel=admin_user_id,
                                                         text=f"For some reason I can't find role for user {ed.user_name} in channel {ed.channel_name}, please solve this!")
                        self.role_assignment.send_role_assignment_message(ed.channel_id, members_without_role,
                                                                          admin_user_id)
                    return

            clean_messages = self.clean_messages([event], ed.channel_id, self.slack_meta_info_provider)
            mhd = self.get_message_history_data(clean_messages,
                                                ed)
            response = self.llm_caller.get_gpt_response(mhd.message_txt, mhd.last_messages_history,
                                                        mhd.previous_context_merged)
            ic(response)
            say(response.json())

            self.add_messages(clean_messages, ed.channel_id)
            mes = clean_messages[0]
            tts = mes.get("thread_ts")
            if tts and tts != mes.get("ts"):
                self.vector_db_helper.delete_message_group_by_thread_ts(mes)

            self.vector_db_helper.group_all_in_channel(ed.channel_id)
            logging.info(f"New message from {ed.user_name} in {ed.channel_name}: {ed.text}")

    def get_message_history_data(self, clean_messages, ed):
        message_txt = self.vector_db_helper.msg_array_to_text(clean_messages, is_db_object=False)
        last_messages_history = self.vector_db_helper.get_last_x_messages(ed.channel_id, 5)
        previous_context = self.vector_db_helper.get_relevant_message_groups(ed.channel_id, message_txt,
                                                                             distance=0.7)
        previous_context_merged = [f"{message_group.properties['text']} \n-------\n" for message_group in
                                   previous_context.objects]
        logging.debug(previous_context)
        return MessageHistoryData(last_messages_history=last_messages_history,
                                  message_txt=message_txt, previous_context_merged=previous_context_merged)

    def get_data_from_event(self, event):
        channel_id = event.get('channel')
        user_id = event.get('user')
        text = event.get('text', '')  # Default to empty string if no text

        user_name = self.slack_meta_info_provider.get_user_name(user_id) or "Unknown User"
        user_role = self.slack_meta_info_provider.get_user_role_in_channel(user_id,
                                                                           channel_id=channel_id)
        channel_name = self.slack_meta_info_provider.get_channel_name(channel_id) or "Unknown Channel"

        return EventData(
            channel_id=channel_id,
            channel_name=channel_name,
            text=text,
            user_id=user_id,
            user_name=user_name,
            user_role=user_role
        )

    def start(self):
        handler = SocketModeHandler(self.app, self.slack_app_token)
        handler.start()
