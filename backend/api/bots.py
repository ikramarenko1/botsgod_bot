import io
import os
import csv
import json
import logging
from datetime import datetime, timedelta
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from PIL import Image

from backend.db.session import get_db
from backend.models.bot import Bot, BotRole, BotStatus
from backend.models.bot_config import BotConfig
from backend.models.broadcast import Broadcast, BroadcastStatus
from backend.models.user import BotUser
from backend.schemas.bot import BotAddRequest, BotResponse, BotRoleUpdateRequest, BotStatusUpdate, BotApplyConfigRequest
from backend.schemas.bot_config import BotConfigCreate, BotConfigResponse
from backend.utils.auth import verify_api_key, get_owner_id, get_owned_bot
from backend.services.bot_service import (
    add_bot as svc_add_bot,
    health_check_bot as svc_health_check_bot,
    health_check_all as svc_health_check_all,
    enable_bot as svc_enable_bot,
    disable_bot as svc_disable_bot,
    delete_bot as svc_delete_bot,
)
from backend.services.replacement_service import (
    get_replacement_logs_for_bot,
)

logger = logging.getLogger("stagecontrol")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
MEDIA_DIR = os.path.join(PROJECT_ROOT, "media")

router = APIRouter()


@router.get("/bots", response_model=List[BotResponse])
async def list_bots(
    owner_id: int = Depends(get_owner_id),
    db: AsyncSession = Depends(get_db)
):
    from backend.models.key import Key

    result = await db.execute(
        select(Bot).where(Bot.owner_telegram_id == owner_id)
    )
    bots = result.scalars().all()

    key_ids = {b.key_id for b in bots if b.key_id}
    keys_map = {}
    if key_ids:
        keys_result = await db.execute(select(Key).where(Key.id.in_(key_ids)))
        keys_map = {k.id: k.short_name for k in keys_result.scalars().all()}

    return [
        BotResponse(
            id=b.id,
            username=b.username,
            role=b.role.value,
            status=b.status.value,
            key_id=b.key_id,
            key_name=keys_map.get(b.key_id) if b.key_id else None,
        )
        for b in bots
    ]


@router.get("/bots/{bot_id}/configs", response_model=list[BotConfigResponse])
async def list_bot_configs(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BotConfig).where(BotConfig.bot_id == bot.id)
    )
    return result.scalars().all()


@router.get("/bots/{bot_id}/users")
async def list_bot_users(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db)
):
    query = select(BotUser).where(
        BotUser.bot_id == bot.id,
        BotUser.is_active == True,
    )

    result = await db.execute(query)
    users = result.scalars().all()

    return [
        {
            "id": u.id,
            "telegram_id": u.telegram_id,
        }
        for u in users
    ]


@router.get("/bots/{bot_id}/users/export")
async def export_bot_users(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
    format: str = Query("csv")
):
    result = await db.execute(
        select(BotUser).where(
            BotUser.bot_id == bot.id,
            BotUser.is_active == True,
        )
    )
    users = result.scalars().all()

    if format not in ("csv", "txt", "json"):
        raise HTTPException(400, "Invalid format")

    total = len(users)
    premium = sum(1 for u in users if u.is_premium)
    normal = total - premium

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            "telegram_id",
            "username",
            "first_name",
            "last_name",
            "language_code",
            "is_premium",
            "created_at",
            "last_seen_at",
        ])

        for u in users:
            writer.writerow([
                u.telegram_id,
                u.username or "",
                u.first_name or "",
                u.last_name or "",
                u.language_code or "",
                bool(u.is_premium),
                u.created_at.isoformat() if u.created_at else "",
                u.last_seen_at.isoformat() if u.last_seen_at else "",
            ])

        content = output.getvalue()
        filename = f"bot_{bot.id}_users.csv"
        media_type = "text/csv"

    elif format == "txt":
        output = io.StringIO()

        output.write(f"Всего пользователей: {total}\n")
        output.write(f"Премиум пользователей: {premium}\n")
        output.write(f"Обычных пользователей: {normal}\n\n")

        output.write("Формат: Telegram ID;Язык;Premium;Дата регистрации\n\n")

        for u in users:
            line = (
                f"{u.telegram_id};"
                f"{u.language_code or ''};"
                f"{bool(u.is_premium)};"
                f"{u.created_at.isoformat() if u.created_at else ''}\n"
            )
            output.write(line)

        content = output.getvalue()
        filename = f"bot_{bot.id}_users.txt"
        media_type = "text/plain"

    else:
        data = [
            {
                "telegram_id": u.telegram_id,
                "username": u.username,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "language_code": u.language_code,
                "is_premium": bool(u.is_premium),
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
            }
            for u in users
        ]

        content = json.dumps(data, indent=2)
        filename = f"bot_{bot.id}_users.json"
        media_type = "application/json"

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Total-Users": str(total),
            "X-Premium-Users": str(premium),
            "X-Normal-Users": str(normal),
        },
    )


@router.get("/bots/{bot_id}/stats")
async def bot_stats(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.utcnow()
    last_hour = now - timedelta(hours=1)
    last_day = now - timedelta(days=1)
    last_week = now - timedelta(days=7)

    total_users = (
        await db.execute(
            select(func.count()).where(BotUser.bot_id == bot.id)
        )
    ).scalar() or 0

    premium_users = (
        await db.execute(
            select(func.count()).where(
                BotUser.bot_id == bot.id,
                BotUser.is_premium == True,
            )
        )
    ).scalar() or 0

    normal_users = total_users - premium_users

    active_last_24h = (
        await db.execute(
            select(func.count()).where(
                BotUser.bot_id == bot.id,
                BotUser.last_seen_at >= last_day,
            )
        )
    ).scalar() or 0

    geo_result = await db.execute(
        select(BotUser.language_code, func.count())
        .where(BotUser.bot_id == bot.id)
        .group_by(BotUser.language_code)
    )

    geo = {row[0] or "unknown": row[1] for row in geo_result.all()}

    growth_hour = (
        await db.execute(
            select(func.count()).where(
                BotUser.bot_id == bot.id,
                BotUser.created_at >= last_hour,
            )
        )
    ).scalar() or 0

    growth_day = (
        await db.execute(
            select(func.count()).where(
                BotUser.bot_id == bot.id,
                BotUser.created_at >= last_day,
            )
        )
    ).scalar() or 0

    growth_week = (
        await db.execute(
            select(func.count()).where(
                BotUser.bot_id == bot.id,
                BotUser.created_at >= last_week,
            )
        )
    ).scalar() or 0

    total_broadcasts = (
        await db.execute(
            select(func.count()).where(Broadcast.bot_id == bot.id)
        )
    ).scalar() or 0

    sent_broadcasts = (
        await db.execute(
            select(func.count()).where(
                Broadcast.bot_id == bot.id,
                Broadcast.status == BroadcastStatus.sent,
            )
        )
    ).scalar() or 0

    failed_broadcasts = (
        await db.execute(
            select(func.count()).where(
                Broadcast.bot_id == bot.id,
                Broadcast.status == BroadcastStatus.failed,
            )
        )
    ).scalar() or 0

    draft_broadcasts = (
        await db.execute(
            select(func.count()).where(
                Broadcast.bot_id == bot.id,
                Broadcast.status == BroadcastStatus.draft,
            )
        )
    ).scalar() or 0

    return {
        "total_users": total_users,
        "premium_users": premium_users,
        "normal_users": normal_users,
        "active_last_24h": active_last_24h,
        "geo": geo,
        "growth_hour": growth_hour,
        "growth_day": growth_day,
        "growth_week": growth_week,
        "total_broadcasts": total_broadcasts,
        "sent_broadcasts": sent_broadcasts,
        "failed_broadcasts": failed_broadcasts,
        "draft_broadcasts": draft_broadcasts,
    }


@router.get("/bots/{bot_id}/replacement-logs")
async def get_bot_replacement_logs(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
):
    return await get_replacement_logs_for_bot(db, bot.id, page, per_page)


@router.post("/bots/add", response_model=BotResponse)
async def add_bot(
    data: BotAddRequest,
    owner_id: int = Depends(get_owner_id),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    try:
        bot = await svc_add_bot(db, data.token, owner_id, MEDIA_DIR, role=data.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return BotResponse(
        id=bot.id,
        username=bot.username,
        role=bot.role.value,
        status=bot.status.value,
    )


@router.post("/bots/{bot_id}/health-check", response_model=BotResponse)
async def health_check_bot(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
):
    bot = await svc_health_check_bot(db, bot)

    return BotResponse(
        id=bot.id,
        username=bot.username,
        role=bot.role.value,
        status=bot.status.value,
    )


@router.post("/bots/health-check/all")
async def health_check_all(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    checked = await svc_health_check_all(db)
    return {"checked": checked}


@router.post("/bots/{bot_id}/configs", response_model=BotConfigResponse)
async def upsert_bot_config(
    data: BotConfigCreate,
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    result = await db.execute(
        select(BotConfig).where(
            BotConfig.bot_id == bot.id,
            BotConfig.region == data.region,
        )
    )
    config = result.scalar_one_or_none()

    if config:
        config.name = data.name
        config.description = data.description
    else:
        config = BotConfig(
            bot_id=bot.id,
            region=data.region,
            name=data.name,
            description=data.description,
        )
        db.add(config)

    await db.commit()
    await db.refresh(config)
    return config


@router.post("/bots/{bot_id}/configs/apply")
async def apply_bot_config(
    data: BotApplyConfigRequest,
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    result = await db.execute(
        select(BotConfig).where(
            BotConfig.bot_id == bot.id,
            BotConfig.region == data.region,
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"Config for region '{data.region}' not found",
        )

    payload_name = {"name": config.name}
    payload_desc = {"description": config.description}

    if data.region != "default":
        payload_name["language_code"] = data.region
        payload_desc["language_code"] = data.region

    async with httpx.AsyncClient(timeout=10) as client:
        resp_name = await client.post(
            f"https://api.telegram.org/bot{bot.token}/setMyName",
            json=payload_name,
        )

        if resp_name.status_code != 200 or not resp_name.json().get("ok"):
            raise HTTPException(
                status_code=502,
                detail="Failed to set bot name in Telegram",
            )

        resp_desc = await client.post(
            f"https://api.telegram.org/bot{bot.token}/setMyDescription",
            json=payload_desc,
        )

        if resp_desc.status_code != 200 or not resp_desc.json().get("ok"):
            raise HTTPException(
                status_code=502,
                detail="Failed to set bot description in Telegram",
            )

    bot.last_applied_region = data.region
    bot.last_applied_at = datetime.utcnow()

    await db.commit()
    await db.refresh(bot)

    return {
        "bot_id": bot.id,
        "username": bot.username,
        "applied_region": data.region,
        "applied_at": bot.last_applied_at,
    }


@router.post("/bots/{bot_id}/avatar")
async def update_bot_avatar(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    _: None = Depends(verify_api_key),
):
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

    payload = {
        "type": "static",
        "photo": "attach://file"
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot.token}/setMyProfilePhoto",
            data={"photo": json.dumps(payload)},
            files={"file": ("avatar.jpg", jpg_bytes, "image/jpeg")},
        )

    if resp.status_code != 200:
        raise HTTPException(502, f"Telegram HTTP error: {resp.text}")

    data = resp.json()
    if not data.get("ok"):
        raise HTTPException(502, f"Telegram error: {resp.text}")

    bot_dir = os.path.join(MEDIA_DIR, f"bot_{bot.id}")
    os.makedirs(bot_dir, exist_ok=True)

    avatar_path = os.path.join(bot_dir, "avatar.jpg")

    if bot.avatar_path and os.path.exists(bot.avatar_path):
        try:
            os.remove(bot.avatar_path)
        except Exception as e:
            logger.warning(f"Failed to remove old avatar: {e}")

    with open(avatar_path, "wb") as f:
        f.write(jpg_bytes)

    bot.avatar_path = avatar_path
    await db.commit()

    return {"status": "avatar_updated"}


@router.patch("/bots/{bot_id}/role", response_model=BotResponse)
async def update_bot_role(
    data: BotRoleUpdateRequest,
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    if data.role not in ("active", "reserve", "farm", "disabled"):
        raise HTTPException(status_code=400, detail="Invalid role")

    bot.role = BotRole(data.role)
    await db.commit()
    await db.refresh(bot)

    if data.role in ("active", "farm"):
        try:
            from backend.services.telegram_service import set_webhook
            await set_webhook(bot)
        except Exception:
            pass
    elif data.role in ("reserve", "disabled"):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"https://api.telegram.org/bot{bot.token}/deleteWebhook")
        except Exception:
            pass

    return BotResponse(
        id=bot.id,
        username=bot.username,
        role=bot.role.value,
        status=bot.status.value,
    )


@router.patch("/bots/{bot_id}/status", response_model=BotResponse)
async def update_bot_status(
    data: BotStatusUpdate,
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
):
    bot.status = BotStatus(data.status)
    await db.commit()
    await db.refresh(bot)

    return BotResponse(
        id=bot.id,
        username=bot.username,
        role=bot.role.value,
        status=bot.status.value,
    )


@router.patch("/bots/{bot_id}/enable")
async def enable_bot(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    await svc_enable_bot(db, bot)
    return {"status": "enabled"}


@router.patch("/bots/{bot_id}/disable")
async def disable_bot(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    await svc_disable_bot(db, bot)
    return {"status": "disabled"}


@router.delete("/bots/{bot_id}")
async def delete_bot(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    await svc_delete_bot(db, bot, MEDIA_DIR)
    return {"status": "deleted"}
