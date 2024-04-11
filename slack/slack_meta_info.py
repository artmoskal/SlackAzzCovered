import json
import logging
from functools import partial


class SlackMetaInfo:
    TWO_WEEKS = 14 * 24 * 60 * 60  # two weeks in seconds
    INFINITY = 0

    def __init__(self, slack_client, redis_client):
        self.redis_client = redis_client
        self.slack_client = slack_client

    def fetch_from_cache(self, key, fetch_function, ex=TWO_WEEKS, *args, **kwargs):
        value = self.redis_client.get(key)
        if value is not None:
            return value.decode('utf-8')  # Data from cache is always a string.

        try:
            value = fetch_function(*args, **kwargs)
            if value is not None:
                serialized_value = json.dumps(value)  # Always serialize before caching.
                ex_time = ex if ex > 0 else None
                self.redis_client.set(key, serialized_value, ex=ex_time)
                return serialized_value  # Return the serialized value directly.
        except Exception as e:
            logging.error(f"Error while fetching and caching: {e}")
        return None

    def _cached_json_to_bool(self, cached_json_str):
        if cached_json_str is not None:
            return json.loads(cached_json_str)
        return None

    def get_user_name(self, user_id):
        return self.fetch_from_cache(
            f"user_name:{user_id}",
            self._fetch_user_name,
            user_id=user_id
        )

    def get_channel_members_all(self, channel_id):
        # Fetching current channel members
        result = self.fetch_from_cache(
            self._get_channel_members_all_key(channel_id),
            partial(self._fetch_channel_members, skip_members_having_role=False))
        if result is not None:
            return json.loads(result)
        else:
            return result

    def get_channel_members_no_role(self, channel_id):
        # Fetching current channel members
        result = self.fetch_from_cache(
            self._get_channel_members_no_role_key(channel_id),
            self._fetch_channel_members,
            channel_id=channel_id)
        if result is not None:
            return json.loads(result)
        else:
            return result

    def _fetch_channel_members(self, channel_id, skip_members_having_role=True):
        result = self.slack_client.conversations_members(channel=channel_id)
        members = result['members'] if 'members' in result else []
        users = {}
        for user_id in members:
            is_bot = self.is_bot(user_id)

            if is_bot:
                logging.debug(f"Skipping bot: {user_id}")
                continue

            user_name = self.get_user_name(user_id)
            existing_role = self.get_user_role_in_channel(user_id, channel_id)
            if existing_role and skip_members_having_role:
                skip_str = f"Found existing role ({existing_role} for {user_id} ({user_name}), skipping."
                logging.debug(skip_str)
                continue
            # TODO Two queries should be replaced with one. First for is_bot and second for user name
            users[user_id] = user_name
        return users

    def get_channel_name(self, channel_id):
        return self.fetch_from_cache(
            f"channel_name:{channel_id}",
            self._fetch_channel_name,
            channel_id
        )

    def is_bot(self, user_id):
        return self._cached_json_to_bool(self.fetch_from_cache(
            key=f"user_is_bot:{user_id}",
            fetch_function=self._fetch_is_bot,
            ex=self.INFINITY,
            user_id=user_id,
        ))

    def _fetch_user_name(self, user_id):
        result = self.slack_client.users_info(user=user_id)
        if result and result['user']:
            return result['user']['name']
        return None

    def _fetch_channel_name(self, channel_id):
        result = self.slack_client.conversations_info(channel=channel_id)
        if result and result['channel']:
            return result['channel']['name']
        return None

    def _fetch_is_bot(self, user_id):
        result = self.slack_client.users_info(user=user_id)
        if result and result['user']:
            return result['user']['is_bot']
        return None

    def get_user_role_in_channel(self, user_id, channel_id):
        value = self.redis_client.get(self._get_user_role_key(user_id, channel_id))
        return value if value is None else value.decode('utf-8')

    # TODO Need invalidation mechanism
    def set_user_role_in_channel(self, user_id, channel_id, role_name):
        self.redis_client.set(self._get_user_role_key(user_id, channel_id), role_name)
        self.redis_client.delete(self._get_channel_members_no_role_key(channel_id))

    def _get_user_role_key(self, user_id, channel_id):
        return f"user_id:{user_id}:channel_id:{channel_id}"

    def _get_channel_members_all_key(self, channel_id):
        return f"channel_members_all:{channel_id}"

    def _get_channel_members_no_role_key(self, channel_id):
        return f"channel_members_no_role:{channel_id}"
