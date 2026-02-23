from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from typing import AsyncGenerator

DATABASE_URL = "sqlite+aiosqlite:///./stagecontrol.db"

engine = create_async_engine(DATABASE_URL, echo=False,)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False,)


@event.listens_for(engine.sync_engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session