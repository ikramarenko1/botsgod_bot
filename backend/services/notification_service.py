import os
import logging

import httpx

logger = logging.getLogger("stagecontrol")

NOTIFY_BOT_TOKEN = os.getenv("NOTIFY_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
CONTROLLER_BOT_TOKEN = os.getenv("CONTROLLER_BOT_TOKEN")

CONTROLLER_ALLOWED_USERS = os.getenv("CONTROLLER_ALLOWED_USERS", "")
CONTROLLER_ALLOWED_USERS = [
    int(x.strip()) for x in CONTROLLER_ALLOWED_USERS.split(",") if x.strip()
]


async def notify_admin(text: str):
    if not NOTIFY_BOT_TOKEN:
        return

    async with httpx.AsyncClient(timeout=10) as client:

        if ADMIN_CHAT_ID:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{NOTIFY_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": int(ADMIN_CHAT_ID),
                        "text": text,
                    },
                )
            except Exception as e:
                logger.error(f"Failed to notify admin group: {e}")

        for user_id in CONTROLLER_ALLOWED_USERS:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{NOTIFY_BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": user_id,
                        "text": text,
                    },
                )
            except Exception as e:
                logger.error(f"Failed to notify admins: {e}")


async def notify_owner(owner_id: int, text: str, reply_markup: dict = None):
    if not CONTROLLER_BOT_TOKEN:
        return

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            payload = {
                "chat_id": owner_id,
                "text": text,
                "parse_mode": "HTML",
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            await client.post(
                f"https://api.telegram.org/bot{CONTROLLER_BOT_TOKEN}/sendMessage",
                json=payload,
            )
        except Exception as e:
            logger.error(f"Failed to notify owner {owner_id}: {e}")