from typing import Optional
from pydantic import BaseModel


class BotConfigCreate(BaseModel):
    region: str
    name: str
    description: Optional[str] = None


class BotConfigResponse(BaseModel):
    id: int
    region: str
    name: str
    description: Optional[str]