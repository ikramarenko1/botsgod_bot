import asyncio
import json
from typing import Optional

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

# Telegram лимит: 30 msg/sec на бота. Ставим 28 с запасом.
BROADCAST_RATE_PER_BOT = 28
# Глобальный лимит одновременных TCP-соединений к Telegram.
# sendMessage = 2-3s на стороне Telegram (не contention).
# 200 → 2.7s (74/sec), 600 → 5s (65/sec — contention).
# 400 = sweet spot: ~3.2s, ~125/sec.
BROADCAST_GLOBAL_CONCURRENCY = 400
# Кол-во worker-корутин на бота.
BROADCAST_WORKERS_PER_BOT = 40
BROADCAST_PROGRESS_STEP = 1000


class BotRateLimiter:
    """Per-bot rate limit (28/sec) + глобальный concurrency (общий семафор)."""

    def __init__(self, rate: int, global_sem: asyncio.Semaphore):
        self._rate_sem = asyncio.Semaphore(rate)
        self._global_sem = global_sem

    async def acquire(self):
        # Сначала rate (ожидание без ресурсов), потом TCP-слот
        await self._rate_sem.acquire()
        asyncio.get_running_loop().call_later(1.0, self._rate_sem.release)
        await self._global_sem.acquire()

    def release(self):
        self._global_sem.release()


async def notify_owner(client: httpx.AsyncClient, owner_id: int, text: str):
    if not CONTROLLER_BOT_TOKEN:
        return

    try:
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
        logger.error(f"[worker] notify error: {type(e).__name__}: {e}")


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
        logger.error(f"[worker] health-check error: {type(e).__name__}: {e}")


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
        logger.error(f"[worker] replacement error: {type(e).__name__}: {e}")


async def _send_one_message(client: httpx.AsyncClient, limiter: BotRateLimiter,
                            bot_token: str, user_tid: int,
                            text: str, reply_markup: Optional[dict],
                            diag: Optional[dict] = None) -> bool:
    t0 = asyncio.get_running_loop().time()
    await limiter.acquire()
    t1 = asyncio.get_running_loop().time()
    released = False
    try:
        payload = {
            "chat_id": user_tid,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        resp = await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=10,
        )
        t2 = asyncio.get_running_loop().time()

        # Диагностика: собираем timing первых 200 сообщений
        if diag is not None and diag["count"] < 200:
            diag["count"] += 1
            diag["acquire_total"] += (t1 - t0)
            diag["http_total"] += (t2 - t1)
            if diag["count"] == 200:
                avg_acq = diag["acquire_total"] / 200
                avg_http = diag["http_total"] / 200
                logger.info(
                    f"[worker] DIAG: avg acquire={avg_acq:.3f}s, "
                    f"avg http={avg_http:.3f}s (over 200 sends)"
                )

        if resp.status_code == 400:
            payload.pop("parse_mode", None)
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=payload,
                timeout=10,
            )

        if resp.status_code == 429:
            data = resp.json()
            retry_after = data.get("parameters", {}).get("retry_after", 1)
            logger.warning(f"[worker] broadcast 429, sleep {retry_after}s")
            limiter.release()  # освободить TCP-слот ДО сна
            released = True
            await asyncio.sleep(retry_after)
            return False

        return resp.status_code == 200

    except Exception as e:
        logger.error(f"[worker] send exception: {type(e).__name__}: {e}")
        return False
    finally:
        if not released:
            limiter.release()


async def _report_progress(client: httpx.AsyncClient, broadcast_id: int, progress: dict):
    """Fire-and-forget progress report — не блокирует воркеров."""
    try:
        await client.patch(
            f"{BACKEND_URL}/broadcasts/{broadcast_id}/stats",
            json={"sent_count": progress["sent"],
                  "failed_count": progress["failed"]},
            headers=HEADERS,
            timeout=10,
        )
        logger.info(
            f"[worker] broadcast {broadcast_id}: "
            f"{progress['done']}/{progress['total']} processed"
        )
    except Exception:
        pass


async def _send_for_bot(client: httpx.AsyncClient, broadcast_id: int,
                        bot_token: str, users: list,
                        text: str, reply_markup: Optional[dict],
                        progress: dict,
                        global_sem: asyncio.Semaphore) -> tuple[int, int]:
    limiter = BotRateLimiter(BROADCAST_RATE_PER_BOT, global_sem)
    queue = asyncio.Queue()
    sent = 0
    failed = 0
    diag = {"count": 0, "acquire_total": 0.0, "http_total": 0.0}

    for u in users:
        queue.put_nowait(u["telegram_id"])

    async def worker():
        nonlocal sent, failed
        while True:
            try:
                tid = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            result = await _send_one_message(
                client, limiter, bot_token, tid, text, reply_markup, diag
            )
            if result:
                sent += 1
                progress["sent"] += 1
            else:
                failed += 1
                progress["failed"] += 1

            progress["done"] += 1
            if progress["done"] - progress["last_reported"] >= BROADCAST_PROGRESS_STEP:
                progress["last_reported"] = progress["done"]
                asyncio.create_task(
                    _report_progress(client, broadcast_id, progress)
                )

    workers = [asyncio.create_task(worker()) for _ in range(BROADCAST_WORKERS_PER_BOT)]
    await asyncio.gather(*workers)

    return sent, failed


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
        await notify_owner(client, nid, f"🚀 <b>Рассылка #{broadcast_id} началась</b>")

    await client.patch(
        f"{BACKEND_URL}/broadcasts/{broadcast_id}/stats",
        json={"started_at": True},
        headers=HEADERS,
    )

    target_bot_ids = list(dict.fromkeys(broadcast.get("bot_ids") or [broadcast["bot_id"]]))

    reply_markup = build_reply_markup(broadcast.get("buttons"))

    # Загружаем данные по ботам (макс. 5 параллельно, чтобы не перегрузить backend)
    fetch_sem = asyncio.Semaphore(5)

    async def _fetch_bot_data(bot_id: int):
        async with fetch_sem:
            try:
                bot_resp = await client.get(
                    f"{BACKEND_URL}/system/bots/{bot_id}/users",
                    headers=HEADERS,
                    timeout=30,
                )
                bot_resp.raise_for_status()
                users = bot_resp.json()
            except Exception as e:
                logger.error(f"[worker] broadcast {broadcast_id}: get users bot {bot_id}: {type(e).__name__}: {e}")
                return None

            try:
                token_resp = await client.get(
                    f"{BACKEND_URL}/system/bot-token/{bot_id}",
                    headers=HEADERS,
                    timeout=10,
                )
                token_resp.raise_for_status()
                bot_token = token_resp.json().get("token", broadcast["token"])
            except Exception as e:
                logger.warning(f"[worker] broadcast {broadcast_id}: token fallback for bot {bot_id}: {type(e).__name__}")
                bot_token = broadcast["token"]

            if users:
                logger.info(f"[worker] broadcast {broadcast_id}: bot {bot_id}, {len(users)} users")
                return (bot_token, users)
            return None

    fetch_results = await asyncio.gather(*[
        _fetch_bot_data(bid) for bid in target_bot_ids
    ])

    bot_jobs = [r for r in fetch_results if r is not None]
    total = sum(len(users) for _, users in bot_jobs)

    # Один глобальный семафор на все боты — контролирует общее число TCP-соединений
    global_sem = asyncio.Semaphore(BROADCAST_GLOBAL_CONCURRENCY)

    progress = {"done": 0, "sent": 0, "failed": 0, "last_reported": 0, "total": total}

    logger.info(f"[worker] broadcast {broadcast_id}: starting, {len(bot_jobs)} bots, {total} users total")

    bot_results = await asyncio.gather(*[
        _send_for_bot(client, broadcast_id, bot_token, users,
                      broadcast["text"], reply_markup, progress, global_sem)
        for bot_token, users in bot_jobs
    ], return_exceptions=True)

    sent = 0
    failed = 0
    for r in bot_results:
        if isinstance(r, Exception):
            logger.error(f"[worker] broadcast {broadcast_id}: bot failed: {type(r).__name__}: {r}")
        else:
            sent += r[0]
            failed += r[1]

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
        await notify_owner(client, nid, finish_text)

    logger.info(
        f"[worker] broadcast {broadcast_id} done: {sent}/{total} sent, {failed} failed"
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
        logger.error(f"[worker] broadcast worker error: {type(e).__name__}: {e}")


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
        else:
            logger.warning(
                f"[worker] delayed failed id:{msg['id']} status:{resp.status_code}"
            )

    except Exception as e:
        logger.error(f"[worker] delayed error id:{msg['id']} {type(e).__name__}: {e}")


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
        logger.error(f"[worker] delayed worker error: {type(e).__name__}: {e}")


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
        logger.error(f"[worker] heartbeat error: {type(e).__name__}: {e}")


async def loop():
    logger.info("[worker] started")

    # Connection pool: 400 для TG + запас для backend.
    limits = httpx.Limits(
        max_connections=500,
        max_keepalive_connections=400,
    )
    async with httpx.AsyncClient(limits=limits) as client:

        last_health = 0
        last_replace = 0

        while True:
            now = asyncio.get_running_loop().time()

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
