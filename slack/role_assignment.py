import re

from slack.slack_meta_info import SlackMetaInfo
import logging


class RoleAssignment:
    ROLES = ["Manager", "Developer", "Customer", "Designer"]

    def __init__(self, app, slack_meta_info_provider: SlackMetaInfo):
        self.slack_meta_info_provider = slack_meta_info_provider
        self.app = app

    def send_role_assignment_message(self, channel_id, users, inviter_id):
        blocks = []
        for user_id, user_name in users.items():
            user_section = {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"@{user_id} ({user_name}) is"
                }
            }
            buttons = [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": role
                    },
                    "value": f"{user_id}_{role.lower()}_{channel_id}",
                    "action_id": f"assign_role_{role.lower()}_{user_id}_{channel_id}"
                } for role in self.ROLES
            ]

            buttons_section = {
                "type": "actions",
                "elements": buttons
            }
            blocks.extend([user_section, buttons_section])

        # Send the message
        self.app.client.chat_postMessage(channel=inviter_id, blocks=blocks, text="Role Assignment")

    def register_interaction_handlers(self):
        @self.app.event("member_joined_channel")
        def ask_for_roles_and_check_existing_members(ack, say, client, event):
            ack()
            # TODO probably should not send "questionary" to customers who invited someone
            inviter_id = event['inviter']  # Assuming 'user' is who added the bot
            channel_id = event['channel']

            users = self.slack_meta_info_provider.get_channel_members_no_role(channel_id)

            self.send_role_assignment_message(channel_id, users, inviter_id)

        @self.app.action(re.compile("assign_role_.*"))  # Use regex to match any action_id starting with "assign_role_"
        def handle_role_assignment(ack, body, say):
            ack()
            action_value = body['actions'][0]['value']
            user_id, role, channel_id = action_value.split('_')
            self.slack_meta_info_provider.set_user_role_in_channel(user_id, channel_id, role)
            say(f"Assigned <@{user_id}> as {role}.")
