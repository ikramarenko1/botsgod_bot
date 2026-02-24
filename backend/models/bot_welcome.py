from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, ForeignKey, Text, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class BotWelcome(Base):
    __tablename__ = "bot_welcome_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"),
        unique=True, index=True
    )

    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    photo_path: Mapped[Optional[str]] = mapped_column(nullable=True)
    buttons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)