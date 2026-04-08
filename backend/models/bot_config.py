from typing import Optional

from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class BotConfig(Base):
    __tablename__ = "bot_configs"

    id: Mapped[int] = mapped_column(primary_key=True)

    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"),
        index=True,
    )

    region: Mapped[str] = mapped_column(String(32))

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    full_description: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    bot = relationship("Bot", back_populates="configs")

    __table_args__ = (
        UniqueConstraint("bot_id", "region", name="uq_bot_region"),
    )