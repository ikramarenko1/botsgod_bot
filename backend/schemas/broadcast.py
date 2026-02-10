from pydantic import BaseModel
from typing import Optional, List


class BroadcastCreateRequest(BaseModel):
    region: Optional[str] = None
    text: str
    buttons: Optional[List[dict]] = None


class BroadcastResponse(BaseModel):
    id: int
    bot_id: int
    region: Optional[str]
    text: str
    buttons: Optional[List[dict]]
    status: str