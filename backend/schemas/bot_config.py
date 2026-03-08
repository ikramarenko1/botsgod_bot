from typing import Optional
from pydantic import BaseModel


class BotConfigCreate(BaseModel):
    region: str
    name: str
    description: Optional[str] = None


class BotConfigResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    region: str
    name: str
    description: Optional[str]