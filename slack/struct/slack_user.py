from typing import Optional

from pydantic import BaseModel


class SlackUser(BaseModel):
    id: str
    name: str
    role: Optional[str] = None
