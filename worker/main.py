import asyncio
import httpx

BACKEND_URL = "http://127.0.0.1:8000"

HEALTHCHECK_INTERVAL_SEC = 120
REPLACEMENT_INTERVAL_SEC = 300


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


async def loop():
    async with httpx.AsyncClient() as client:
        while True:
            await call_healthcheck_all(client)
            await call_replacement(client)

            await asyncio.sleep(min(HEALTHCHECK_INTERVAL_SEC, REPLACEMENT_INTERVAL_SEC))


if __name__ == "__main__":
    asyncio.run(loop())