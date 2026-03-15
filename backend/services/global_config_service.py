import os
import shutil
import logging
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.bot import Bot, BotRole, DEFAULT_AUTO_REPLY
from backend.models.bot_config import BotConfig
from backend.models.bot_welcome import BotWelcome
from backend.models.global_config import GlobalConfig, GlobalConfigRegion
from backend.models.key import Key

logger = logging.getLogger("stagecontrol")


async def apply_global_config_to_bot(
    db: AsyncSession,
    bot: Bot,
    config: GlobalConfig,
    media_dir: str,
    force: bool = False,
) -> dict:
    """Применить глобальный конфиг к одному боту. Возвращает {"skipped": [...], "api_errors": [...]}."""
    skipped = []
    api_errors = []

    # Avatar
    if config.avatar_path and os.path.exists(config.avatar_path):
        if bot.avatar_path and not force:
            skipped.append("аватар")
        else:
            bot_dir = os.path.join(media_dir, f"bot_{bot.id}")
            os.makedirs(bot_dir, exist_ok=True)
            dest = os.path.join(bot_dir, "avatar.jpg")
            shutil.copy2(config.avatar_path, dest)
            bot.avatar_path = dest

            try:
                import json
                with open(dest, "rb") as f:
                    jpg_bytes = f.read()
                payload = {"type": "static", "photo": "attach://file"}
                async with httpx.AsyncClient(timeout=20) as client:
                    await client.post(
                        f"https://api.telegram.org/bot{bot.token}/setMyProfilePhoto",
                        data={"photo": json.dumps(payload)},
                        files={"file": ("avatar.jpg", jpg_bytes, "image/jpeg")},
                    )
            except Exception as e:
                logger.error(f"Global config: avatar apply failed for @{bot.username}: {e}")

    # Welcome
    if config.welcome_text:
        result = await db.execute(
            select(BotWelcome).where(BotWelcome.bot_id == bot.id)
        )
        existing_welcome = result.scalar_one_or_none()

        if existing_welcome and existing_welcome.is_enabled and not force:
            skipped.append("приветствие")
        else:
            if existing_welcome:
                existing_welcome.text = config.welcome_text
                existing_welcome.buttons = config.welcome_buttons
                existing_welcome.is_enabled = True
                if config.welcome_photo_path and os.path.exists(config.welcome_photo_path):
                    bot_dir = os.path.join(media_dir, f"bot_{bot.id}")
                    os.makedirs(bot_dir, exist_ok=True)
                    ext = os.path.splitext(config.welcome_photo_path)[1]
                    dest = os.path.join(bot_dir, f"welcome{ext}")
                    shutil.copy2(config.welcome_photo_path, dest)
                    existing_welcome.photo_path = dest
            else:
                welcome = BotWelcome(
                    bot_id=bot.id,
                    text=config.welcome_text,
                    buttons=config.welcome_buttons,
                    is_enabled=True,
                )
                if config.welcome_photo_path and os.path.exists(config.welcome_photo_path):
                    bot_dir = os.path.join(media_dir, f"bot_{bot.id}")
                    os.makedirs(bot_dir, exist_ok=True)
                    ext = os.path.splitext(config.welcome_photo_path)[1]
                    dest = os.path.join(bot_dir, f"welcome{ext}")
                    shutil.copy2(config.welcome_photo_path, dest)
                    welcome.photo_path = dest
                db.add(welcome)

    # Auto-reply
    if config.auto_reply_text:
        if bot.auto_reply_text and bot.auto_reply_text != DEFAULT_AUTO_REPLY and not force:
            skipped.append("авто-ответ")
        else:
            bot.auto_reply_text = config.auto_reply_text

    # Region configs
    regions = await db.execute(
        select(GlobalConfigRegion).where(
            GlobalConfigRegion.global_config_id == config.id
        )
    )
    gc_regions = regions.scalars().all()

    skipped_regions = []
    for gc_region in gc_regions:
        existing_result = await db.execute(
            select(BotConfig).where(
                BotConfig.bot_id == bot.id,
                BotConfig.region == gc_region.region,
            )
        )
        existing_config = existing_result.scalar_one_or_none()
        if existing_config and not force:
            skipped_regions.append(gc_region.region)
        else:
            if existing_config:
                existing_config.name = gc_region.name
                existing_config.description = gc_region.description
            else:
                new_config = BotConfig(
                    bot_id=bot.id,
                    region=gc_region.region,
                    name=gc_region.name,
                    description=gc_region.description,
                )
                db.add(new_config)

            try:
                payload_name = {"name": gc_region.name}
                payload_desc = {"short_description": gc_region.description or ""}
                if gc_region.region != "default":
                    payload_name["language_code"] = gc_region.region
                    payload_desc["language_code"] = gc_region.region
                async with httpx.AsyncClient(timeout=10) as client:
                    resp_name = await client.post(
                        f"https://api.telegram.org/bot{bot.token}/setMyName",
                        json=payload_name,
                    )
                    if resp_name.status_code != 200 or not resp_name.json().get("ok"):
                        err = resp_name.json().get("description", "unknown error")
                        logger.warning(f"Global config: setMyName failed for @{bot.username} region {gc_region.region}: {err}")
                        api_errors.append(f"setMyName {gc_region.region}: {err}")

                    resp_desc = await client.post(
                        f"https://api.telegram.org/bot{bot.token}/setMyShortDescription",
                        json=payload_desc,
                    )
                    if resp_desc.status_code != 200 or not resp_desc.json().get("ok"):
                        err = resp_desc.json().get("description", "unknown error")
                        logger.warning(f"Global config: setMyShortDescription failed for @{bot.username} region {gc_region.region}: {err}")
                        api_errors.append(f"setMyShortDescription {gc_region.region}: {err}")
            except Exception as e:
                logger.error(f"Global config: region {gc_region.region} apply failed for @{bot.username}: {e}")

    if skipped_regions:
        skipped.append(f"регионы ({', '.join(skipped_regions)})")

    return {"skipped": skipped, "api_errors": api_errors}


async def apply_global_config_to_all_active(
    db: AsyncSession,
    config: GlobalConfig,
    team_id: int,
    media_dir: str,
    force: bool = False,
) -> dict:
    """Применить глобальный конфиг ко всем активным ботам команды."""
    result = await db.execute(
        select(Bot).where(
            Bot.team_id == team_id,
            Bot.role == BotRole.active,
        )
    )
    bots = result.scalars().all()

    # Предзагрузить ключи команды
    keys_result = await db.execute(select(Key).where(Key.team_id == team_id))
    keys_map = {k.id: k.short_name for k in keys_result.scalars().all()}

    applied = 0
    skipped_bots = {}
    applied_bots = []
    all_api_errors = {}

    for bot in bots:
        try:
            result = await apply_global_config_to_bot(db, bot, config, media_dir, force=force)
            skipped = result["skipped"]
            bot_api_errors = result["api_errors"]
            if skipped:
                skipped_bots[bot.username] = skipped
            if bot_api_errors:
                all_api_errors[bot.username] = bot_api_errors
            applied += 1
            applied_bots.append({
                "username": bot.username,
                "role": bot.role.value if bot.role else "active",
                "key_name": keys_map.get(bot.key_id) if bot.key_id else None,
            })
        except Exception as e:
            logger.error(f"Global config apply failed for @{bot.username}: {e}")
            skipped_bots[bot.username] = ["ошибка применения"]

    await db.commit()

    return {
        "applied": applied,
        "skipped_bots": skipped_bots,
        "applied_bots": applied_bots,
        "api_errors": all_api_errors,
    }


async def get_active_global_config(db: AsyncSession, team_id: int) -> Optional[GlobalConfig]:
    """Получить активный глобальный конфиг команды."""
    result = await db.execute(
        select(GlobalConfig).where(
            GlobalConfig.team_id == team_id,
            GlobalConfig.is_active == True,
        )
    )
    return result.scalar_one_or_none()
