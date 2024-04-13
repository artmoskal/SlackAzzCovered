from dataclasses import dataclass


@dataclass
class EventData:
    channel_id: str
    channel_name: str
    text: str
    user_id: str
    user_name: str
    user_role: str
