from typing import Optional

import httpx
from aiogram import Bot
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

from controller.config import BACKEND_URL, INTERNAL_API_KEY, REGION_BY_CODE


def owner_headers(telegram_id: int, with_api_key: bool = False):
    headers = {"X-TELEGRAM-ID": str(telegram_id)}
    if with_api_key and INTERNAL_API_KEY:
        headers["X-API-KEY"] = INTERNAL_API_KEY
    return headers


async def backend_request(
    method: str,
    endpoint: str,
    telegram_id: int,
    json: Optional[dict] = None,
    with_api_key: bool = False,
):
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.request(
            method=method,
            url=f"{BACKEND_URL}{endpoint}",
            headers=owner_headers(telegram_id, with_api_key),
            json=json,
        )
        response.raise_for_status()
        return response.json()


async def safe_edit(message, text: str, reply_markup=None, parse_mode: Optional[str] = None):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)


async def safe_edit_by_id(bot: Bot, chat_id: int, message_id: int, text: str, reply_markup=None, parse_mode: Optional[str] = None):
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)


async def safe_delete_message(message: Message):
    try:
        await message.delete()
    except Exception:
        pass


async def safe_delete_by_id(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def parse_buttons_input(text: str) -> list[dict]:
    lines = [x.strip() for x in text.split("\n") if x.strip()]
    buttons = []

    for line in lines:
        if "|" not in line:
            raise ValueError("Неверный формат. Используйте: Текст | ссылка")

        left, right = [x.strip() for x in line.split("|", 1)]

        if not left or not right.startswith("http"):
            raise ValueError("Проверьте текст и ссылку.")

        buttons.append({"text": left, "url": right})

    return buttons


def _render_selected_regions(selected_codes: list[str]) -> str:
    if not selected_codes:
        return "Вы пока ничего не выбрали."
    lines = "\n".join([f"{REGION_BY_CODE[c]['flag']} {REGION_BY_CODE[c]['title']}" for c in selected_codes if c in REGION_BY_CODE])
    return f"Выбрано ({len(selected_codes)}):\n{lines}"


async def _get_bot_username(owner_id: int, bot_id: str) -> str:
    bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    return next((b["username"] for b in bots if str(b["id"]) == str(bot_id)), "")


async def _get_configs_map(owner_id: int, bot_id: str) -> dict[str, dict]:
    configs = await backend_request("GET", f"/bots/{bot_id}/configs", telegram_id=owner_id)
    out = {}
    for c in configs:
        out[c.get("region")] = c
    return out
