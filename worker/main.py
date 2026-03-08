import asyncio
import json

import httpx
import os
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()


INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
BACKEND_URL = os.getenv("BACKEND_URL")
LOG_FILE = os.getenv("WORKER_LOG_FILE")
CONTROLLER_BOT_TOKEN = os.getenv("CONTROLLER_BOT_TOKEN")

HEADERS = {"X-API-KEY": INTERNAL_API_KEY}

logger = logging.getLogger("stagecontrol_worker")
logger.setLevel(logging.INFO)

if LOG_FILE:
    handler = RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=3)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
else:
    logging.basicConfig(level=logging.INFO)

HEALTHCHECK_INTERVAL_SEC = 60
REPLACEMENT_INTERVAL_SEC = 120
WORKER_LOOP_DELAY = 10


async def notify_owner(owner_id: int, text: str):
    if not CONTROLLER_BOT_TOKEN:
        return

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{CONTROLLER_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": owner_id,
                    "text": text,
                    "parse_mode": "HTML"
                },
                timeout=10,
            )
    except Exception as e:
        logger.error(f"[worker] notify error: {e}")


def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def build_reply_markup(buttons):
    if not buttons:
        return None

    keyboard = []

    for b in buttons:
        if not is_valid_url(b["url"]):
            logger.warning(f"[worker] invalid URL skipped: {b['url']}")
            continue

        keyboard.append([{
            "text": b["text"],
            "url": b["url"]
        }])

    if not keyboard:
        return None

    return {"inline_keyboard": keyboard}


async def call_healthcheck_all(client: httpx.AsyncClient):
    try:
        r = await client.post(
            f"{BACKEND_URL}/bots/health-check/all",
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        logger.info("[worker] health-check done")
    except Exception as e:
        logger.error(f"[worker] health-check error: {e}")


async def call_replacement(client: httpx.AsyncClient):
    try:
        r = await client.post(
            f"{BACKEND_URL}/bots/replacement",
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        logger.info("[worker] replacement checked")
    except Exception as e:
        logger.error(f"[worker] replacement error: {e}")


async def process_broadcast(client: httpx.AsyncClient, broadcast: dict):
    broadcast_id = broadcast["id"]

    try:
        r = await client.patch(
            f"{BACKEND_URL}/broadcasts/{broadcast_id}/status",
            json={"status": "sending"},
            headers=HEADERS,
        )
        r.raise_for_status()
    except Exception:
        logger.info(f"[worker] broadcast {broadcast_id} already locked")
        return

    notify_ids = broadcast.get("notify_ids") or [broadcast["owner_id"]]
    for nid in notify_ids:
        await notify_owner(nid, f"🚀 <b>Рассылка #{broadcast_id} началась</b>")

    await client.patch(
        f"{BACKEND_URL}/broadcasts/{broadcast_id}/stats",
        json={"started_at": True},
        headers=HEADERS,
    )

    # Определяем список bot_id для рассылки
    target_bot_ids = broadcast.get("bot_ids") or [broadcast["bot_id"]]

    total = 0
    sent = 0
    failed = 0

    reply_markup = build_reply_markup(broadcast.get("buttons"))

    for target_bot_id in target_bot_ids:
        # Получаем токен и пользователей для каждого бота
        try:
            bot_resp = await client.get(
                f"{BACKEND_URL}/system/bots/{target_bot_id}/users",
                headers=HEADERS,
            )
            bot_resp.raise_for_status()
            users = bot_resp.json()
        except Exception as e:
            logger.error(f"[worker] broadcast {broadcast_id}: failed to get users for bot {target_bot_id}: {e}")
            continue

        # Получаем токен бота
        try:
            token_resp = await client.get(
                f"{BACKEND_URL}/system/bot-token/{target_bot_id}",
                headers=HEADERS,
            )
            token_resp.raise_for_status()
            bot_token = token_resp.json().get("token", broadcast["token"])
        except Exception:
            bot_token = broadcast["token"]

        total += len(users)

        for user in users:
            try:
                payload = {
                    "chat_id": user["telegram_id"],
                    "text": broadcast["text"],
                    "parse_mode": "HTML",
                }

                if reply_markup:
                    payload["reply_markup"] = reply_markup

                tg_resp = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json=payload,
                    timeout=10,
                )

                # Fallback для старых plain-text записей
                if tg_resp.status_code == 400:
                    payload.pop("parse_mode", None)
                    tg_resp = await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json=payload,
                        timeout=10,
                    )

                if tg_resp.status_code == 200:
                    sent += 1
                else:
                    failed += 1
                    logger.warning(
                        f"[worker] send error {tg_resp.status_code}: {tg_resp.text}"
                    )

                await asyncio.sleep(0.05)

            except Exception as e:
                failed += 1
                logger.error(f"[worker] send exception: {e}")

    await client.patch(
        f"{BACKEND_URL}/broadcasts/{broadcast_id}/stats",
        json={
            "total_users": total,
            "sent_count": sent,
            "failed_count": failed,
            "finished_at": True,
        },
        headers=HEADERS,
    )

    final_status = "sent" if sent > 0 else "failed"

    await client.patch(
        f"{BACKEND_URL}/broadcasts/{broadcast_id}/status",
        json={"status": final_status},
        headers=HEADERS,
    )

    finish_text = (
        f"<b>Рассылка #{broadcast_id} завершена</b>\n\n"
        f"👥 Всего: {total}\n"
        f"✅ Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n"
        f"📡 Статус: {final_status}"
    )
    for nid in notify_ids:
        await notify_owner(nid, finish_text)

    logger.info(
        f"[worker] broadcast {broadcast_id} finished. "
        f"Total: {total}, Sent: {sent}, Failed: {failed}"
    )


async def call_broadcast_worker(client: httpx.AsyncClient):
    try:
        r = await client.get(
            f"{BACKEND_URL}/broadcasts/scheduled",
            headers=HEADERS,
        )
        r.raise_for_status()
        broadcasts = r.json()

        for b in broadcasts:
            await process_broadcast(client, b)

    except Exception as e:
        logger.error(f"[worker] broadcast worker error: {e}")


async def process_delayed(client: httpx.AsyncClient, msg: dict, _retries: int = 0):
    try:
        reply_markup = None
        if msg.get("buttons"):
            reply_markup = {
                "inline_keyboard": [
                    [{"text": b["text"], "url": b["url"]}]
                    for b in msg["buttons"]
                ]
            }

        # если есть фото
        if msg.get("photo_path") and os.path.exists(msg["photo_path"]):

            with open(msg["photo_path"], "rb") as photo_file:
                resp = await client.post(
                    f"https://api.telegram.org/bot{msg['token']}/sendPhoto",
                    data={
                        "chat_id": msg["telegram_id"],
                        "caption": msg["text"] or "",
                        "parse_mode": "HTML",
                        "reply_markup": json.dumps(reply_markup) if reply_markup else None,
                    },
                    files={
                        "photo": photo_file
                    },
                    timeout=10,
                )

        else:
            payload = {
                "chat_id": msg["telegram_id"],
                "text": msg["text"],
                "parse_mode": "HTML",
            }

            if reply_markup:
                payload["reply_markup"] = reply_markup

            resp = await client.post(
                f"https://api.telegram.org/bot{msg['token']}/sendMessage",
                json=payload,
                timeout=10,
            )

            # Fallback для старых plain-text записей
            if resp.status_code == 400:
                payload.pop("parse_mode", None)
                resp = await client.post(
                    f"https://api.telegram.org/bot{msg['token']}/sendMessage",
                    json=payload,
                    timeout=10,
                )

            if resp.status_code == 429:
                if _retries >= 3:
                    logger.warning(f"[worker] delayed 429 max retries id:{msg['id']}")
                    return
                data = resp.json()
                retry_after = data.get("parameters", {}).get("retry_after", 1)
                logger.warning(f"[worker] delayed 429. Sleeping {retry_after}s")
                await asyncio.sleep(retry_after)
                return await process_delayed(client, msg, _retries + 1)

        if resp.status_code == 200:
            await client.patch(
                f"{BACKEND_URL}/delayed/{msg['id']}/sent",
                headers=HEADERS,
            )
            logger.debug(f"[worker] delayed sent id:{msg['id']}")
        else:
            logger.warning(
                f"[worker] delayed failed id:{msg['id']} status:{resp.status_code}"
            )

    except Exception as e:
        logger.error(f"[worker] delayed error id:{msg['id']} {e}")


async def call_delayed_worker(client: httpx.AsyncClient):
    try:
        r = await client.get(
            f"{BACKEND_URL}/delayed/pending",
            headers=HEADERS,
        )
        r.raise_for_status()
        messages = r.json()

        for msg in messages:
            await process_delayed(client, msg)

        if messages:
            logger.info(f"[worker] delayed: {len(messages)} messages processed")

    except Exception as e:
        logger.error(f"[worker] delayed worker error: {e}")


async def send_heartbeat(client: httpx.AsyncClient, did_health_check: bool, did_replacement: bool):
    try:
        payload = {}
        if did_health_check:
            payload["last_health_check"] = True
        if did_replacement:
            payload["last_replacement_run"] = True
        await client.post(
            f"{BACKEND_URL}/system/worker-heartbeat",
            json=payload,
            headers=HEADERS,
            timeout=10,
        )
    except Exception as e:
        logger.error(f"[worker] heartbeat error: {e}")


async def loop():
    logger.info("[worker] started")

    async with httpx.AsyncClient() as client:

        last_health = 0
        last_replace = 0

        while True:
            now = asyncio.get_event_loop().time()

            did_health = False
            did_replace = False

            if now - last_health >= HEALTHCHECK_INTERVAL_SEC:
                await call_healthcheck_all(client)
                last_health = now
                did_health = True

            if now - last_replace >= REPLACEMENT_INTERVAL_SEC:
                await call_replacement(client)
                last_replace = now
                did_replace = True

            await call_broadcast_worker(client)
            await call_delayed_worker(client)

            await send_heartbeat(client, did_health, did_replace)

            await asyncio.sleep(WORKER_LOOP_DELAY)


if __name__ == "__main__":
    asyncio.run(loop())