from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class TeamResponse(BaseModel):
    id: int
    name: str
    created_by: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TeamMemberResponse(BaseModel):
    telegram_id: int
    is_creator: bool = False
    joined_at: Optional[datetime] = None


class TeamMembersListResponse(BaseModel):
    team: TeamResponse
    members: List[TeamMemberResponse]


class AddMemberRequest(BaseModel):
    telegram_id: int
