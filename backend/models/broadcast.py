import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer,
    ForeignKey,
    DateTime,
    Enum,
    Text,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class BroadcastStatus(enum.Enum):
    draft = "draft"
    scheduled = "scheduled"
    sending = "sending"
    sent = "sent"
    failed = "failed"
    cancelled = "cancelled"


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"),
        index=True,
    )
    region: Mapped[Optional[str]] = mapped_column(nullable=True)

    text: Mapped[str] = mapped_column(Text)
    buttons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    bot_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    status: Mapped[BroadcastStatus] = mapped_column(
        Enum(BroadcastStatus),
        default=BroadcastStatus.draft,
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )

    total_users: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)