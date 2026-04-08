import asyncio

from sqlalchemy import text

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
from backend.models.team import Team, TeamMember
from backend.models.global_config import GlobalConfig, GlobalConfigRegion


async def column_exists(conn, table_name: str, column_name: str) -> bool:
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    columns = result.fetchall()
    return any(col[1] == column_name for col in columns)


async def migrate_auto_reply(conn):
    if not await column_exists(conn, "bots", "auto_reply_text"):
        await conn.execute(text("""
            ALTER TABLE bots
            ADD COLUMN auto_reply_text TEXT
            DEFAULT 'Свяжитесь с нами по контактам в сообщении выше👆👆👆'
        """))


async def migrate_no_reserve_alert(conn):
    if not await column_exists(conn, "bots", "last_no_reserve_alert_at"):
        await conn.execute(text("""
            ALTER TABLE bots
            ADD COLUMN last_no_reserve_alert_at DATETIME
        """))


async def migrate_full_description(conn):
    for table in ["global_config_regions", "bot_configs"]:
        if not await column_exists(conn, table, "full_description"):
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN full_description TEXT"))


async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await migrate_auto_reply(conn)
        await migrate_no_reserve_alert(conn)
        await migrate_full_description(conn)


asyncio.run(init())