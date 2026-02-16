from datetime import datetime
from pydantic import BaseModel
from typing import Optional, List, Literal


class BroadcastCreateRequest(BaseModel):
    region: Optional[str] = None
    text: str
    buttons: Optional[List[dict]] = None
    scheduled_at: Optional[datetime] = None


class BroadcastResponse(BaseModel):
    id: int
    bot_id: int
    region: Optional[str]
    text: str
    buttons: Optional[List[dict]]
    status: str

    total_users: int = 0
    sent_count: int = 0
    failed_count: int = 0

    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    scheduled_at: Optional[datetime] = None


class BroadcastStatusUpdate(BaseModel):
    status: Literal[
        "draft",
        "scheduled",
        "sending",
        "sent",
        "failed",
        "cancelled",
    ]


class BroadcastScheduleUpdate(BaseModel):
    scheduled_at: datetime