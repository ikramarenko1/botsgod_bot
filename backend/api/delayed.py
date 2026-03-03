import os
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.db.session import get_db
from backend.models.bot import Bot
from backend.models.delayed_message import DelayedMessage, DelayedStatus
from backend.schemas.delayed_message import DelayedConfigRequest
from backend.utils.auth import verify_api_key, get_owned_bot
from backend.services.delayed_service import get_pending_delayed

logger = logging.getLogger("stagecontrol")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
MEDIA_DIR = os.path.join(PROJECT_ROOT, "media")

router = APIRouter()


@router.get("/bots/{bot_id}/delayed/photo")
async def get_delayed_photo(
    bot: Bot = Depends(get_owned_bot),
):
    if not bot.delayed_photo_path:
        raise HTTPException(404, "Photo not set")

    if not os.path.exists(bot.delayed_photo_path):
        raise HTTPException(404, "File missing")

    return FileResponse(bot.delayed_photo_path)


@router.get("/bots/{bot_id}/delayed")
async def get_delayed_config(
    bot: Bot = Depends(get_owned_bot),
):
    return {
        "text": bot.delayed_text,
        "buttons": bot.delayed_buttons,
        "delay_minutes": bot.delayed_delay_minutes,
        "photo_path": bot.delayed_photo_path,
    }


@router.get("/delayed/pending")
async def get_pending_delayed_endpoint(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    return await get_pending_delayed(db)


@router.post("/bots/{bot_id}/delayed")
async def set_delayed_message(
    data: DelayedConfigRequest,
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
):
    bot.delayed_text = data.text
    bot.delayed_buttons = data.buttons
    bot.delayed_delay_minutes = data.delay_minutes

    await db.commit()

    return {"status": "configured"}


@router.post("/bots/{bot_id}/delayed/photo")
async def upload_delayed_photo(
    bot: Bot = Depends(get_owned_bot),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "Only images allowed")

    content = await file.read()

    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "File too large")

    bot_dir = os.path.join(MEDIA_DIR, f"bot_{bot.id}")
    os.makedirs(bot_dir, exist_ok=True)

    extension = file.content_type.split("/")[-1]
    file_path = os.path.join(bot_dir, f"delayed.{extension}")

    if os.path.exists(file_path):
        os.remove(file_path)

    with open(file_path, "wb") as f:
        f.write(content)

    bot.delayed_photo_path = file_path
    await db.commit()

    return {"status": "uploaded"}


@router.patch("/delayed/{msg_id}/sent")
async def mark_delayed_sent(
    msg_id: int,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    result = await db.execute(
        select(DelayedMessage).where(DelayedMessage.id == msg_id)
    )
    msg = result.scalar_one_or_none()

    if not msg:
        raise HTTPException(404, "Delayed message not found")

    msg.status = DelayedStatus.sent
    await db.commit()

    return {"status": "ok"}
