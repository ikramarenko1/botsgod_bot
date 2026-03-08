import os
from typing import Optional

from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.db.session import get_db
from backend.models.bot import Bot
from backend.models.broadcast import Broadcast, BroadcastStatus
from backend.models.bot import BotRole, BotStatus
from backend.models.team import Team, TeamMember

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")


async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    if not INTERNAL_API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    if x_api_key != INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


async def get_owner_id(x_telegram_id: Optional[str] = Header(None)):
    if not x_telegram_id:
        raise HTTPException(status_code=400, detail="X-TELEGRAM-ID header required")
    return int(x_telegram_id)


async def get_user_team_id(
    owner_id: int = Depends(get_owner_id),
    db: AsyncSession = Depends(get_db),
) -> int:
    """Возвращает team_id пользователя. Автоматически создаёт команду если её нет."""
    result = await db.execute(
        select(TeamMember.team_id).where(TeamMember.telegram_id == owner_id)
    )
    team_id = result.scalar_one_or_none()
    if team_id:
        return team_id

    team = Team(name="Моя команда", created_by=owner_id)
    db.add(team)
    await db.flush()

    member = TeamMember(team_id=team.id, telegram_id=owner_id)
    db.add(member)
    await db.flush()

    return team.id


async def get_owned_bot(
    bot_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    bot = await db.get(Bot, bot_id)

    if not bot or bot.team_id != team_id:
        raise HTTPException(status_code=404, detail="Bot not found")

    return bot


async def get_owned_broadcast(
    broadcast_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Broadcast, Bot)
        .join(Bot, Broadcast.bot_id == Bot.id)
        .where(
            Broadcast.id == broadcast_id,
            Bot.team_id == team_id,
        )
    )

    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    broadcast, _ = row
    return broadcast
