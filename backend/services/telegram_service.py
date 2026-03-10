import os
import json
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.bot import Bot
from backend.models.bot_config import BotConfig

logger = logging.getLogger("stagecontrol")

PUBLIC_WEBHOOK_BASE = os.getenv("PUBLIC_WEBHOOK_BASE")


async def set_webhook(bot: Bot):
    if not PUBLIC_WEBHOOK_BASE:
        return

    url = f"{PUBLIC_WEBHOOK_BASE}/webhooks/{bot.id}"

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot.token}/setWebhook",
            json={"url": url},
        )

    if resp.status_code != 200:
        logger.error(f"setWebhook HTTP error for @{bot.username}: {resp.status_code} {resp.text}")
        return

    data = resp.json()
    if not data.get("ok"):
        logger.error(f"setWebhook failed for @{bot.username}: {data}")
        return

    logger.debug(f"Webhook set for @{bot.username}")


async def apply_last_config(db: AsyncSession, bot: Bot, region: str):
    result = await db.execute(
        select(BotConfig).where(
            BotConfig.bot_id == bot.id,
            BotConfig.region == region,
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        return

    payload_name = {"name": config.name}
    payload_desc = {"description": config.description}

    if region != "default":
        payload_name["language_code"] = region
        payload_desc["language_code"] = region

    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"https://api.telegram.org/bot{bot.token}/setMyName",
            json=payload_name,
        )

        await client.post(
            f"https://api.telegram.org/bot{bot.token}/setMyDescription",
            json=payload_desc,
        )

    logger.debug(
        f"Config applied to @{bot.username} (region={region})"
    )


async def apply_avatar(bot: Bot):
    if not bot.avatar_path:
        return

    if not os.path.exists(bot.avatar_path):
        logger.warning(f"Avatar file missing for @{bot.username}")
        return

    with open(bot.avatar_path, "rb") as f:
        raw = f.read()

    payload = {
        "type": "static",
        "photo": "attach://file"
    }

    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(
            f"https://api.telegram.org/bot{bot.token}/setMyProfilePhoto",
            data={"photo": json.dumps(payload)},
            files={"file": ("avatar.jpg", raw, "image/jpeg")},
        )

    logger.debug(f"Avatar applied to @{bot.username}")
