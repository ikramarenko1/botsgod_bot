import asyncio
import httpx
import json

BACKEND_URL = "http://127.0.0.1:8000"

HEALTHCHECK_INTERVAL_SEC = 120
REPLACEMENT_INTERVAL_SEC = 300
BROADCAST_CHECK_INTERVAL = 10


async def call_healthcheck_all(client: httpx.AsyncClient):
    try:
        r = await client.post(f"{BACKEND_URL}/bots/health-check/all", timeout=30)
        r.raise_for_status()
        data = r.json()
        print("[worker] health-check/all:", data)
        return data
    except Exception as e:
        print("[worker] health-check/all error:", e)
        return None


async def call_replacement(client: httpx.AsyncClient):
    try:
        r = await client.post(f"{BACKEND_URL}/bots/replacement", timeout=30)
        r.raise_for_status()
        data = r.json()
        print("[worker] replacement:", data)
        return data
    except Exception as e:
        print("[worker] replacement error:", e)
        return None


async def process_broadcast(client, broadcast):
    print(f"[worker] attempting to lock broadcast {broadcast['id']}")

    try:
        r = await client.patch(
            f"{BACKEND_URL}/broadcasts/{broadcast['id']}/status",
            json={"status": "sending"},
        )
        r.raise_for_status()
    except Exception:
        print(f"[worker] broadcast id:{broadcast['id']} already locked")
        return

    print(f"[worker] processing broadcast id:{broadcast['id']}")

    total = 0
    sent = 0
    failed = 0

    users_resp = await client.get(
        f"{BACKEND_URL}/bots/{broadcast['bot_id']}/users"
    )
    users = users_resp.json()

    total = len(users)

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

            if tg_resp.status_code == 200:
                sent += 1
            else:
                failed += 1

            await asyncio.sleep(0.05)

        except Exception:
            failed += 1

    await client.patch(
        f"{BACKEND_URL}/broadcasts/{broadcast['id']}/status",
        json={
            "total_users": total,
            "sent_count": sent,
            "failed_count": failed,
            "started_at": True,
            "finished_at": True,
        }
    )

    print(f"[worker] broadcast id:{broadcast['id']} sent")
    print(f"Total: {total}, Sent: {sent}, Failed: {failed}")


async def process_delayed(client, msg):
    print(f"[worker] sending delayed {msg['id']}")

    payload = {
        "chat_id": msg["telegram_id"],
        "text": msg["text"],
    }

    if msg["buttons"]:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": b["text"], "url": b["url"]}]
                for b in msg["buttons"]
            ]
        }

    await client.post(
        f"https://api.telegram.org/bot{msg['token']}/sendMessage",
        json=payload,
    )

    await client.patch(
        f"{BACKEND_URL}/delayed/{msg['id']}/sent"
    )


async def call_broadcast_worker(client: httpx.AsyncClient):
    try:
        r = await client.get(f"{BACKEND_URL}/broadcasts/scheduled")
        r.raise_for_status()
        broadcasts = r.json()

        for b in broadcasts:
            await process_broadcast(client, b)

    except Exception as e:
        print("[worker] broadcast worker error:", e)


async def call_delayed_worker(client):
    try:
        r = await client.get(f"{BACKEND_URL}/delayed/pending")
        r.raise_for_status()
        messages = r.json()

        for msg in messages:
            await process_delayed(client, msg)

    except Exception as e:
        print("[worker] delayed error:", e)


async def loop():
    async with httpx.AsyncClient() as client:
        while True:
            await call_healthcheck_all(client)
            await call_replacement(client)
            await call_broadcast_worker(client)
            await call_delayed_worker(client)

            await asyncio.sleep(BROADCAST_CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(loop())