from pydantic import BaseModel

class SendMessageAction(BaseModel):
    channel_id: str
    text: str
    #add mention array versus inline!
