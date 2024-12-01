import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal

from slack.struct.event_data import EventData
from slack.struct.message_history_data import MessageHistoryData
from slack.struct.slack_user import SlackUser
from utils.date_utils import ts_to_rfc3339

class SlackUtilities:
    def __init__(self, vector_db_helper, message_history_fetcher, slack_meta_info_provider):
        self.vector_db_helper = vector_db_helper
        self.message_history_fetcher = message_history_fetcher
        self.slack_meta_info_provider = slack_meta_info_provider

    async def fetch_and_process_channel_history(self, channel_id, total_limit=1000, days_ago=6 * 30,
                                          say=lambda msg: print(msg)):
        days_ago = datetime.now() - timedelta(days=days_ago)
        oldest = str(int(days_ago.timestamp()))
        latest = str(int(time.time()))

        messages = await self.message_history_fetcher.fetch_channel_history(channel_id, say, oldest, latest, total_limit)
        self.message_history_fetcher.save_messages_to_file(messages, channel_id)

        await self.clean_and_add_messages(channel_id, messages)

    async def clean_messages(self, messages, channel_id):
        return await self.message_history_fetcher.cleanup_messages(messages, channel_id, self.slack_meta_info_provider)

    async def add_messages(self, clean_messages, channel_id):
        await self.vector_db_helper.add_messages(clean_messages, channel_id)

    async def clean_and_add_messages(self, channel_id, messages):
        clean_messages = await self.clean_messages(messages, channel_id)
        await self.add_messages(clean_messages, channel_id)

    async def delete_message(self, client, channel_id, ts, as_user=False):
        try:
            await client.chat_delete(channel=channel_id, ts=ts, as_user=as_user)
        except Exception as e:
            logging.debug(f"Can't delete message, error: {e}")
            if not as_user:
                logging.debug(f"Will retry as user")
                await self.delete_message(client, channel_id, ts, as_user=True)

    async def get_data_from_event(self, event):
        channel_id = event.get('channel')
        user_id = event.get('user', "")
        text = event.get('text', '')  # Default to empty string if no text

        user_name = await self.slack_meta_info_provider.get_user_name(user_id) or "Unknown User"
        user_role = self.slack_meta_info_provider.get_user_role_in_channel(user_id, channel_id=channel_id) or ""
        channel_name = await self.slack_meta_info_provider.get_channel_name(channel_id) or "Unknown Channel"
        user = SlackUser(id=user_id, name=user_name, role=user_role)

        return EventData(
            channel_id=channel_id,
            channel_name=channel_name,
            text=text,
            ts=ts_to_rfc3339(event.get('ts')),
            user=user
        )

    async def group_all_messages_in_channel(self, channel_id):
        await self.vector_db_helper.group_all_in_channel(channel_id)

    async def get_message_history_data(self, clean_messages, channel_id):
        message_txt = self.vector_db_helper.msg_array_to_text(clean_messages, is_db_object=False)
        last_messages_history = await self.vector_db_helper.get_last_x_messages(channel_id, 5)
        previous_context = await self.vector_db_helper.get_relevant_message_groups(channel_id, message_txt,
                                                                             distance=0.7)
        #TODO check if usernames and timestamps are included into this text
        previous_context_merged = [f"{message_group.properties['text']} \n-------\n" for message_group in
                                   previous_context.objects]
        logging.debug("Previous Context: %s", previous_context_merged)

        return MessageHistoryData(last_messages_history=last_messages_history,
                                  message_txt=message_txt, previous_context_merged=previous_context_merged)
