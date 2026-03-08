from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class WelcomeCreateRequest(BaseModel):
    text: Optional[str] = None
    photo_path: Optional[str] = None
    buttons: Optional[list] = None
    is_enabled: Optional[bool] = True


class WelcomeResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    bot_id: int
    text: Optional[str]
    photo_path: Optional[str]
    buttons: Optional[list]
    is_enabled: bool
    created_at: datetime