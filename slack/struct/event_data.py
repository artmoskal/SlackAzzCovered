from datetime import datetime

from pydantic import BaseModel

from slack.struct.slack_user import SlackUser

class EventData(BaseModel):
    channel_id: str
    channel_name: str
    text: str
    ts: datetime
    user: SlackUser
