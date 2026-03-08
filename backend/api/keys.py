from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.db.session import get_db
from backend.models.key import Key
from backend.models.bot import Bot
from backend.utils.auth import get_owner_id, get_user_team_id

router = APIRouter()


class KeyCreateRequest(BaseModel):
    full_name: str
    short_name: str


class KeyUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    short_name: Optional[str] = None
    farm_text: Optional[str] = None


class KeyResponse(BaseModel):
    id: int
    full_name: str
    short_name: str
    farm_text: Optional[str]

    class Config:
        from_attributes = True


class KeyDetailResponse(KeyResponse):
    bots: List[dict] = []


@router.get("/keys", response_model=List[KeyResponse])
async def list_keys(
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Key).where(Key.team_id == team_id)
    )
    return result.scalars().all()


@router.post("/keys", response_model=KeyResponse)
async def create_key(
    data: KeyCreateRequest,
    owner_id: int = Depends(get_owner_id),
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    key = Key(
        owner_telegram_id=owner_id,
        team_id=team_id,
        full_name=data.full_name,
        short_name=data.short_name,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return key


@router.get("/keys/{key_id}")
async def get_key(
    key_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(Key, key_id)
    if not key or key.team_id != team_id:
        raise HTTPException(404, "Key not found")

    result = await db.execute(
        select(Bot).where(Bot.key_id == key_id)
    )
    bots = result.scalars().all()

    return {
        "id": key.id,
        "full_name": key.full_name,
        "short_name": key.short_name,
        "farm_text": key.farm_text,
        "bots": [
            {"id": b.id, "username": b.username, "role": b.role.value, "status": b.status.value}
            for b in bots
        ],
    }


@router.patch("/keys/{key_id}", response_model=KeyResponse)
async def update_key(
    key_id: int,
    data: KeyUpdateRequest,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(Key, key_id)
    if not key or key.team_id != team_id:
        raise HTTPException(404, "Key not found")

    if data.full_name is not None:
        key.full_name = data.full_name
    if data.short_name is not None:
        key.short_name = data.short_name
    if data.farm_text is not None:
        key.farm_text = data.farm_text

    await db.commit()
    await db.refresh(key)
    return key


@router.delete("/keys/{key_id}")
async def delete_key(
    key_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(Key, key_id)
    if not key or key.team_id != team_id:
        raise HTTPException(404, "Key not found")

    # Отвязываем ботов
    result = await db.execute(select(Bot).where(Bot.key_id == key_id))
    bots = result.scalars().all()
    for b in bots:
        b.key_id = None

    await db.delete(key)
    await db.commit()
    return {"status": "deleted"}


@router.post("/keys/{key_id}/bots/{bot_id}")
async def assign_bot_to_key(
    key_id: int,
    bot_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(Key, key_id)
    if not key or key.team_id != team_id:
        raise HTTPException(404, "Key not found")

    bot = await db.get(Bot, bot_id)
    if not bot or bot.team_id != team_id:
        raise HTTPException(404, "Bot not found")

    bot.key_id = key_id
    await db.commit()
    return {"status": "assigned"}


@router.delete("/keys/{key_id}/bots/{bot_id}")
async def unassign_bot_from_key(
    key_id: int,
    bot_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(Key, key_id)
    if not key or key.team_id != team_id:
        raise HTTPException(404, "Key not found")

    bot = await db.get(Bot, bot_id)
    if not bot or bot.team_id != team_id:
        raise HTTPException(404, "Bot not found")

    if bot.key_id == key_id:
        bot.key_id = None
        await db.commit()

    return {"status": "unassigned"}
