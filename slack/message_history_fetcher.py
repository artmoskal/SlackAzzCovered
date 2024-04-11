import json
import logging

from slack.slack_meta_info import SlackMetaInfo


class MessageHistoryFetcher:
    def __init__(self, app):
        self.app = app

    def cleanup_messages(self, messages, channel_id, slack_meta_info_provider: SlackMetaInfo):
        cleaned_messages = []

        for msg in messages:
            cleaned_msg = {}
            # Extract timestamp
            cleaned_msg['ts'] = msg.get('ts')
            cleaned_msg['thread_ts'] = msg.get('thread_ts', None)

            # Handle different message types and sources
            if 'user' in msg:
                user_id = msg['user']
                cleaned_msg['user_id'] = user_id
                cleaned_msg['user_name'] = slack_meta_info_provider.get_user_name(user_id)
                role = slack_meta_info_provider.get_user_role_in_channel(user_id, channel_id) if msg.get(
                    'bot_id') is None else 'bot'
                cleaned_msg['role'] = role
                cleaned_msg['type'] = 'user'
            else:
                cleaned_msg['user_id'] = None  # Unknown source

            # Extract text content
            text_content = msg.get('text', '')

            # Handle attachments (e.g., forwarded emails, files) if necessary
            attachments = msg.get('attachments', [])
            for attachment in attachments:
                # Example: Extracting text from forwarded emails or other integrations
                if 'text' in attachment:
                    text_content += '\n' + attachment['text']
                elif 'fallback' in attachment:  # Fallback text for some attachments
                    text_content += '\n' + attachment['fallback']

            cleaned_msg['text'] = text_content.strip()

            cleaned_messages.append(cleaned_msg)

        return cleaned_messages

    def save_messages_to_file(self, messages, channel_id):
        file_path = f"messages_{channel_id}.json"
        with open(file_path, 'w') as f:
            json.dump(messages, f)
        logging.info(f"Saved {len(messages)} messages to {file_path}")

    def fetch_channel_history(self, channel_id, say, start_timestamp, end_timestamp, max_messages_to_fetch):
        try:
            limit = 200

            messages = []
            has_more = True
            next_cursor = None
            total_fetched = 0

            while has_more and total_fetched < max_messages_to_fetch:
                result = self.app.client.conversations_history(
                    channel=channel_id,
                    latest=end_timestamp,
                    oldest=start_timestamp,
                    limit=min(limit, max_messages_to_fetch - total_fetched),
                    cursor=next_cursor
                )

                batch_messages = result['messages']
                messages.extend(batch_messages)
                total_fetched += len(batch_messages)

                has_more = result.get('has_more', False)
                next_cursor = result.get('response_metadata', {}).get('next_cursor', "") if has_more else ""

                if total_fetched >= max_messages_to_fetch or not has_more:
                    break

            # Fetch threads for messages that are the beginning of a thread
            for message in messages:
                if message.get('thread_ts') and message['ts'] == message['thread_ts']:
                    thread_result = self.app.client.conversations_replies(
                        channel=channel_id,
                        ts=message['thread_ts']
                    )
                    # Exclude the first message since it's already included
                    thread_messages = thread_result['messages'][1:]
                    messages.extend(thread_messages)

            logging.info(f"Fetched {len(messages)} messages from the last 6 months.")
            say(f"Fetched {len(messages)} messages from the last 6 months, up to a limit of {min(len(messages), max_messages_to_fetch)} messages.")
            logging.info(messages)
            return messages

        except Exception as e:
            logging.error(f"Error fetching channel history: {e}")
            say("Failed to fetch channel history.")
