from datetime import datetime

from sqlalchemy import String, DateTime, BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="Моя команда")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by = mapped_column(BigInteger, nullable=False)


class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_id = mapped_column(BigInteger, nullable=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("team_id", "telegram_id"),)
