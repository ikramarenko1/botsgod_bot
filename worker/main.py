import asyncio
import json

import httpx
import os
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")
BACKEND_URL = os.getenv("BACKEND_URL")
LOG_FILE = os.getenv("WORKER_LOG_FILE")

HEADERS = {
    "X-API-KEY": INTERNAL_API_KEY
}

logger = logging.getLogger("stagecontrol_worker")
logger.setLevel(logging.INFO)

if LOG_FILE:
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10_000_000,
        backupCount=3
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
else:
    logging.basicConfig(level=logging.INFO)


HEALTHCHECK_INTERVAL_SEC = 60
REPLACEMENT_INTERVAL_SEC = 15
WORKER_LOOP_DELAY = 10


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

    await client.patch(
        f"{BACKEND_URL}/broadcasts/{broadcast_id}/stats",
        json={"started_at": True},
        headers=HEADERS,
    )

    users_resp = await client.get(
        f"{BACKEND_URL}/system/bots/{broadcast['bot_id']}/users",
        headers=HEADERS,
        timeout=30,
    )
    users_resp.raise_for_status()
    users = users_resp.json()

    total = len(users)
    sent = 0
    failed = 0

    for user in users:
        try:
            payload = {
                "chat_id": user["telegram_id"],
                "text": broadcast["text"],
            }

            if broadcast["buttons"]:
                payload["reply_markup"] = {
                    "inline_keyboard": [
                        [{"text": b["text"], "url": b["url"]}]
                        for b in broadcast["buttons"]
                    ]
                }

            tg_resp = await client.post(
                f"https://api.telegram.org/bot{broadcast['token']}/sendMessage",
                json=payload,
                timeout=10,
            )

            if tg_resp.status_code == 429:
                data = tg_resp.json()
                retry_after = data.get("parameters", {}).get("retry_after", 1)
                logger.warning(f"[worker] 429 flood. Sleeping {retry_after}s")
                await asyncio.sleep(retry_after)
                continue

            if tg_resp.status_code == 200:
                sent += 1
            else:
                failed += 1

            await asyncio.sleep(0.05)

        except Exception:
            failed += 1

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


async def process_delayed(client: httpx.AsyncClient, msg: dict):
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
            }

            if reply_markup:
                payload["reply_markup"] = reply_markup

            resp = await client.post(
                f"https://api.telegram.org/bot{msg['token']}/sendMessage",
                json=payload,
                timeout=10,
            )

            if resp.status_code == 429:
                data = resp.json()
                retry_after = data.get("parameters", {}).get("retry_after", 1)
                logger.warning(f"[worker] delayed 429. Sleeping {retry_after}s")
                await asyncio.sleep(retry_after)
                return await process_delayed(client, msg)

        if resp.status_code == 200:
            await client.patch(
                f"{BACKEND_URL}/delayed/{msg['id']}/sent",
                headers=HEADERS,
            )
            logger.info(f"[worker] delayed sent id:{msg['id']}")
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

    except Exception as e:
        logger.error(f"[worker] delayed worker error: {e}")


async def loop():
    logger.info("[worker] started")

    async with httpx.AsyncClient() as client:

        last_health = 0
        last_replace = 0

        while True:
            now = asyncio.get_event_loop().time()

            if now - last_health >= HEALTHCHECK_INTERVAL_SEC:
                await call_healthcheck_all(client)
                last_health = now

            if now - last_replace >= REPLACEMENT_INTERVAL_SEC:
                await call_replacement(client)
                last_replace = now

            await call_broadcast_worker(client)
            await call_delayed_worker(client)

            await asyncio.sleep(WORKER_LOOP_DELAY)


if __name__ == "__main__":
    asyncio.run(loop())