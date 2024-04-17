import logging
from icecream import ic
from slack_bolt.adapter.socket_mode import SocketModeHandler
from llm.llm_caller import LlmCaller
from slack.role_assignment import RoleAssignment


class SlackMessageHandler:
    def __init__(self, slack_bolt_app, slack_app_token, slack_utilities, llm_caller: LlmCaller, admin_user_ids):
        self.app = slack_bolt_app
        self.slack_utilities = slack_utilities
        self.llm_caller = llm_caller
        self.slack_app_token = slack_app_token
        self.admin_user_ids = admin_user_ids
        self.role_assignment = RoleAssignment(self.app,
                                              slack_meta_info_provider=self.slack_utilities.slack_meta_info_provider)
        self.role_assignment.register_interaction_handlers()
        self.setup_commands_and_events()

    def setup_commands_and_events(self):
        @self.app.command("/get-channel-history")
        def get_channel_history(ack, say, command, client):
            channel_id = command['channel_id']
            members_without_role = self.slack_utilities.slack_meta_info_provider.get_channel_members_no_role(channel_id)
            if members_without_role:
                ack({"response_type": "ephemeral",
                     "text": "Hey, I will not build any history until all roles are assigned! I'll send you roles, you assign and get back to re-run history fetch."})
                self.role_assignment.send_role_assignment_message(channel_id, members_without_role,
                                                                  command.get('user_id'))
                return

            ack()
            total_limit = 100
            self.slack_utilities.fetch_and_process_channel_history(channel_id, total_limit=total_limit, days_ago=6 * 30,
                                                                   say=say)

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

            response = client.conversations_history(channel=channel_id, limit=messages_to_delete)
            messages = response.get('messages', [])

            for message in messages:
                # Check for and delete threaded messages first
                thread_ts = message.get('thread_ts')
                if thread_ts:
                    thread_response = client.conversations_replies(channel=channel_id, ts=thread_ts)
                    thread_messages = thread_response.get('messages', [])
                    for thread_message in thread_messages:
                        self.slack_utilities.delete_message(client, channel_id, thread_message['ts'])

                # Then delete the message itself
                self.slack_utilities.delete_message(client, channel_id, message['ts'])

        @self.app.event("message")
        def handle_message_events(event, say):
            st = event.get("subtype")
            if st is not None and (st == "bot_message" or st == "message_deleted"):
                logging.debug(f"Message subtype is {st}, stopping further processing")
                return
            ed = self.slack_utilities.get_data_from_event(event)
            if not ed.user_role and not self.slack_utilities.slack_meta_info_provider.is_bot(ed.user_id):
                logging.warning(f"User {ed.user_id} has no role assigned in channel {ed.channel_id} .")
                members_without_role = self.slack_utilities.slack_meta_info_provider.get_channel_members_no_role(
                    ed.channel_id)
                if members_without_role:
                    for admin_user_id in self.admin_user_ids:
                        self.app.client.chat_postMessage(channel=admin_user_id,
                                                         text=f"For some reason I can't find role for user {ed.user_name} in channel {ed.channel_name}, please solve this!")
                        self.role_assignment.send_role_assignment_message(ed.channel_id, members_without_role,
                                                                          admin_user_id)
                    return
            c_id = ed.channel_id
            clean_messages = self.slack_utilities.clean_messages([event], c_id)
            mhd = self.slack_utilities.get_message_history_data(clean_messages, c_id)
            response = self.llm_caller.get_gpt_response(mhd.message_txt, mhd.last_messages_history,
                                                        mhd.previous_context_merged)
            ic(response)
            say(response.json())

            self.slack_utilities.add_messages(clean_messages, ed.channel_id)
            mes = clean_messages[0]
            tts = mes.get("thread_ts")
            if tts and tts != mes.get("ts"):
                self.slack_utilities.vector_db_helper.delete_message_group_by_thread_ts(mes)

            self.slack_utilities.group_all_messages_in_channel(c_id)
            logging.info(f"New message from {ed.user_name} in {ed.channel_name}: {ed.text}")

    def start(self):
        handler = SocketModeHandler(self.app, self.slack_app_token)
        handler.start()
