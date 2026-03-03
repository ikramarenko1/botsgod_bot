import os
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.db.session import get_db
from backend.models.bot import Bot
from backend.models.bot_welcome import BotWelcome
from backend.schemas.bot_welcome import WelcomeCreateRequest, WelcomeResponse
from backend.utils.auth import get_owned_bot

logger = logging.getLogger("stagecontrol")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
MEDIA_DIR = os.path.join(PROJECT_ROOT, "media")

router = APIRouter()


@router.get("/bots/{bot_id}/welcome", response_model=WelcomeResponse)
async def get_welcome(bot: Bot = Depends(get_owned_bot), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(BotWelcome).where(BotWelcome.bot_id == bot.id)
    )
    welcome = result.scalar_one_or_none()

    if not welcome:
        raise HTTPException(404, "Welcome message not set")

    return welcome


@router.get("/bots/{bot_id}/welcome/photo")
async def get_welcome_photo(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BotWelcome).where(BotWelcome.bot_id == bot.id)
    )
    welcome = result.scalar_one_or_none()

    if not welcome or not welcome.photo_path:
        raise HTTPException(404, "Photo not found")

    if not os.path.exists(welcome.photo_path):
        raise HTTPException(404, "File missing")

    return FileResponse(welcome.photo_path)


@router.post("/bots/{bot_id}/welcome", response_model=WelcomeResponse)
async def upsert_welcome(
    data: WelcomeCreateRequest,
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BotWelcome).where(BotWelcome.bot_id == bot.id)
    )
    welcome = result.scalar_one_or_none()

    if welcome and welcome.photo_path and data.photo_path is None:
        if os.path.exists(welcome.photo_path):
            try:
                os.remove(welcome.photo_path)
            except Exception as e:
                logger.error(f"Failed to delete old welcome photo: {e}")

    if welcome:
        welcome.text = data.text
        welcome.photo_path = data.photo_path
        welcome.buttons = data.buttons
        welcome.is_enabled = data.is_enabled
    else:
        welcome = BotWelcome(
            bot_id=bot.id,
            text=data.text,
            photo_path=data.photo_path,
            buttons=data.buttons,
            is_enabled=data.is_enabled,
        )
        db.add(welcome)

    await db.commit()
    await db.refresh(welcome)

    return welcome


@router.post("/bots/{bot_id}/welcome/photo")
async def upload_welcome_photo(
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
    file_path = os.path.join(bot_dir, f"welcome.{extension}")

    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            logger.error(f"Failed to delete old welcome photo: {e}")

    with open(file_path, "wb") as f:
        f.write(content)

    result = await db.execute(
        select(BotWelcome).where(BotWelcome.bot_id == bot.id)
    )
    welcome = result.scalar_one_or_none()

    if not welcome:
        welcome = BotWelcome(
            bot_id=bot.id,
            text=None,
            photo_path=file_path,
            buttons=None,
            is_enabled=True
        )
        db.add(welcome)
    else:
        welcome.photo_path = file_path
        welcome.is_enabled = True

    await db.commit()

    return {"status": "uploaded"}
