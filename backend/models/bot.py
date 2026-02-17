from typing import Optional

from sqlalchemy import String, DateTime, Enum, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import enum

from backend.db.base import Base


class BotRole(enum.Enum):
    active = "active"
    reserve = "reserve"
    disabled = "disabled"


class BotStatus(enum.Enum):
    alive = "alive"
    degraded = "degraded"
    dead = "dead"


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True)
    token: Mapped[str] = mapped_column(String(255))
    role: Mapped[BotRole] = mapped_column(Enum(BotRole), default=BotRole.reserve)
    status: Mapped[BotStatus] = mapped_column(Enum(BotStatus), default=BotStatus.alive)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_applied_region: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    last_applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    delayed_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delayed_buttons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    delayed_delay_minutes: Mapped[Optional[int]] = mapped_column(nullable=True)

    configs = relationship(
        "BotConfig",
        back_populates="bot",
        cascade="all, delete-orphan",
    )