import os

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./stagecontrol.db")

_is_sqlite = DATABASE_URL.startswith("sqlite")

engine_kwargs = {"echo": False}
if not _is_sqlite:
    engine_kwargs.update(
        pool_size=20,
        max_overflow=40,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
    )

engine = create_async_engine(DATABASE_URL, **engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

if not _is_sqlite:
    _ac_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
else:
    _ac_engine = engine

if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
