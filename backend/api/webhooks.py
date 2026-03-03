import os
import json
import logging
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.db.session import get_db
from backend.models.bot import Bot, BotRole
from backend.models.bot_welcome import BotWelcome
from backend.models.delayed_message import DelayedMessage, DelayedStatus
from backend.models.user import BotUser

logger = logging.getLogger("stagecontrol")

router = APIRouter()


@router.post("/webhooks/{bot_id}")
async def telegram_webhook(
    bot_id: int,
    update: dict,
    db: AsyncSession = Depends(get_db),
):
    message = update.get("message") or update.get("callback_query", {}).get("message")

    if not message:
        return {"status": "ignored"}

    user_data = message.get("from")
    if not user_data:
        return {"status": "no_user"}

    telegram_id = user_data["id"]

    bot = await db.get(Bot, bot_id)
    if not bot or bot.role == BotRole.disabled:
        raise HTTPException(status_code=404, detail="Bot not found or disabled")

    result = await db.execute(
        select(BotUser).where(
            BotUser.bot_id == bot_id,
            BotUser.telegram_id == telegram_id,
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        user = BotUser(
            bot_id=bot_id,
            telegram_id=telegram_id,
            username=user_data.get("username"),
            first_name=user_data.get("first_name"),
            last_name=user_data.get("last_name"),
            is_premium=user_data.get("is_premium"),
            language_code=user_data.get("language_code"),
            created_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
        db.add(user)
    else:
        user.last_seen_at = datetime.utcnow()
        user.is_premium = user_data.get("is_premium")
        user.language_code = user_data.get("language_code")

    await db.commit()

    text = message.get("text", "")
    if text.startswith("/start"):
        result = await db.execute(
            select(BotWelcome).where(
                BotWelcome.bot_id == bot_id,
                BotWelcome.is_enabled == True,
            )
        )
        welcome = result.scalar_one_or_none()

        if welcome:
            reply_markup = None
            if welcome.buttons and isinstance(welcome.buttons, list):
                reply_markup = {
                    "inline_keyboard": [
                        [{"text": b["text"], "url": b["url"]}]
                        for b in welcome.buttons
                    ]
                }

            async with httpx.AsyncClient() as client:

                if welcome.photo_path and os.path.exists(welcome.photo_path):
                    with open(welcome.photo_path, "rb") as photo_file:
                        data_payload = {
                            "chat_id": telegram_id,
                            "caption": welcome.text or "",
                        }

                        if reply_markup:
                            data_payload["reply_markup"] = json.dumps(reply_markup)

                        response = await client.post(
                            f"https://api.telegram.org/bot{bot.token}/sendPhoto",
                            data=data_payload,
                            files={
                                "photo": photo_file
                            }
                        )

                        if response.status_code != 200:
                            logger.error(f"sendPhoto failed: {response.text}")

                elif welcome.text:
                    payload = {
                        "chat_id": telegram_id,
                        "text": welcome.text,
                    }

                    if reply_markup:
                        payload["reply_markup"] = reply_markup

                    response = await client.post(
                        f"https://api.telegram.org/bot{bot.token}/sendMessage",
                        json=payload,
                    )

                    if response.status_code != 200:
                        logger.error(f"sendMessage failed: {response.text}")

        if bot.delayed_text and bot.delayed_delay_minutes is not None:
            send_at = datetime.utcnow() + timedelta(minutes=bot.delayed_delay_minutes)

            delayed_msg = DelayedMessage(
                bot_id=bot_id,
                user_id=user.id,
                text=bot.delayed_text,
                buttons=bot.delayed_buttons,
                send_at=send_at,
                status=DelayedStatus.pending,
            )

            db.add(delayed_msg)
            await db.commit()

    return {"status": "ok"}
