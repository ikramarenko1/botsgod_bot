import os
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.bot import Bot, BotRole, BotStatus
from backend.models.bot_config import BotConfig
from backend.services.telegram_service import set_webhook

logger = logging.getLogger("stagecontrol")


async def add_bot(db: AsyncSession, token: str, owner_id: int, media_dir: str, role: str = "active", team_id: int = None) -> Bot:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=10,
        )

    if resp.status_code != 200:
        raise ValueError("Invalid bot token")

    payload = resp.json()
    if not payload.get("ok"):
        raise ValueError("Invalid bot token")

    tg_bot = payload["result"]
    username = tg_bot["username"]

    if role not in ("active", "reserve", "farm"):
        raise ValueError("Invalid role: must be 'active', 'reserve' or 'farm'")

    existing = await db.execute(select(Bot).where(Bot.username == username))
    if existing.scalar_one_or_none():
        raise ValueError("Bot already exists")

    bot = Bot(
        username=username,
        token=token,
        role=BotRole(role),
        status=BotStatus.alive,
        owner_telegram_id=owner_id,
        team_id=team_id,
    )

    db.add(bot)
    await db.commit()
    await db.refresh(bot)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            desc_resp = await client.get(
                f"https://api.telegram.org/bot{bot.token}/getMyDescription"
            )

            description = ""
            if desc_resp.status_code == 200 and desc_resp.json().get("ok"):
                description = desc_resp.json()["result"].get("description", "")

        default_config = BotConfig(
            bot_id=bot.id,
            region="default",
            name=username,
            description=description,
        )

        db.add(default_config)
        await db.commit()

    except Exception:
        pass

    if role in ("active", "farm"):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{bot.token}/deleteWebhook"
                )

                await set_webhook(bot)

        except Exception as e:
            logger.error(f"Failed to set webhook for @{bot.username}: {e}")

    logger.info(f"New bot added: @{bot.username}")
    return bot


async def health_check_bot(db: AsyncSession, bot: Bot) -> Bot:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{bot.token}/getMe"
            )

        if resp.status_code != 200 or not resp.json().get("ok"):
            bot.status = BotStatus.dead
        else:
            bot.status = BotStatus.alive

    except httpx.TimeoutException:
        bot.status = BotStatus.degraded

    await db.commit()
    await db.refresh(bot)
    return bot


async def health_check_all(db: AsyncSession) -> list[dict]:
    logger.info("Health-check started")

    result = await db.execute(
        select(Bot).where(Bot.role.in_([BotRole.active, BotRole.reserve]))
    )
    bots = result.scalars().all()

    checked = []
    counts = {"alive": 0, "dead": 0, "degraded": 0}

    for bot in bots:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{bot.token}/getMe"
                )

            if resp.status_code != 200 or not resp.json().get("ok"):
                bot.status = BotStatus.dead
            else:
                bot.status = BotStatus.alive

            logger.debug(
                f"Health-check: @{bot.username} -> {bot.status.value}"
            )

        except httpx.TimeoutException:
            bot.status = BotStatus.degraded
            logger.debug(
                f"Health-check: @{bot.username} -> {bot.status.value}"
            )

        counts[bot.status.value] = counts.get(bot.status.value, 0) + 1

        checked.append({
            "id": bot.id,
            "username": bot.username,
            "role": bot.role.value,
            "status": bot.status.value,
        })

    await db.commit()

    logger.info(
        f"Health-check: {counts['alive']} alive, {counts['dead']} dead, "
        f"{counts['degraded']} degraded ({len(bots)} total)"
    )

    return checked


async def enable_bot(db: AsyncSession, bot: Bot):
    bot.role = BotRole.active
    bot.status = BotStatus.alive
    await db.commit()
    await set_webhook(bot)


async def disable_bot(db: AsyncSession, bot: Bot):
    bot.role = BotRole.disabled
    bot.status = BotStatus.dead
    await db.commit()

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{bot.token}/deleteWebhook"
            )
    except Exception:
        pass


async def delete_bot(db: AsyncSession, bot: Bot, media_dir: str):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{bot.token}/deleteWebhook"
            )
    except Exception:
        pass

    bot_dir = os.path.join(media_dir, f"bot_{bot.id}")
    if os.path.exists(bot_dir):
        import shutil
        shutil.rmtree(bot_dir, ignore_errors=True)

    await db.delete(bot)
    await db.commit()

    logger.warning(f"Bot deleted: @{bot.username}")
