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


class DelayedStatus(enum.Enum):
    pending = "pending"
    sent = "sent"
    cancelled = "cancelled"


class DelayedMessage(Base):
    __tablename__ = "delayed_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("bot_users.id", ondelete="CASCADE"),
        index=True,
    )

    text: Mapped[str] = mapped_column(Text)
    buttons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    send_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[DelayedStatus] = mapped_column(Enum(DelayedStatus),  default=DelayedStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)