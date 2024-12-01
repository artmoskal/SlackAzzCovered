from celery import shared_task, current_task
import logging

import pydevd_pycharm
from asgiref.sync import async_to_sync
from config.container import Container
from workflows.slack_state_manager import MissingRolesException

logger = logging.getLogger(__name__)

@shared_task(name='celery_scheduler.tasks.ping_manager_when_unanswered.soft')
def soft_sync(channel_id: str):
    async_to_sync(soft)(channel_id)

async def soft(channel_id: str):
    container = Container()
    sm = container.state_manager()
    pydevd_pycharm.settrace('localhost', port=5678, stdoutToServer=True, stderrToServer=True, suspend=True)
    try:
        channel_state = await sm.load_channel_data(channel_id)
    except MissingRolesException as e:
        logger.info(str(e))
        # Initiate role assignment process externally
        role_assignment = container.role_assignment()
        admin_ids = sm.slack_meta_info_provider.admin_user_ids
        members = await sm.slack_meta_info_provider.get_channel_members_no_role(channel_id)
        channel_name = await sm.slack_meta_info_provider.get_channel_name(channel_id)
        for admin_id in admin_ids:
            await role_assignment.send_role_assignment_message(
                channel_id,
                {user.id: user.name for user in members},
                admin_id,
                channel_name
            )
        # Exit the task gracefully
        return
    channel_manager = container.channel_state_manager_factory(channel_state)

    # Get the current task ID
    current_task_id = current_task.request.id

    # Process the soft ping with the current task ID
    message_action = channel_manager.process_soft_ping(current_task_id)
    if message_action:
        await container.slack_bolt_app().client.chat_postMessage(channel=message_action.channel_id, text=message_action.text)
    sm.save_channel_data(channel_state)
    return ""
