from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.bot import Bot, BotRole, BotStatus
from backend.models.delayed_message import DelayedMessage, DelayedStatus
from backend.models.user import BotUser


async def get_pending_delayed(db: AsyncSession) -> list[dict]:
    now = datetime.utcnow()

    result = await db.execute(
        select(DelayedMessage, Bot, BotUser)
        .join(Bot, DelayedMessage.bot_id == Bot.id)
        .join(BotUser, DelayedMessage.user_id == BotUser.id)
        .where(
            Bot.role == BotRole.active,
            Bot.status == BotStatus.alive,
            DelayedMessage.status == DelayedStatus.pending,
            DelayedMessage.send_at <= now,
        )
    )

    rows = result.all()

    return [
        {
            "id": msg.id,
            "telegram_id": user.telegram_id,
            "text": msg.text,
            "buttons": msg.buttons,
            "photo_path": bot.delayed_photo_path,
            "token": bot.token,
        }
        for msg, bot, user in rows
    ]
