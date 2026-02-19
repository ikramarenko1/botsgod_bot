from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from backend.db.base import Base


class ReplacementLog(Base):
    __tablename__ = "replacement_logs"

    id = Column(Integer, primary_key=True)
    dead_bot_id = Column(Integer, nullable=False)
    dead_bot_username = Column(String, nullable=False)

    new_bot_id = Column(Integer, nullable=False)
    new_bot_username = Column(String, nullable=False)

    replaced_at = Column(DateTime, default=datetime.utcnow)