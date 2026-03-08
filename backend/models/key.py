from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Text, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Key(Base):
    __tablename__ = "keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_telegram_id = mapped_column(BigInteger, nullable=False, index=True)
    team_id = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    short_name: Mapped[str] = mapped_column(String(50))
    farm_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="Здравствуйте! Спасибо за обращение.")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
