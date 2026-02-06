import asyncio

from backend.db.session import engine
from backend.db.base import Base
from backend.models.bot import Bot


async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(init())