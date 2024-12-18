import logging
from icecream import ic
from slack_bolt.adapter.socket_mode import SocketModeHandler
from llm.llm_caller import LLMCaller, SatisfactionLevelContext
from slack.role_assignment import RoleAssignment
from workflows.slack_state_manager import SlackStateManager
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

class SlackMessageHandler:
    # TODO remove llm_caller from here, should go to state manger
    def __init__(self, slack_bolt_app, slack_app_token, slack_utilities, state_manager: SlackStateManager,
                 role_assignment: RoleAssignment, n8n_manager):
        self.app = slack_bolt_app
        self.slack_utilities = slack_utilities
        self.state_manager = state_manager
        self.slack_app_token = slack_app_token
        self.role_assignment = role_assignment
        self.n8n_manager = n8n_manager

    async def are_all_roles_assigned(self, user_name, channel_name, channel_id):
        smip = self.slack_utilities.slack_meta_info_provider
        members_without_role = await smip.get_channel_members_no_role(channel_id)
        if members_without_role:
            for admin_user_id in smip.admin_user_ids:
                await self.app.client.chat_postMessage(
                    channel=admin_user_id,
                    text=f"For some reason I can't find role for user {user_name} in channel {channel_name}, please solve this!"
                )
                await self.role_assignment.send_role_assignment_message(
                    channel_id,
                    members_without_role,
                    admin_user_id,
                    channel_name
                )
            return False
        return True

    async def setup_commands_and_events(self):
        await self.role_assignment.register_interaction_handlers()

        # Test command for registration verification
        @self.app.command("/test-command")
        async def test_command(ack, say, command):
            await ack()
            channel_id = "G03MX3VE7"
            result = await self.state_manager.scheduler().send_task(
                'celery_scheduler.tasks.ping_manager_when_unanswered.soft', args=[channel_id],
                countdown=2)
            result.get(timeout=588)
            await say("Test command is registered and working!")

        @self.app.command("/get-channel-history")
        async def get_channel_history(ack, say, command, client):
            channel_id = command['channel_id']
            members_without_role = await self.slack_utilities.slack_meta_info_provider.get_channel_members_no_role(channel_id)

            if members_without_role:
                await ack({
                    "response_type": "ephemeral",
                    "text": "Hey, I will not build any history until all roles are assigned! I'll send you roles, you assign and get back to re-run history fetch."
                })
                channel_name = await self.slack_utilities.slack_meta_info_provider.get_channel_name(channel_id)
                await self.role_assignment.send_role_assignment_message(
                    channel_id,
                    members_without_role,
                    command.get('user_id'),
                    channel_name
                )
                return

            await ack()
            total_limit = 100
            await self.slack_utilities.fetch_and_process_channel_history(
                channel_id,
                total_limit=total_limit,
                days_ago=6 * 30,
                say=say
            )

        @self.app.command("/delete-last-messages")
        async def delete_last_messages(ack, say, command, client):
            await ack()  # Acknowledge the command request immediately
            channel_id = command['channel_id']
            user_id = command['user_id']
            num_to_delete = command.get('text', 0)

            try:
                messages_to_delete = int(num_to_delete)
            except ValueError:
                await say(f"Please specify a valid number of messages to delete. Got {num_to_delete}")
                return

            if messages_to_delete <= 0:
                await say(f"Please specify a valid number of messages to delete.")
                return

            response = await client.conversations_history(channel=channel_id, limit=messages_to_delete)
            messages = response.get('messages', [])

            for message in messages:
                # Check for and delete threaded messages first
                thread_ts = message.get('thread_ts')
                if thread_ts:
                    thread_response = await client.conversations_replies(channel=channel_id, ts=thread_ts)
                    thread_messages = thread_response.get('messages', [])
                    for thread_message in thread_messages:
                        await self.slack_utilities.delete_message(client, channel_id, thread_message['ts'])

                # Then delete the message itself
                await self.slack_utilities.delete_message(client, channel_id, message['ts'])

        @self.app.event("message")
        async def handle_message_events(event, say):
            st = event.get("subtype")
            if st is not None and (st == "bot_message" or st == "message_deleted"):
                logging.debug(f"Message subtype is {st}, stopping further processing")
                return

            ed = await self.slack_utilities.get_data_from_event(event)
            # TODO this will skip message incoming as no role is assigned, rendering all messages came before role is set to be missed
            if not ed.user.role and not await self.slack_utilities.slack_meta_info_provider.is_bot(ed.user.id):
                logging.warning(f"User {ed.user.name} has no role assigned in channel {ed.channel_id} .")
                if not await self.are_all_roles_assigned(ed.user.name, ed.channel_name, ed.channel_id):
                    return
            c_id = ed.channel_id
            clean_messages = await self.slack_utilities.clean_messages([event], c_id)
            mhd = await self.slack_utilities.get_message_history_data(clean_messages, c_id)
            # self.state_manager.handle_message(mhd, ed)
            # dynamic_context = SatisfactionLevelContext(last_message=mhd.message_txt,
            #                                           last_messages_history=mhd.last_messages_history)
            # response = self.state_manager.llm_caller.get_satisfaction_level(dynamic_context)
            # ic(response)
            # say(response.json())
            workflow_data = {
                "message": {
                    "text": mhd.message_txt,
                    "history": mhd.last_messages_history,
                    "previous_context": mhd.previous_context_merged,
                    "channel_id": c_id,
                    "user": {
                        "id": ed.user.id,
                        "name": ed.user.name,
                        "role": ed.user.role
                    },
                    "thread_ts": event.get("thread_ts"),
                    "ts": event.get("ts")
                }
            }

            # Trigger n8n workflow
            is_success = await self.n8n_manager.trigger_workflow("satisfaction", workflow_data)

            if not is_success:
                logging.error(f"Failed to process message through n8n")

            await self.slack_utilities.add_messages(clean_messages, ed.channel_id)
            mes = clean_messages[0]
            tts = mes.get("thread_ts")
            if tts and tts != mes.get("ts"):
                await self.slack_utilities.vector_db_helper.delete_message_group_by_thread_ts(mes)

            await self.slack_utilities.group_all_messages_in_channel(c_id)
            logging.info(f"New message from {ed.user.name} in {ed.channel_name}: {ed.text} processed")
