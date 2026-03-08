from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from backend.models.bot import Bot, BotRole, BotStatus
from backend.models.broadcast import Broadcast, BroadcastStatus


async def get_scheduled_broadcasts(db: AsyncSession) -> list[dict]:
    now = datetime.utcnow()

    result = await db.execute(
        select(Broadcast, Bot)
        .join(Bot, Broadcast.bot_id == Bot.id)
        .where(
            Broadcast.status == BroadcastStatus.scheduled,
            Bot.role.in_([BotRole.active, BotRole.farm]),
            Bot.status == BotStatus.alive,
            or_(
                Broadcast.scheduled_at == None,
                Broadcast.scheduled_at <= now
            )
        )
    )

    rows = result.all()

    return [
        {
            "id": broadcast.id,
            "bot_id": broadcast.bot_id,
            "bot_ids": broadcast.bot_ids,
            "owner_id": bot.owner_telegram_id,
            "text": broadcast.text,
            "buttons": broadcast.buttons,
            "token": bot.token,
        }
        for broadcast, bot in rows
    ]


async def create_broadcast(db: AsyncSession, bot: Bot, data) -> Broadcast:
    now = datetime.utcnow()
    scheduled_at = data.scheduled_at

    if scheduled_at:
        status = BroadcastStatus.scheduled
    else:
        status = BroadcastStatus.draft

    broadcast = Broadcast(
        bot_id=bot.id,
        region=data.region,
        text=data.text,
        buttons=data.buttons,
        bot_ids=getattr(data, 'bot_ids', None),
        scheduled_at=scheduled_at,
        status=status,
    )

    db.add(broadcast)
    await db.commit()
    await db.refresh(broadcast)
    return broadcast


async def send_broadcast_now(db: AsyncSession, broadcast: Broadcast) -> Broadcast:
    if broadcast.status not in (
        BroadcastStatus.draft,
        BroadcastStatus.failed,
    ):
        raise ValueError(f"Cannot send broadcast with status {broadcast.status.value}")

    broadcast.scheduled_at = datetime.utcnow()
    broadcast.status = BroadcastStatus.scheduled

    await db.commit()
    await db.refresh(broadcast)
    return broadcast
