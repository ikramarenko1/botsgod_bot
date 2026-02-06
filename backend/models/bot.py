from sqlalchemy import String, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column
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