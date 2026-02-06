from pydantic import BaseModel
from typing import List, Literal


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
    status: Literal["alive", "dead"]