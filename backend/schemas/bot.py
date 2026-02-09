from pydantic import BaseModel
from typing import List, Literal
from sqlalchemy.orm import relationship


class BotAddRequest(BaseModel):
    token: str


class BotResponse(BaseModel):
    id: int
    username: str
    role: str
    status: str


class BotListResponse(BaseModel):
    bots: List[BotResponse]


class BotRoleUpdateRequest(BaseModel):
    role: str


class BotStatusUpdate(BaseModel):
    status: Literal["alive", "degraded", "dead"]


class BotApplyConfigRequest(BaseModel):
    region: str