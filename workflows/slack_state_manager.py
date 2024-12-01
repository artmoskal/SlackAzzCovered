import json

from celery import Celery
from typing import Callable

from llm.llm_caller import LLMCaller
from slack.struct.event_data import EventData
from slack.struct.message_history_data import MessageHistoryData
from slack.slack_meta_info import SlackMetaInfo
from workflows.channel_state_manager import ChannelState, ChannelStateManager


class MissingRolesException(Exception):
    """Exception raised when user roles are missing."""
    pass


class SlackStateManager:
    def __init__(
        self,
        redis_client,
        llm_caller: LLMCaller,
        slack_meta_info_provider: SlackMetaInfo,
        scheduler: Celery,
        channel_state_manager_factory: Callable[..., ChannelStateManager]
    ) -> None:
        self.channels = {}
        self.redis = redis_client
        self.scheduler = scheduler
        self.slack_meta_info_provider = slack_meta_info_provider
        self.llm_caller = llm_caller
        self.channel_state_manager_factory = channel_state_manager_factory

    async def load_channel_data(self, channel_id: str) -> ChannelState:
        channel_data = self.redis.get(channel_id)
        if channel_data:
            channel_data = json.loads(channel_data)
        else:
            members = await self.slack_meta_info_provider.get_channel_members_all(channel_id)
            missing_roles_message = f"User roles are missing in channel {channel_id}."
            if not members:
                raise MissingRolesException(missing_roles_message)

            # Check if any member lacks a role
            missing_roles = [user for user in members if not user.role]
            if missing_roles:
                # Raise an exception to indicate roles are missing
                raise MissingRolesException(missing_roles_message)
            channel_data = {
                "channel_id": channel_id,
                "users": members,
                "workspace_name": self.slack_meta_info_provider.get_workspace_name(),
            }
        # Use Pydantic's parsing to handle defaults and type enforcement
        return ChannelState.model_validate(channel_data)

    def save_channel_data(self, channel_state: ChannelState) -> None:
        self.redis.set(channel_state.channel_id, channel_state.json())

    async def handle_message(
        self,
        message_history_data: MessageHistoryData,
        event_data: EventData
    ) -> None:
        channel_id = event_data.channel_id
        channel_state = await self.load_channel_data(channel_id)
        channel_manager = self.channel_state_manager_factory(
            channel_state=channel_state
        )
        channel_manager.handle_message(message_history_data, event_data)
        self.save_channel_data(channel_state)
