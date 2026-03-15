import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from controller.config import BOT_TOKEN
from controller.handlers import start, bots, welcome, delayed, broadcast, rename, avatar, auto_reply
from controller.handlers import mass_broadcast, mass_role, keys, team, global_config

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

dp.include_router(start.router)
dp.include_router(welcome.router)
dp.include_router(delayed.router)
dp.include_router(broadcast.router)
dp.include_router(rename.router)
dp.include_router(avatar.router)
dp.include_router(mass_broadcast.router)
dp.include_router(mass_role.router)
dp.include_router(keys.router)
dp.include_router(team.router)
dp.include_router(auto_reply.router)
dp.include_router(global_config.router)
dp.include_router(bots.router)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
