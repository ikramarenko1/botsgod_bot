import os
import json
import logging
import time
import asyncio
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, insert as sa_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.db.session import AsyncSessionLocal, _ac_engine, _is_sqlite
from backend.models.bot import Bot, BotRole
from backend.models.bot_welcome import BotWelcome
from backend.models.delayed_message import DelayedMessage, DelayedStatus
from backend.models.user import BotUser
from backend.models.key import Key

logger = logging.getLogger("stagecontrol")

router = APIRouter()

DEFAULT_FARM_TEXT = "Здравствуйте! Спасибо за обращение."

_bot_cache = {}
_BOT_CACHE_TTL = 60

_farm_text_cache = {}
_FARM_TEXT_CACHE_TTL = 120

_welcome_cache = {}
_WELCOME_CACHE_TTL = 60

_http_client = None

_db_semaphore = asyncio.Semaphore(15)


_send_semaphore = asyncio.Semaphore(30)

_MAX_RETRIES = 2
_RETRY_DELAYS = (0.5, 1.5)


def _get_http_client():
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=20,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _http_client


async def _tg_request(client, bot_token, method, retries=_MAX_RETRIES, **kwargs):
    """Отправка запроса в Telegram API с retry и семафором."""
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    async with _send_semaphore:
        for attempt in range(1 + retries):
            try:
                resp = await client.post(url, **kwargs)
                if resp.status_code == 429:
                    retry_after = float(resp.json().get("parameters", {}).get("retry_after", 1))
                    logger.warning(f"Telegram 429, retry_after={retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue
                if resp.status_code >= 500 and attempt < retries:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
                    continue
                if resp.status_code != 200:
                    logger.error(f"Telegram {method} failed ({resp.status_code}): {resp.text}")
                return resp
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < retries:
                    logger.warning(f"Telegram {method} attempt {attempt+1} failed: {e}")
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
                    continue
                logger.error(f"Telegram {method} failed after {retries+1} attempts: {e}")
                return None
            except Exception as e:
                logger.error(f"Telegram {method} unexpected error: {e}")
                return None
    return None


async def _get_bot_cached(bot_id):
    now = time.monotonic()
    cached = _bot_cache.get(bot_id)
    if cached and cached[0] > now:
        return cached[1]

    async with _db_semaphore:
        cached = _bot_cache.get(bot_id)
        if cached and cached[0] > now:
            return cached[1]

        async with _ac_engine.connect() as conn:
            result = await conn.execute(
                select(
                    Bot.id, Bot.token, Bot.role, Bot.key_id,
                    Bot.delayed_text, Bot.delayed_buttons, Bot.delayed_delay_minutes,
                    Bot.auto_reply_text,
                ).where(Bot.id == bot_id)
            )
            row = result.one_or_none()
            if not row:
                return None

            data = {
                "id": row.id,
                "token": row.token,
                "role": row.role,
                "key_id": row.key_id,
                "delayed_text": row.delayed_text,
                "delayed_buttons": row.delayed_buttons,
                "delayed_delay_minutes": row.delayed_delay_minutes,
                "auto_reply_text": row.auto_reply_text,
            }
    _bot_cache[bot_id] = (now + _BOT_CACHE_TTL, data)
    return data


async def _get_farm_text_cached(key_id):
    now = time.monotonic()
    cached = _farm_text_cache.get(key_id)
    if cached and cached[0] > now:
        return cached[1]

    async with _db_semaphore:
        cached = _farm_text_cache.get(key_id)
        if cached and cached[0] > now:
            return cached[1]

        async with _ac_engine.connect() as conn:
            result = await conn.execute(select(Key.farm_text).where(Key.id == key_id))
            row = result.one_or_none()
            farm_text = row.farm_text if row and row.farm_text else DEFAULT_FARM_TEXT
    _farm_text_cache[key_id] = (now + _FARM_TEXT_CACHE_TTL, farm_text)
    return farm_text


async def _get_welcome_cached(bot_id):
    now = time.monotonic()
    cached = _welcome_cache.get(bot_id)
    if cached and cached[0] > now:
        return cached[1]

    async with _db_semaphore:
        cached = _welcome_cache.get(bot_id)
        if cached and cached[0] > now:
            return cached[1]

        async with _ac_engine.connect() as conn:
            result = await conn.execute(
                select(
                    BotWelcome.text, BotWelcome.photo_path, BotWelcome.buttons,
                ).where(
                    BotWelcome.bot_id == bot_id,
                    BotWelcome.is_enabled == True,
                )
            )
            welcome = result.one_or_none()

    if not welcome:
        _welcome_cache[bot_id] = (now + _WELCOME_CACHE_TTL, None)
        return None

    data = {
        "text": welcome.text,
        "photo_path": welcome.photo_path,
        "buttons": welcome.buttons,
    }
    _welcome_cache[bot_id] = (now + _WELCOME_CACHE_TTL, data)
    return data


def invalidate_bot_cache(bot_id=None):
    """Сброс кэша бота. Без аргументов — сброс всего."""
    if bot_id is None:
        _bot_cache.clear()
    else:
        _bot_cache.pop(bot_id, None)


def invalidate_welcome_cache(bot_id=None):
    """Сброс кэша welcome. Без аргументов — сброс всего."""
    if bot_id is None:
        _welcome_cache.clear()
    else:
        _welcome_cache.pop(bot_id, None)


def invalidate_farm_text_cache(key_id=None):
    """Сброс кэша farm_text. Без аргументов — сброс всего."""
    if key_id is None:
        _farm_text_cache.clear()
    else:
        _farm_text_cache.pop(key_id, None)


@router.post("/webhooks/{bot_id}")
async def telegram_webhook(
    bot_id: int,
    update: dict,
):
    callback_query = update.get("callback_query")
    message = update.get("message") or (callback_query or {}).get("message")

    if not message:
        return {"status": "ignored"}

    if callback_query:
        user_data = callback_query.get("from")
    else:
        user_data = message.get("from")

    if not user_data:
        return {"status": "no_user"}

    telegram_id = user_data["id"]
    text = message.get("text", "")
    is_start = text.startswith("/start")
    now = datetime.utcnow()

    bot_data = await _get_bot_cached(bot_id)
    if not bot_data or bot_data["role"] == BotRole.disabled:
        raise HTTPException(status_code=404, detail="Bot not found or disabled")

    user_id = None
    if _is_sqlite:
        async with AsyncSessionLocal() as db:
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
                    created_at=now,
                    last_seen_at=now,
                )
                db.add(user)
                await db.flush()
            else:
                user.last_seen_at = now
                user.is_premium = user_data.get("is_premium")
                user.language_code = user_data.get("language_code")
            user_id = user.id
            await db.commit()
    else:
        stmt = pg_insert(BotUser).values(
            bot_id=bot_id,
            telegram_id=telegram_id,
            username=user_data.get("username"),
            first_name=user_data.get("first_name"),
            last_name=user_data.get("last_name"),
            is_premium=user_data.get("is_premium"),
            language_code=user_data.get("language_code"),
            created_at=now,
            last_seen_at=now,
        ).on_conflict_do_update(
            index_elements=["bot_id", "telegram_id"],
            set_={
                "last_seen_at": now,
                "is_premium": user_data.get("is_premium"),
                "language_code": user_data.get("language_code"),
            },
        ).returning(BotUser.id)
        async with _db_semaphore:
            async with _ac_engine.connect() as conn:
                result = await conn.execute(stmt)
                user_id = result.scalar_one()

    farm_text = DEFAULT_FARM_TEXT
    if bot_data["role"] == BotRole.farm and bot_data["key_id"]:
        farm_text = await _get_farm_text_cached(bot_data["key_id"])

    welcome_data = None
    if is_start and bot_data["role"] != BotRole.farm:
        welcome_data = await _get_welcome_cached(bot_id)

        if bot_data["delayed_text"] and bot_data["delayed_delay_minutes"] is not None:
            send_at = now + timedelta(minutes=bot_data["delayed_delay_minutes"])
            async with _db_semaphore:
                async with _ac_engine.connect() as conn:
                    await conn.execute(
                        sa_insert(DelayedMessage).values(
                            bot_id=bot_id,
                            user_id=user_id,
                            text=bot_data["delayed_text"],
                            buttons=bot_data["delayed_buttons"],
                            send_at=send_at,
                            status=DelayedStatus.pending,
                        )
                    )
                    if _is_sqlite:
                        await conn.commit()

    bot_token = bot_data["token"]
    client = _get_http_client()

    if bot_data["role"] == BotRole.farm:
        asyncio.create_task(
            _send_farm_reply(client, bot_token, telegram_id, farm_text)
        )
        return {"status": "farm_reply"}

    if welcome_data:
        asyncio.create_task(
            _send_welcome(client, bot_token, telegram_id, welcome_data)
        )

    auto_reply = bot_data.get("auto_reply_text")
    if auto_reply:
        asyncio.create_task(
            _send_auto_reply(client, bot_token, telegram_id, auto_reply)
        )

    return {"status": "ok"}


async def _send_farm_reply(client, bot_token, telegram_id, farm_text):
    """Фоновая отправка farm-ответа."""
    await _tg_request(
        client, bot_token, "sendMessage",
        json={"chat_id": telegram_id, "text": farm_text, "parse_mode": "HTML"},
    )


async def _send_auto_reply(client, bot_token, telegram_id, text):
    """Фоновая отправка авто-ответа."""
    await _tg_request(
        client, bot_token, "sendMessage",
        json={"chat_id": telegram_id, "text": text, "parse_mode": "HTML"},
    )


async def _send_welcome(client, bot_token, telegram_id, welcome_data):
    """Фоновая отправка welcome-сообщения."""
    try:
        reply_markup = None
        if welcome_data["buttons"] and isinstance(welcome_data["buttons"], list):
            reply_markup = {
                "inline_keyboard": [
                    [{"text": b["text"], "url": b["url"]}]
                    for b in welcome_data["buttons"]
                ]
            }

        if welcome_data["photo_path"] and os.path.exists(welcome_data["photo_path"]):
            with open(welcome_data["photo_path"], "rb") as photo_file:
                photo_bytes = photo_file.read()

            data_payload = {
                "chat_id": telegram_id,
                "caption": welcome_data["text"] or "",
                "parse_mode": "HTML",
            }
            if reply_markup:
                data_payload["reply_markup"] = json.dumps(reply_markup)

            await _tg_request(
                client, bot_token, "sendPhoto",
                data=data_payload,
                files={"photo": ("photo", photo_bytes)},
            )

        elif welcome_data["text"]:
            payload = {
                "chat_id": telegram_id,
                "text": welcome_data["text"],
                "parse_mode": "HTML",
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup

            await _tg_request(
                client, bot_token, "sendMessage",
                json=payload,
            )
    except Exception as e:
        logger.error(f"Welcome send failed: {e}")
