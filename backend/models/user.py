from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, BigInteger, Boolean, UniqueConstraint, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from backend.db.base import Base


class BotUser(Base):
    __tablename__ = "bot_users"
    __table_args__ = (
        UniqueConstraint("bot_id", "telegram_id", name="uq_bot_users_botid_tgid"),
        Index("ix_bot_users_bot_id_is_active", "bot_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"),
        index=True
    )

    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)

    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_premium: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)