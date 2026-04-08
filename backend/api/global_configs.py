import os
import io
import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from PIL import Image

from backend.db.session import get_db
from backend.models.global_config import GlobalConfig, GlobalConfigRegion
from backend.schemas.global_config import (
    GlobalConfigCreate, GlobalConfigUpdate,
    GlobalConfigRegionCreate,
)
from backend.utils.auth import verify_api_key, get_user_team_id
from backend.services.global_config_service import apply_global_config_to_all_active
from backend.models.bot import DEFAULT_AUTO_REPLY

logger = logging.getLogger("stagecontrol")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
MEDIA_DIR = os.path.join(PROJECT_ROOT, "media")

router = APIRouter()

MAX_GLOBAL_CONFIGS = 5


@router.get("/global-configs")
async def list_global_configs(
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(GlobalConfig).where(GlobalConfig.team_id == team_id)
    )
    configs = result.scalars().all()

    response = []
    for c in configs:
        regions_result = await db.execute(
            select(GlobalConfigRegion).where(GlobalConfigRegion.global_config_id == c.id)
        )
        regions = regions_result.scalars().all()
        response.append({
            "id": c.id,
            "name": c.name,
            "avatar_path": c.avatar_path,
            "welcome_text": c.welcome_text,
            "welcome_photo_path": c.welcome_photo_path,
            "welcome_buttons": c.welcome_buttons,
            "auto_reply_text": c.auto_reply_text,
            "is_active": c.is_active,
            "regions": [{"region": r.region, "name": r.name, "description": r.description, "full_description": r.full_description} for r in regions],
        })

    return response


@router.post("/global-configs")
async def create_global_config(
    data: GlobalConfigCreate,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    count = await db.execute(
        select(func.count()).where(GlobalConfig.team_id == team_id)
    )
    if count.scalar() >= MAX_GLOBAL_CONFIGS:
        raise HTTPException(400, f"Maximum {MAX_GLOBAL_CONFIGS} configs allowed")

    config = GlobalConfig(team_id=team_id, name=data.name, welcome_text="Для связи:\nИнформация:", auto_reply_text=DEFAULT_AUTO_REPLY)
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return {"id": config.id, "name": config.name, "is_active": config.is_active}


@router.get("/global-configs/{config_id}")
async def get_global_config(
    config_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(GlobalConfig, config_id)
    if not config or config.team_id != team_id:
        raise HTTPException(404, "Config not found")

    regions_result = await db.execute(
        select(GlobalConfigRegion).where(GlobalConfigRegion.global_config_id == config.id)
    )
    regions = regions_result.scalars().all()

    return {
        "id": config.id,
        "name": config.name,
        "avatar_path": config.avatar_path,
        "welcome_text": config.welcome_text,
        "welcome_photo_path": config.welcome_photo_path,
        "welcome_buttons": config.welcome_buttons,
        "auto_reply_text": config.auto_reply_text,
        "is_active": config.is_active,
        "regions": [{"region": r.region, "name": r.name, "description": r.description, "full_description": r.full_description} for r in regions],
    }


@router.patch("/global-configs/{config_id}")
async def update_global_config(
    config_id: int,
    data: GlobalConfigUpdate,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(GlobalConfig, config_id)
    if not config or config.team_id != team_id:
        raise HTTPException(404, "Config not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(config, field, value)

    await db.commit()
    await db.refresh(config)
    return {"status": "updated"}


@router.delete("/global-configs/{config_id}")
async def delete_global_config(
    config_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(GlobalConfig, config_id)
    if not config or config.team_id != team_id:
        raise HTTPException(404, "Config not found")

    gc_dir = os.path.join(MEDIA_DIR, f"global_config_{config.id}")
    if os.path.exists(gc_dir):
        import shutil
        shutil.rmtree(gc_dir, ignore_errors=True)

    await db.delete(config)
    await db.commit()
    return {"status": "deleted"}


@router.post("/global-configs/{config_id}/activate")
async def activate_global_config(
    config_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    config = await db.get(GlobalConfig, config_id)
    if not config or config.team_id != team_id:
        raise HTTPException(404, "Config not found")

    # Деактивировать текущий активный
    result = await db.execute(
        select(GlobalConfig).where(
            GlobalConfig.team_id == team_id,
            GlobalConfig.is_active == True,
        )
    )
    for c in result.scalars().all():
        c.is_active = False

    config.is_active = True
    await db.commit()

    # Применить ко всем active ботам
    apply_result = await apply_global_config_to_all_active(db, config, team_id, MEDIA_DIR, force=True)

    return {
        "status": "activated",
        "applied": apply_result["applied"],
        "skipped_bots": apply_result["skipped_bots"],
        "applied_bots": apply_result["applied_bots"],
        "api_errors": apply_result.get("api_errors", {}),
    }


@router.post("/global-configs/{config_id}/deactivate")
async def deactivate_global_config(
    config_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(GlobalConfig, config_id)
    if not config or config.team_id != team_id:
        raise HTTPException(404, "Config not found")

    config.is_active = False
    await db.commit()
    return {"status": "deactivated"}


@router.post("/global-configs/{config_id}/reapply")
async def reapply_global_config(
    config_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    config = await db.get(GlobalConfig, config_id)
    if not config or config.team_id != team_id:
        raise HTTPException(404, "Config not found")

    if not config.is_active:
        raise HTTPException(400, "Config is not active")

    apply_result = await apply_global_config_to_all_active(db, config, team_id, MEDIA_DIR, force=True)

    return {
        "status": "reapplied",
        "applied": apply_result["applied"],
        "skipped_bots": apply_result["skipped_bots"],
        "applied_bots": apply_result["applied_bots"],
        "api_errors": apply_result.get("api_errors", {}),
    }


@router.post("/global-configs/{config_id}/avatar")
async def upload_global_config_avatar(
    config_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    config = await db.get(GlobalConfig, config_id)
    if not config or config.team_id != team_id:
        raise HTTPException(404, "Config not found")

    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(400, "Only images allowed")

    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 5MB)")

    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        raise HTTPException(400, "Invalid image file")

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=95)
    jpg_bytes = buffer.getvalue()

    gc_dir = os.path.join(MEDIA_DIR, f"global_config_{config.id}")
    os.makedirs(gc_dir, exist_ok=True)
    avatar_path = os.path.join(gc_dir, "avatar.jpg")

    with open(avatar_path, "wb") as f:
        f.write(jpg_bytes)

    config.avatar_path = avatar_path
    await db.commit()

    return {"status": "avatar_uploaded"}


@router.post("/global-configs/{config_id}/welcome-photo")
async def upload_global_config_welcome_photo(
    config_id: int,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    config = await db.get(GlobalConfig, config_id)
    if not config or config.team_id != team_id:
        raise HTTPException(404, "Config not found")

    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 5MB)")

    gc_dir = os.path.join(MEDIA_DIR, f"global_config_{config.id}")
    os.makedirs(gc_dir, exist_ok=True)

    ext = os.path.splitext(file.filename or "photo.jpg")[1] or ".jpg"
    photo_path = os.path.join(gc_dir, f"welcome{ext}")

    with open(photo_path, "wb") as f:
        f.write(raw)

    config.welcome_photo_path = photo_path
    await db.commit()

    return {"status": "photo_uploaded"}


@router.post("/global-configs/{config_id}/regions")
async def upsert_global_config_region(
    config_id: int,
    data: GlobalConfigRegionCreate,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(GlobalConfig, config_id)
    if not config or config.team_id != team_id:
        raise HTTPException(404, "Config not found")

    result = await db.execute(
        select(GlobalConfigRegion).where(
            GlobalConfigRegion.global_config_id == config.id,
            GlobalConfigRegion.region == data.region,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.name = data.name
        existing.description = data.description
        existing.full_description = data.full_description
    else:
        region = GlobalConfigRegion(
            global_config_id=config.id,
            region=data.region,
            name=data.name,
            description=data.description,
            full_description=data.full_description,
        )
        db.add(region)

    await db.commit()
    return {"status": "region_saved"}


@router.delete("/global-configs/{config_id}/regions/{region}")
async def delete_global_config_region(
    config_id: int,
    region: str,
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    config = await db.get(GlobalConfig, config_id)
    if not config or config.team_id != team_id:
        raise HTTPException(404, "Config not found")

    result = await db.execute(
        select(GlobalConfigRegion).where(
            GlobalConfigRegion.global_config_id == config.id,
            GlobalConfigRegion.region == region,
        )
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(404, "Region not found")

    await db.delete(existing)
    await db.commit()
    return {"status": "region_deleted"}
