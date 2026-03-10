import os
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.db.session import get_db
from backend.models.bot import Bot, BotRole
from backend.models.user import BotUser
from backend.utils.auth import verify_api_key
from backend.services.replacement_service import run_replacement, get_replacement_logs_all
from backend.services.telegram_service import set_webhook

logger = logging.getLogger("stagecontrol")

CONTROLLER_BOT_TOKEN = os.getenv("CONTROLLER_BOT_TOKEN")
CONTROLLER_ALLOWED_USERS = os.getenv("CONTROLLER_ALLOWED_USERS", "")
CONTROLLER_ALLOWED_USERS = [
    int(x.strip()) for x in CONTROLLER_ALLOWED_USERS.split(",") if x.strip()
]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
MEDIA_DIR = os.path.join(PROJECT_ROOT, "media")

worker_status = {
    "last_heartbeat": None,
    "last_health_check": None,
    "last_replacement_run": None,
}

router = APIRouter()


@router.get("/system/bots/{bot_id}/users")
async def system_list_bot_users(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    result = await db.execute(
        select(BotUser).where(
            BotUser.bot_id == bot_id,
            BotUser.is_active == True,
        )
    )
    users = result.scalars().all()

    return [
        {
            "id": u.id,
            "telegram_id": u.telegram_id,
        }
        for u in users
    ]


@router.get("/system/bot-token/{bot_id}")
async def get_bot_token(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    bot = await db.get(Bot, bot_id)
    if not bot:
        raise HTTPException(404, "Bot not found")

    return {"token": bot.token}


@router.get("/system/worker-status")
async def get_worker_status(
    _: None = Depends(verify_api_key),
):
    last_hb = worker_status["last_heartbeat"]
    if last_hb and (datetime.utcnow() - last_hb).total_seconds() < 30:
        status = "online"
    else:
        status = "offline"

    return {
        "status": status,
        "last_heartbeat": last_hb.isoformat() if last_hb else None,
        "last_health_check": worker_status["last_health_check"].isoformat() if worker_status["last_health_check"] else None,
        "last_replacement_run": worker_status["last_replacement_run"].isoformat() if worker_status["last_replacement_run"] else None,
    }


@router.post("/system/worker-heartbeat")
async def worker_heartbeat_endpoint(
    data: dict,
    _: None = Depends(verify_api_key),
):
    worker_status["last_heartbeat"] = datetime.utcnow()

    if data.get("last_health_check"):
        worker_status["last_health_check"] = datetime.utcnow()
    if data.get("last_replacement_run"):
        worker_status["last_replacement_run"] = datetime.utcnow()

    return {"status": "ok"}


@router.get("/replacement/logs")
async def get_replacement_logs(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    return await get_replacement_logs_all(db)


@router.post("/bots/replacement")
async def replacement(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    return await run_replacement(db, MEDIA_DIR)


@router.post("/system/sync-webhooks")
async def sync_webhooks(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    result = await db.execute(
        select(Bot).where(Bot.role.in_([BotRole.active, BotRole.farm]))
    )
    bots = result.scalars().all()

    synced = 0
    errors = 0

    for bot in bots:
        try:
            await set_webhook(bot)
            synced += 1
        except Exception as e:
            logger.error(f"sync-webhooks: failed for @{bot.username}: {e}")
            errors += 1

    return {"synced": synced, "errors": errors, "total": len(bots)}


@router.post("/controller/webhook")
async def controller_webhook(update: dict):
    if not CONTROLLER_BOT_TOKEN:
        return {"status": "misconfigured"}

    message = update.get("message")
    if not message:
        return {"status": "ignored"}

    user = message.get("from")
    if not user:
        return {"status": "no_user"}

    telegram_id = user["id"]

    if telegram_id not in CONTROLLER_ALLOWED_USERS:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{CONTROLLER_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": telegram_id,
                    "text": "⛔ Доступ к StageControl запрещен.",
                },
            )

        logger.warning(f"Unauthorized controller access attempt: {telegram_id}")
        return {"status": "forbidden"}

    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"https://api.telegram.org/bot{CONTROLLER_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": telegram_id,
                "text": "✅ Добро пожаловать в StageControl",
            },
        )

    logger.info(f"Controller login: {telegram_id}")
    return {"status": "ok"}
