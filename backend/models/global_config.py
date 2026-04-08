from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, Boolean, DateTime, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


class GlobalConfig(Base):
    __tablename__ = "global_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    avatar_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    welcome_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    welcome_photo_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    welcome_buttons: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    auto_reply_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    regions: Mapped[list["GlobalConfigRegion"]] = relationship(
        back_populates="global_config", cascade="all, delete-orphan"
    )


class GlobalConfigRegion(Base):
    __tablename__ = "global_config_regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    global_config_id: Mapped[int] = mapped_column(
        ForeignKey("global_configs.id", ondelete="CASCADE"), index=True
    )
    region: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    full_description: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    global_config: Mapped["GlobalConfig"] = relationship(back_populates="regions")

    __table_args__ = (
        UniqueConstraint("global_config_id", "region", name="uq_gc_region"),
    )
