import json
import logging
from functools import partial
from typing import Any, Callable, Optional

from pydantic import TypeAdapter

from slack.struct.slack_user import SlackUser

def to_json(value: Any) -> str:
    adapter = TypeAdapter(type(value))
    return adapter.dump_json(value, exclude_unset=True, exclude_defaults=True, exclude_none=True).decode('utf-8')

def from_json(value: str, parse_as_type: type[Any]) -> Any:
    adapter = TypeAdapter(parse_as_type)
    return adapter.validate_json(value.encode('utf-8'))

class SlackMetaInfo:
    TWO_WEEKS = 14 * 24 * 60 * 60  # Two weeks in seconds
    EXPIRATION_INFINITY = 0

    def __init__(self, slack_app, redis_client, admin_user_ids: list[str]) -> None:
        self.redis_client = redis_client
        self.slack_app = slack_app
        self.admin_user_ids = admin_user_ids

    async def fetch_from_cache(
        self,
        key: str,
        fetch_function: Callable[..., Any],
        ex: int = TWO_WEEKS,
        *args,
        parse_as_type: Optional[type[Any]] = None,
        **kwargs
    ) -> Any:
        """Fetch data from cache or use the provided fetch function to retrieve it."""
        value = self.redis_client.get(key)
        if value is not None:
            try:
                if parse_as_type:
                    return from_json(value.decode('utf-8'), parse_as_type)
                return json.loads(value.decode('utf-8'))
            except Exception as e:
                logging.error(f"Error decoding JSON from cache for key {key}: {e}")
                # Proceed to fetch fresh data
        try:
            value = await fetch_function(*args, **kwargs)
            if value is not None:
                if parse_as_type:
                    serialized_value = to_json(value)
                else:
                    serialized_value = json.dumps(value)
                ex_time = ex if ex > 0 else None
                self.redis_client.set(key, serialized_value, ex=ex_time)
                return value
        except Exception as e:
            logging.error(f"Error while fetching and caching for key {key}: {e}")
        return None

    async def get_user_name(self, user_id: str) -> Optional[str]:
        key = self._generate_cache_key("user_name", user_id=user_id)
        return await self.fetch_from_cache(
            key,
            self._fetch_user_name,
            user_id=user_id
        )

    async def get_channel_members_all(self, channel_id: str) -> Optional[list[SlackUser]]:
        key = self._generate_cache_key("channel_members_all", channel_id=channel_id)
        return await self.fetch_from_cache(
            key,
            partial(self._fetch_channel_members, channel_id=channel_id, skip_members_having_role=False),
            parse_as_type=list[SlackUser]
        )

    async def get_channel_members_no_role(self, channel_id: str) -> Optional[list[SlackUser]]:
        """Get channel members who have no assigned role."""
        key = self._generate_cache_key("channel_members_no_role", channel_id=channel_id)
        return await self.fetch_from_cache(
            key,
            self._fetch_channel_members,
            channel_id=channel_id,
            parse_as_type=list[SlackUser]
        )

    async def _fetch_channel_members(
        self,
        channel_id: str,
        skip_members_having_role: bool = True,
        skip_bots: bool = True
    ) -> Optional[list[SlackUser]]:
        """Fetch channel members from Slack API."""
        try:
            result = await self.slack_app.client.conversations_members(channel=channel_id)
            members = result.get('members', [])
        except Exception as e:
            logging.error(f"Error fetching channel members for channel {channel_id}: {e}")
            return None

        users = []
        for user_id in members:
            is_bot = await self.is_bot(user_id)

            if is_bot and skip_bots:
                logging.debug(f"Skipping bot: {user_id}")
                continue

            user_name = await self.get_user_name(user_id)
            role = "bot" if is_bot else self.get_user_role_in_channel(user_id, channel_id)
            if role and skip_members_having_role:
                logging.debug(f"Found existing role ({role}) for {user_id} ({user_name}), skipping.")
                continue
            # TODO Two queries should be replaced with one. First for is_bot and second for user name
            users.append(SlackUser(id=user_id, name=user_name, role=role))
        return users if users else None

    async def get_channel_name(self, channel_id: str) -> Optional[str]:
        """Get the name of a channel."""
        key = self._generate_cache_key("channel_name", channel_id=channel_id)
        return await self.fetch_from_cache(
            key,
            self._fetch_channel_name,
            channel_id=channel_id
        )

    async def get_workspace_name(self) -> Optional[str]:
        """Get the name of the workspace."""
        key = self._generate_cache_key("workspace_name")
        return await self.fetch_from_cache(
            key,
            self._fetch_workspace_name,
        )

    async def is_bot(self, user_id: str) -> Optional[bool]:
        """Check if a user is a bot."""
        key = self._generate_cache_key("user_is_bot", user_id=user_id)
        result = await self.fetch_from_cache(
            key=key,
            fetch_function=self._fetch_is_bot,
            ex=self.EXPIRATION_INFINITY,
            user_id=user_id,
        )
        if result is not None:
            return bool(result)
        else:
            return None

    def get_slack_client(self):
        return self.slack_app.client

    def _fetch_workspace_name(self) -> Optional[str]:
        """Fetch workspace name from Slack API."""
        try:
            client = self.get_slack_client()
            result = client.team_info()
            return result.get('team', {}).get('name')
        except Exception as e:
            logging.error(f"Error fetching workspace name: {e}")
            return None

    async def _fetch_user_name(self, user_id: str) -> Optional[str]:
        """Fetch user name from Slack API."""
        try:
            result = await self.get_slack_client().users_info(user=user_id)
            return result.get('user', {}).get('name')
        except Exception as e:
            logging.error(f"Error fetching user name for user {user_id}: {e}")
            return None

    async def _fetch_channel_name(self, channel_id: str) -> Optional[str]:
        """Fetch channel name from Slack API."""
        try:
            result = await self.get_slack_client().conversations_info(channel=channel_id)
            return result.get('channel', {}).get('name')
        except Exception as e:
            logging.error(f"Error fetching channel name for channel {channel_id}: {e}")
            return None

    async def _fetch_is_bot(self, user_id: str) -> Optional[bool]:
        """Fetch bot status from Slack API."""
        try:
            result = await self.get_slack_client().users_info(user=user_id)
            return result.get('user', {}).get('is_bot')
        except Exception as e:
            logging.error(f"Error fetching bot status for user {user_id}: {e}")
            return None

    def get_user_role_in_channel(self, user_id: str, channel_id: str) -> Optional[str]:
        """Get the role of a user in a channel."""
        key = self._generate_cache_key("user_role", user_id=user_id, channel_id=channel_id)
        value = self.redis_client.get(key)
        return value.decode('utf-8') if value else None

    def set_user_role_in_channel(self, user_id: str, channel_id: str, role_name: str) -> None:
        """Set the role of a user in a channel."""
        key = self._generate_cache_key("user_role", user_id=user_id, channel_id=channel_id)
        self.redis_client.set(key, role_name)
        # Invalidate the cache for channel members with no role
        key_no_role = self._generate_cache_key("channel_members_no_role", channel_id=channel_id)
        self.redis_client.delete(key_no_role)

    def _generate_cache_key(self, key_type: str, **identifiers: str) -> str:
        """Generate a cache key based on key type and identifiers."""
        parts = [key_type] + [f"{k}:{v}" for k, v in identifiers.items()]
        return ":".join(parts)
