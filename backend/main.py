import os
import logging
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

from backend.api.bots import router as bots_router
from backend.api.broadcasts import router as broadcasts_router
from backend.api.system import router as system_router
from backend.api.webhooks import router as webhooks_router
from backend.api.welcome import router as welcome_router
from backend.api.delayed import router as delayed_router
from backend.api.keys import router as keys_router
from backend.api.top_configs import router as top_configs_router

MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

LOG_FILE = os.getenv("LOG_FILE")

logger = logging.getLogger("stagecontrol")
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


app = FastAPI(title="StageControl Backend")


@app.get("/")
async def health():
    return {"status": "ok"}


app.include_router(bots_router)
app.include_router(broadcasts_router)
app.include_router(system_router)
app.include_router(webhooks_router)
app.include_router(welcome_router)
app.include_router(delayed_router)
app.include_router(keys_router)
app.include_router(top_configs_router)
