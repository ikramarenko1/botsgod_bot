from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func

from backend.models.bot import Bot, BotRole, BotStatus
from backend.models.broadcast import Broadcast, BroadcastStatus
from backend.models.team import TeamMember

STUCK_BROADCAST_TIMEOUT_MIN = 10


async def get_scheduled_broadcasts(db: AsyncSession) -> list[dict]:
    now = datetime.utcnow()
    stuck_threshold = now - timedelta(minutes=STUCK_BROADCAST_TIMEOUT_MIN)

    result = await db.execute(
        select(Broadcast, Bot)
        .join(Bot, Broadcast.bot_id == Bot.id)
        .where(
            Bot.role.in_([BotRole.active, BotRole.farm]),
            Bot.status == BotStatus.alive,
            or_(
                and_(
                    Broadcast.status == BroadcastStatus.scheduled,
                    or_(
                        Broadcast.scheduled_at == None,
                        Broadcast.scheduled_at <= now
                    )
                ),
                and_(
                    Broadcast.status == BroadcastStatus.sending,
                    or_(
                        Broadcast.started_at == None,
                        Broadcast.started_at <= stuck_threshold
                    )
                ),
            )
        )
    )

    rows = result.all()

    broadcasts_list = []
    for broadcast, bot in rows:
        entry = {
            "id": broadcast.id,
            "bot_id": broadcast.bot_id,
            "bot_ids": broadcast.bot_ids,
            "owner_id": bot.owner_telegram_id,
            "text": broadcast.text,
            "buttons": broadcast.buttons,
            "token": bot.token,
        }
        if bot.team_id:
            members_result = await db.execute(
                select(TeamMember.telegram_id).where(TeamMember.team_id == bot.team_id)
            )
            entry["notify_ids"] = members_result.scalars().all()
        broadcasts_list.append(entry)

    return broadcasts_list


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
