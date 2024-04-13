from dataclasses import dataclass


@dataclass
class MessageHistoryData:
    last_messages_history: str
    message_txt: str
    previous_context_merged: list[str]
