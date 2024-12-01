from pydantic import BaseModel
class MessageHistoryData(BaseModel):
    last_messages_history: str
    message_txt: str
    previous_context_merged: list[str]
