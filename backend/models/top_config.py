from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class TopConfig(Base):
    __tablename__ = "top_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    key_id: Mapped[int] = mapped_column(ForeignKey("keys.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    avatar_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    welcome_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link_private: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    link_group: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
