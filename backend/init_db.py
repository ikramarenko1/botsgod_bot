import asyncio

from backend.db.session import engine
from backend.db.base import Base

from backend.models.bot import Bot
from backend.models.bot_config import BotConfig
from backend.models.broadcast import Broadcast
from backend.models.user import BotUser
from backend.models.bot_welcome import BotWelcome
from backend.models.delayed_message import DelayedMessage
from backend.models.replacement_log import ReplacementLog
from backend.models.key import Key
from backend.models.top_config import TopConfig


async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(init())
