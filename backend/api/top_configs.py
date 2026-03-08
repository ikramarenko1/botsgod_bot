from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.db.session import get_db
from backend.models.key import Key
from backend.models.top_config import TopConfig
from backend.utils.auth import get_user_team_id

router = APIRouter()


class TopConfigCreateRequest(BaseModel):
    name: str
    welcome_text: Optional[str] = None
    link_private: Optional[str] = None
    link_group: Optional[str] = None


class TopConfigUpdateRequest(BaseModel):
    name: Optional[str] = None
    welcome_text: Optional[str] = None
    link_private: Optional[str] = None
    link_group: Optional[str] = None
    is_active: Optional[bool] = None


class TopConfigResponse(BaseModel):
    id: int
    key_id: int
    name: str
    avatar_path: Optional[str]
    welcome_text: Optional[str]
    link_private: Optional[str]
    link_group: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


async def _verify_key_team(key_id: int, team_id: int, db: AsyncSession) -> Key:
    key = await db.get(Key, key_id)
    if not key or key.team_id != team_id:
        raise HTTPException(404, "Key not found")
    return key


@router.get("/keys/{key_id}/top-configs", response_model=List[TopConfigResponse])
async def list_top_configs(
    key_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    await _verify_key_team(key_id, team_id, db)

    result = await db.execute(
        select(TopConfig).where(TopConfig.key_id == key_id)
    )
    return result.scalars().all()


@router.post("/keys/{key_id}/top-configs", response_model=TopConfigResponse)
async def create_top_config(
    key_id: int,
    data: TopConfigCreateRequest,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    await _verify_key_team(key_id, team_id, db)

    config = TopConfig(
        key_id=key_id,
        name=data.name,
        welcome_text=data.welcome_text,
        link_private=data.link_private,
        link_group=data.link_group,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


@router.get("/top-configs/{config_id}", response_model=TopConfigResponse)
async def get_top_config(
    config_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(TopConfig, config_id)
    if not config:
        raise HTTPException(404, "TopConfig not found")

    await _verify_key_team(config.key_id, team_id, db)
    return config


@router.patch("/top-configs/{config_id}", response_model=TopConfigResponse)
async def update_top_config(
    config_id: int,
    data: TopConfigUpdateRequest,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(TopConfig, config_id)
    if not config:
        raise HTTPException(404, "TopConfig not found")

    await _verify_key_team(config.key_id, team_id, db)

    if data.name is not None:
        config.name = data.name
    if data.welcome_text is not None:
        config.welcome_text = data.welcome_text
    if data.link_private is not None:
        config.link_private = data.link_private
    if data.link_group is not None:
        config.link_group = data.link_group
    if data.is_active is not None:
        config.is_active = data.is_active

    await db.commit()
    await db.refresh(config)
    return config


@router.delete("/top-configs/{config_id}")
async def delete_top_config(
    config_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(TopConfig, config_id)
    if not config:
        raise HTTPException(404, "TopConfig not found")

    await _verify_key_team(config.key_id, team_id, db)

    await db.delete(config)
    await db.commit()
    return {"status": "deleted"}
