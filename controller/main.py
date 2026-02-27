import asyncio
import os
from typing import Optional

import httpx
from aiogram import Bot, Dispatcher
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile
)
from aiogram.filters import CommandStart
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from datetime import datetime, timedelta

from states import AddBotState, WelcomeStates, DelayedStates, BroadcastStates, RenameStates, AvatarStates

load_dotenv()

BOT_TOKEN = os.getenv("CONTROLLER_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("CONTROLLER_BOT_TOKEN not set")

if not BACKEND_URL:
    raise RuntimeError("BACKEND_URL not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


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


async def safe_edit_by_id(chat_id: int, message_id: int, text: str, reply_markup=None, parse_mode: Optional[str] = None):
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

async def safe_delete_by_id(chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


main_reply_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Меню")]],
    resize_keyboard=True,
    is_persistent=True,
)


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Мои боты", callback_data="my_bots")],
            [InlineKeyboardButton(text="➕ Добавить бота", callback_data="add_bot")],
        ]
    )


UTC3_OFFSET = timedelta(hours=3)

def now_utc() -> datetime:
    return datetime.utcnow()

def now_utc3() -> datetime:
    return now_utc() + UTC3_OFFSET

def utc3_to_utc(dt_utc3: datetime) -> datetime:
    return dt_utc3 - UTC3_OFFSET

def parse_utc3_input_to_utc_iso(text: str) -> str:
    """
    Поддержка:
      - "Сейчас"
      - "ЧЧ:ММ" (сегодня, если прошло - завтра)
      - "ДД.ММ.ГГГГ ЧЧ:ММ"
    """
    raw = text.strip()
    low = raw.lower()

    if low in ("сейчас", "now"):
        return now_utc().replace(microsecond=0).isoformat()

    # HH:MM
    if len(raw) == 5 and raw[2] == ":":
        hh, mm = raw.split(":")
        if not (hh.isdigit() and mm.isdigit()):
            raise ValueError("bad time")
        base = now_utc3()
        candidate = base.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if candidate <= base:
            candidate = candidate + timedelta(days=1)
        return utc3_to_utc(candidate).replace(microsecond=0).isoformat()

    # DD.MM.YYYY HH:MM
    dt_utc3 = datetime.strptime(raw, "%d.%m.%Y %H:%M").replace(second=0, microsecond=0)
    return utc3_to_utc(dt_utc3).replace(microsecond=0).isoformat()


def parse_utc_iso(s: str) -> datetime:
    s = (s or "").replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)
    return dt

def utc_iso_to_utc3_human(s: Optional[str]) -> str:
    if not s:
        return "—"
    dt_utc = parse_utc_iso(s)
    dt_utc3 = dt_utc + UTC3_OFFSET
    return dt_utc3.strftime("%d.%m.%Y %H:%M")


def buttons_status(buttons: Optional[list]) -> str:
    return "🟢" if buttons else "🔴"


def status_emoji(status: str) -> str:
    return {
        "draft": "📝",
        "scheduled": "⏳",
        "sending": "📡",
        "sent": "✅",
        "failed": "❌",
        "cancelled": "🛑",
    }.get(status or "", "•")


def short_text(s: Optional[str], n: int = 60) -> str:
    if not s:
        return ""
    s = s.strip()
    return s if len(s) <= n else s[:n] + "…"


async def render_welcome_menu(
    message: Message,
    owner_id: int,
    bot_id: str,
    edit: bool = False
):
    try:
        welcome = await backend_request(
            "GET",
            f"/bots/{bot_id}/welcome",
            telegram_id=owner_id,
        )
    except:
        welcome = None

    bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    bot_username = next(
        (b["username"] for b in bots if str(b["id"]) == bot_id),
        ""
    )

    photo_status = "🟢" if welcome and welcome.get("photo_path") else "🔴"
    buttons_flag = "🟢" if welcome and welcome.get("buttons") else "🔴"

    text_block = (
        f"<blockquote>{welcome.get('text')}</blockquote>"
        if welcome and welcome.get("text")
        else "— не задано —"
    )

    text = (
        f"🏠 <b>Настройка приветствия бота @{bot_username}</b>\n\n"

        f"📝 <b>Текущее сообщение:</b>\n"
        f"{text_block}\n\n"

        f"📸 Фото: {photo_status}\n"
        f"🔗 Кнопки: {buttons_flag}\n\n"

        f"Выберите действие:"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Текст", callback_data=f"welcome_{bot_id}_text"),
                InlineKeyboardButton(text="🖼 Фото", callback_data=f"welcome_{bot_id}_photo"),
            ],
            [
                InlineKeyboardButton(text="🔗 Кнопки", callback_data=f"welcome_{bot_id}_buttons"),
                InlineKeyboardButton(text="🧪 Тест", callback_data=f"welcome_{bot_id}_test"),
            ],
            [
                InlineKeyboardButton(text="🗑 Сбросить", callback_data=f"welcome_{bot_id}_reset"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")
            ]
        ]
    )

    try:
        if edit:
            await message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            await message.answer(
                text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except TelegramBadRequest:
        await message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )


async def render_delayed_menu(
    message: Message,
    owner_id: int,
    bot_id: str,
    edit: bool = False
):
    try:
        delayed = await backend_request(
            "GET",
            f"/bots/{bot_id}/delayed",
            telegram_id=owner_id,
        )

        bots = await backend_request(
            "GET",
            "/bots",
            telegram_id=owner_id,
        )

    except:
        await message.answer("Ошибка загрузки данных")
        return

    bot_username = next(
        (b["username"] for b in bots if str(b["id"]) == bot_id),
        ""
    )

    delayed_text = delayed.get("text")
    delayed_buttons = delayed.get("buttons")
    delay_minutes = delayed.get("delay_minutes")
    photo_path = delayed.get("photo_path")

    text_block = (
        f"<blockquote>{delayed_text}</blockquote>"
        if delayed_text else "— не задано —"
    )

    photo_status = "🟢" if photo_path else "🔴"
    buttons_flag = "🟢" if delayed_buttons else "🔴"
    delay_value = f"{delay_minutes} мин" if delay_minutes is not None else "не установлено"
    enabled_status = "🟢 Активно" if delayed_text and delay_minutes is not None else "🔴 Не активно"

    text = (
        f"⏳ <b>Отложенное сообщение для @{bot_username}</b>\n\n"
        f"📝 <b>Текст:</b>\n{text_block}\n\n"
        f"📸 Фото: {photo_status}\n"
        f"🔗 Кнопки: {buttons_flag}\n"
        f"⏳ Задержка: {delay_value}\n\n"
        f"📡 Статус: {enabled_status}\n\n"
        f"Выберите действие:"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏️ Текст", callback_data=f"delayed_{bot_id}_text"),
                InlineKeyboardButton(text="🖼 Фото", callback_data=f"delayed_{bot_id}_photo"),
            ],
            [
                InlineKeyboardButton(text="🔗 Кнопки", callback_data=f"delayed_{bot_id}_buttons"),
                InlineKeyboardButton(text="⏳ Задержка", callback_data=f"delayed_{bot_id}_delay"),
            ],
            [
                InlineKeyboardButton(text="🧪 Тест", callback_data=f"delayed_{bot_id}_test"),
                InlineKeyboardButton(text="🗑 Сбросить", callback_data=f"delayed_{bot_id}_reset"),
            ],
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")
            ]
        ]
    )

    if edit:
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


async def render_bot_menu(message: Message, owner_id: int, bot_id: str, edit: bool = False):
    try:
        bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    except Exception:
        await safe_edit(message, "Ошибка загрузки данных бота.")
        return

    bot_username = next((b["username"] for b in bots if str(b["id"]) == str(bot_id)), None)
    if not bot_username:
        await safe_edit(message, "Бот не найден.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data=f"bot_{bot_id}_stats")],
            [InlineKeyboardButton(text="📩 Сообщение", callback_data=f"bot_{bot_id}_message")],
            [InlineKeyboardButton(text="⏳ Отложенное сообщение", callback_data=f"bot_{bot_id}_delayed")],
            [InlineKeyboardButton(text="📢 Создать рассылку", callback_data=f"bot_{bot_id}_create_broadcast")],
            [InlineKeyboardButton(text="🗂 Отложенные рассылки", callback_data=f"bot_{bot_id}_scheduled_broadcasts")],
            [InlineKeyboardButton(text="✏ Изменить название", callback_data=f"bot_{bot_id}_rename")],
            [InlineKeyboardButton(text="🖼 Изменить фото", callback_data=f"bot_{bot_id}_avatar")],
            [InlineKeyboardButton(text="⛔ Выключить бота", callback_data=f"bot_{bot_id}_disable")],
            [InlineKeyboardButton(text="📦 Выгрузить пользователей", callback_data=f"bot_{bot_id}_export_users")],
            [InlineKeyboardButton(text="🗑 Удалить бота", callback_data=f"bot_{bot_id}_delete")],
            [InlineKeyboardButton(text="« Назад", callback_data="my_bots")]
        ]
    )

    text = f"Управление ботом @{bot_username}."
    if edit:
        await safe_edit(message, text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


async def render_bot_menu_by_id(chat_id: int, owner_id: int, bot_id: str, message_id: int):
    try:
        bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    except Exception:
        await safe_edit_by_id(chat_id, message_id, "Ошибка загрузки данных бота.")
        return

    bot_username = next((b["username"] for b in bots if str(b["id"]) == str(bot_id)), None)
    if not bot_username:
        await safe_edit_by_id(chat_id, message_id, "Бот не найден.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data=f"bot_{bot_id}_stats")],
            [InlineKeyboardButton(text="📩 Сообщение", callback_data=f"bot_{bot_id}_message")],
            [InlineKeyboardButton(text="⏳ Отложенное сообщение", callback_data=f"bot_{bot_id}_delayed")],
            [InlineKeyboardButton(text="📢 Создать рассылку", callback_data=f"bot_{bot_id}_create_broadcast")],
            [InlineKeyboardButton(text="🗂 Отложенные рассылки", callback_data=f"bot_{bot_id}_scheduled_broadcasts")],
            [InlineKeyboardButton(text="✏ Изменить название", callback_data=f"bot_{bot_id}_rename")],
            [InlineKeyboardButton(text="🖼 Изменить фото", callback_data=f"bot_{bot_id}_avatar")],
            [InlineKeyboardButton(text="⛔ Выключить бота", callback_data=f"bot_{bot_id}_disable")],
            [InlineKeyboardButton(text="📦 Выгрузить пользователей", callback_data=f"bot_{bot_id}_export_users")],
            [InlineKeyboardButton(text="🗑 Удалить бота", callback_data=f"bot_{bot_id}_delete")],
            [InlineKeyboardButton(text="« Назад", callback_data="my_bots")]
        ]
    )

    await safe_edit_by_id(
        chat_id=chat_id,
        message_id=message_id,
        text=f"Управление ботом @{bot_username}.",
        reply_markup=keyboard
    )


async def broadcast_show_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("text") or ""
    buttons = data.get("buttons")
    scheduled_at = data.get("scheduled_at")
    wizard_msg_id = data.get("wizard_msg_id")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать", callback_data="broadcast_confirm")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")],
        ]
    )

    content = (
        "📢 <b>Проверка рассылки</b>\n\n"
        f"📝 <b>Текст:</b>\n<blockquote>{text}</blockquote>\n\n"
        f"🔗 Кнопки: {buttons_status(buttons)}\n"
        f"⏳ Отправка: <b>{utc_iso_to_utc3_human(scheduled_at)}</b> (UTC+3)\n\n"
        "Выберите действие:"
    )

    if wizard_msg_id:
        await safe_edit_by_id(message.chat.id, wizard_msg_id, content, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(content, reply_markup=kb, parse_mode="HTML")


LANG_REGIONS = [
    # СНГ
    {"code": "ru", "title": "Русский", "flag": "🇷🇺", "group": "cis"},
    {"code": "uk", "title": "Українська", "flag": "🇺🇦", "group": "cis"},
    {"code": "kk", "title": "Қазақша", "flag": "🇰🇿", "group": "cis"},
    {"code": "az", "title": "Azərbaycanca", "flag": "🇦🇿", "group": "cis"},
    {"code": "hy", "title": "Հայերեն", "flag": "🇦🇲", "group": "cis"},
    {"code": "ka", "title": "ქართული", "flag": "🇬🇪", "group": "cis"},
    {"code": "uz", "title": "Oʻzbek", "flag": "🇺🇿", "group": "cis"},
    {"code": "be", "title": "Беларуская", "flag": "🇧🇾", "group": "cis"},
    {"code": "tg", "title": "Тоҷикӣ", "flag": "🇹🇯", "group": "cis"},

    # Запад
    {"code": "en", "title": "English", "flag": "🇺🇸", "group": "west"},
    {"code": "de", "title": "Deutsch", "flag": "🇩🇪", "group": "west"},
    {"code": "fr", "title": "Français", "flag": "🇫🇷", "group": "west"},
    {"code": "es", "title": "Español", "flag": "🇪🇸", "group": "west"},
    {"code": "it", "title": "Italiano", "flag": "🇮🇹", "group": "west"},
    {"code": "pt", "title": "Português", "flag": "🇵🇹", "group": "west"},
    {"code": "pl", "title": "Polski", "flag": "🇵🇱", "group": "west"},
    {"code": "nl", "title": "Nederlands", "flag": "🇳🇱", "group": "west"},
    {"code": "cs", "title": "Čeština", "flag": "🇨🇿", "group": "west"},
    {"code": "ro", "title": "Română", "flag": "🇷🇴", "group": "west"},
    {"code": "el", "title": "Ελληνικά", "flag": "🇬🇷", "group": "west"},
    {"code": "sv", "title": "Svenska", "flag": "🇸🇪", "group": "west"},
    {"code": "da", "title": "Dansk", "flag": "🇩🇰", "group": "west"},
    {"code": "no", "title": "Norsk", "flag": "🇳🇴", "group": "west"},
    {"code": "fi", "title": "Suomi", "flag": "🇫🇮", "group": "west"},

    # Азия
    {"code": "tr", "title": "Türkçe", "flag": "🇹🇷", "group": "asia"},
    {"code": "ar", "title": "العربية", "flag": "🇸🇦", "group": "asia"},
    {"code": "he", "title": "עברית", "flag": "🇮🇱", "group": "asia"},
    {"code": "hi", "title": "हिन्दी", "flag": "🇮🇳", "group": "asia"},
    {"code": "th", "title": "ไทย", "flag": "🇹🇭", "group": "asia"},
    {"code": "vi", "title": "Tiếng Việt", "flag": "🇻🇳", "group": "asia"},
    {"code": "id", "title": "Bahasa Indonesia", "flag": "🇮🇩", "group": "asia"},
    {"code": "ms", "title": "Bahasa Melayu", "flag": "🇲🇾", "group": "asia"},
    {"code": "zh", "title": "中文", "flag": "🇨🇳", "group": "asia"},
    {"code": "ja", "title": "日本語", "flag": "🇯🇵", "group": "asia"},
    {"code": "ko", "title": "한국어", "flag": "🇰🇷", "group": "asia"},
]

REGION_BY_CODE = {x["code"]: x for x in LANG_REGIONS}


def _render_selected_regions(selected_codes: list[str]) -> str:
    if not selected_codes:
        return "Вы пока ничего не выбрали."
    lines = "\n".join([f"{REGION_BY_CODE[c]['flag']} {REGION_BY_CODE[c]['title']}" for c in selected_codes if c in REGION_BY_CODE])
    return f"Выбрано ({len(selected_codes)}):\n{lines}"


def _regions_keyboard(bot_id: str, selected: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="СНГ", callback_data=f"rename_{bot_id}_geo_group_cis"),
            InlineKeyboardButton(text="Запад", callback_data=f"rename_{bot_id}_geo_group_west"),
            InlineKeyboardButton(text="Азия", callback_data=f"rename_{bot_id}_geo_group_asia"),
        ],
        [InlineKeyboardButton(text="🌍 На все регионы", callback_data=f"rename_{bot_id}_geo_all")],
    ]

    grid = []
    for item in LANG_REGIONS:
        code = item["code"]
        flag = item["flag"]
        is_on = code in selected
        txt = f"✅ {flag}" if is_on else flag
        grid.append(InlineKeyboardButton(text=txt, callback_data=f"rename_{bot_id}_geo_t_{code}"))

    for i in range(0, len(grid), 3):
        rows.append(grid[i:i+3])

    rows.append([
        InlineKeyboardButton(text="✅ Готово", callback_data=f"rename_{bot_id}_geo_done"),
        InlineKeyboardButton(text="♻️ Сброс", callback_data=f"rename_{bot_id}_geo_reset"),
    ])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"rename_{bot_id}_geo_back"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _get_bot_username(owner_id: int, bot_id: str) -> str:
    bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    return next((b["username"] for b in bots if str(b["id"]) == str(bot_id)), "")


async def _get_configs_map(owner_id: int, bot_id: str) -> dict[str, dict]:
    configs = await backend_request("GET", f"/bots/{bot_id}/configs", telegram_id=owner_id)
    # ожидаем list[{"region":..., "name":..., "description":...}]
    out = {}
    for c in configs:
        out[c.get("region")] = c
    return out


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Добро пожаловать.",
        reply_markup=main_reply_keyboard,
    )

    await message.answer(
        "Этот чудо-бот - это конструктор ваших ботов в Telegram.\n"
        "Ещё какой-то текст?",
        reply_markup=main_menu_keyboard(),
    )


@dp.message(lambda message: message.text == "Меню")
async def menu_handler(message: Message):
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu_keyboard(),
    )


@dp.callback_query(lambda c: c.data == "my_bots")
async def my_bots_handler(callback):
    owner_id = callback.from_user.id

    try:
        bots = await backend_request(
            "GET",
            "/bots",
            telegram_id=owner_id,
        )
    except Exception:
        await safe_edit(callback.message, "Ошибка получения списка ботов.")
        await callback.answer()
        return

    inline_buttons = []

    inline_buttons.append([
        InlineKeyboardButton(
            text="📢 Массовая рассылка",
            callback_data="broadcast_menu"
        )
    ])

    inline_buttons.append([
        InlineKeyboardButton(
            text="📦 Выгрузка ботов",
            callback_data="export_bots"
        )
    ])

    for bot_obj in bots:
        inline_buttons.append([
            InlineKeyboardButton(
                text=bot_obj["username"],
                callback_data=f"bot_{bot_obj['id']}"
            )
        ])

    inline_buttons.append([
        InlineKeyboardButton(
            text="« Назад",
            callback_data="back_to_main"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_buttons)

    await safe_edit(
        callback.message,
        "Выберите бота из списка ниже.",
        reply_markup=keyboard,
    )

    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_handler(callback):
    await safe_edit(
        callback.message,
        "Главное меню:",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("bot_") and "_" not in c.data[4:])
async def bot_manage_handler(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    await render_bot_menu(callback.message, owner_id, bot_id, edit=True)
    await callback.answer()


@dp.callback_query(lambda c: c.data.endswith("_stats"))
async def bot_stats_handler(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    await safe_edit(callback.message, "⏳ Загружаю статистику...")

    try:
        stats = await backend_request(
            "GET",
            f"/bots/{bot_id}/stats",
            telegram_id=owner_id,
        )

        bots = await backend_request(
            "GET",
            "/bots",
            telegram_id=owner_id,
        )
    except Exception:
        await safe_edit(callback.message, "❌ Ошибка загрузки статистики.")
        await callback.answer()
        return

    bot_username = next(
        (b["username"] for b in bots if str(b["id"]) == bot_id),
        ""
    )

    total = stats.get("total_users", 0)
    premium = stats.get("premium_users", 0)
    normal = stats.get("normal_users", 0)

    premium_percent = round((premium / total) * 100, 1) if total else 0
    normal_percent = round((normal / total) * 100, 1) if total else 0

    geo = stats.get("geo", {})

    geo_lines = ""
    if geo:
        for code, count in geo.items():
            percent = round((count / total) * 100, 1) if total else 0
            geo_lines += f"{code.upper()}: {count} ({percent}%)\n"
    else:
        geo_lines = "Нет данных\n"

    text = (
        f"<b>📊 Статистика пользователей бота @{bot_username}</b>\n\n"

        f"<b>👥 Всего пользователей:</b> {total}\n"
        f"💎 Премиум пользователи: {premium} ({premium_percent}%)\n"
        f"👤 Обычные пользователи: {normal} ({normal_percent}%)\n\n"

        f"<b>🌍 География пользователей:</b>\n"
        f"{geo_lines}\n"

        f"<b>📈 Рост аудитории:</b>\n"
        f"⏰ За последний час: +{stats.get('growth_hour', 0)}\n"
        f"📅 За последний день: +{stats.get('growth_day', 0)}\n"
        f"📊 За последнюю неделю: +{stats.get('growth_week', 0)}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"bot_{bot_id}_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data=f"bot_{bot_id}"
                )
            ],
        ]
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    await callback.answer()


@dp.callback_query(lambda c: c.data == "add_bot")
async def add_bot_start(callback, state: FSMContext):
    text = (
        "Чтобы подключить бот, Вам нужно выполнить следующие действия:\n\n"
        "1. Перейдите в @BotFather и создайте новый бот (можно импортировать существующий).\n"
        "2. После создания бота Вы получите токен (123456:ABCDEF) — "
        "скопируйте или перешлите его в этот чат.\n\n"
        "Важно: не подключайте боты, которые уже используются другими сервисами."
    )

    await safe_edit(callback.message, text)
    await state.set_state(AddBotState.waiting_for_token)
    await callback.answer()


async def main():
    await dp.start_polling(bot)


@dp.message(AddBotState.waiting_for_token)
async def add_bot_token_handler(message: Message, state: FSMContext):
    owner_id = message.from_user.id
    token = message.text.strip()

    if ":" not in token:
        await message.answer("❌ Похоже это не токен. Попробуйте снова.")
        return

    try:
        result = await backend_request(
            "POST",
            "/bots/add",
            telegram_id=owner_id,
            json={"token": token},
            with_api_key=True,
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            await message.answer("❌ Неверный токен или бот уже добавлен.")
        else:
            await message.answer("❌ Ошибка сервера.")
        return
    except Exception:
        await message.answer("❌ Ошибка подключения к backend.")
        return

    username = result.get("username")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Мои боты", callback_data="my_bots")]
        ]
    )

    await message.answer(
        f"✅ Успешно добавлено ботов: 1\n@{username}",
        reply_markup=keyboard,
    )

    await state.clear()


@dp.callback_query(lambda c: c.data.endswith("_message"))
async def welcome_menu(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    await render_welcome_menu(
        callback.message,
        owner_id,
        bot_id,
        edit=True
    )

    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("welcome_") and c.data.endswith("_text"))
async def welcome_text_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(WelcomeStates.waiting_text)

    await callback.message.answer("📝 Отправьте новый текст приветствия.")
    await callback.answer()


@dp.message(WelcomeStates.waiting_text)
async def welcome_text_save(message: Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["bot_id"]
    owner_id = message.from_user.id

    try:
        current = await backend_request(
            "GET",
            f"/bots/{bot_id}/welcome",
            telegram_id=owner_id,
        )
    except:
        current = {}

    await backend_request(
        "POST",
        f"/bots/{bot_id}/welcome",
        telegram_id=owner_id,
        json={
            "text": message.text,
            "photo_path": current.get("photo_path"),
            "buttons": current.get("buttons"),
            "is_enabled": True
        }
    )

    await message.answer(
        "✅ <b>Текст приветствия обновлён</b>\n\n"
        f"<blockquote>{message.text}</blockquote>",
        parse_mode="HTML"
    )
    await state.clear()
    await render_welcome_menu(message, owner_id, bot_id)


@dp.callback_query(lambda c: c.data.startswith("welcome_") and c.data.endswith("_photo"))
async def welcome_photo_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(WelcomeStates.waiting_photo)

    await callback.message.answer("🖼 Отправьте фото которое будет показываться с приветственным сообщением.")
    await callback.answer()


@dp.message(WelcomeStates.waiting_photo)
async def welcome_photo_save(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("❌ Нужно отправить фото.")
        return

    owner_id = message.from_user.id
    data = await state.get_data()
    bot_id = data["bot_id"]

    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)

    async with httpx.AsyncClient() as client:
        file_response = await client.get(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        )

        if file_response.status_code != 200:
            await message.answer("❌ Не удалось скачать файл из Telegram")
            await state.clear()
            return

        extension = os.path.splitext(file.file_path)[1]
        filename = f"welcome{extension}"

        upload_resp = await client.post(
            f"{BACKEND_URL}/bots/{bot_id}/welcome/photo",
            headers=owner_headers(owner_id, with_api_key=True),
            files={"file": (filename, file_response.content)}
        )

        upload_resp.raise_for_status()

    await message.answer(
        "🖼 <b>Фото обновлено</b>\n\n"
        "Теперь приветствие будет отображаться с изображением.",
        parse_mode="HTML"
    )
    await state.clear()
    await render_welcome_menu(message, owner_id, bot_id)


@dp.callback_query(lambda c: c.data.startswith("welcome_") and c.data.endswith("_test"))
async def welcome_test(callback):
    bot_id = callback.data.split("_")[1]
    owner_id = callback.from_user.id

    try:
        welcome = await backend_request(
            "GET",
            f"/bots/{bot_id}/welcome",
            telegram_id=owner_id,
        )
    except:
        await callback.answer("❌ Сообщение не настроено")
        return

    text = welcome.get("text")
    buttons = welcome.get("buttons")
    photo_exists = bool(welcome.get("photo_path"))

    reply_markup = None
    if buttons:
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=b["text"], url=b["url"])]
                for b in buttons
            ]
        )

    try:
        async with httpx.AsyncClient(timeout=10) as client:

            if photo_exists:
                photo_resp = await client.get(
                    f"{BACKEND_URL}/bots/{bot_id}/welcome/photo",
                    headers=owner_headers(owner_id),
                )

                photo_resp.raise_for_status()

                content_type = photo_resp.headers.get("content-type", "")

                if "png" in content_type:
                    ext = ".png"
                elif "webp" in content_type:
                    ext = ".webp"
                else:
                    ext = ".jpg"

                photo_file = BufferedInputFile(
                    photo_resp.content,
                    filename=f"welcome{ext}"
                )

                await callback.message.answer_photo(
                    photo=photo_file,
                    caption=text or "",
                    reply_markup=reply_markup,
                )

            elif text:
                await callback.message.answer(
                    text,
                    reply_markup=reply_markup,
                )
            else:
                await callback.answer("❌ Сообщение пустое")
                return

        await callback.answer("✅ Тест отправлен")

    except Exception as e:
        print("TEST ERROR:", e)
        await callback.answer("❌ Ошибка отправки теста")


@dp.callback_query(lambda c: c.data.startswith("welcome_") and c.data.endswith("_buttons"))
async def welcome_buttons_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]

    await state.update_data(bot_id=bot_id)
    await state.set_state(WelcomeStates.waiting_buttons)

    text = (
        "🔗 <b>Настройка кнопок приветствия</b>\n\n"
        "Отправьте кнопки в формате:\n\n"
        "Текст кнопки | ссылка\n"
        "Кнопка 1 | https://example.com\n\n"
        "Или отправьте <code>-</code> чтобы пропустить"
    )

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@dp.message(WelcomeStates.waiting_buttons)
async def welcome_buttons_save(message: Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["bot_id"]
    owner_id = message.from_user.id

    text_input = message.text.strip()

    if text_input == "-":
        await message.answer("Ок, оставляем кнопки без изменений.")
        await state.clear()
        await render_welcome_menu(message, owner_id, bot_id)
        return

    if text_input.lower() == "удалить":
        try:
            current = await backend_request(
                "GET",
                f"/bots/{bot_id}/welcome",
                telegram_id=owner_id,
            )
        except:
            current = {}

        await backend_request(
            "POST",
            f"/bots/{bot_id}/welcome",
            telegram_id=owner_id,
            json={
                "text": current.get("text"),
                "photo_path": current.get("photo_path"),
                "buttons": None,
                "is_enabled": True
            }
        )

        await message.answer("🗑 Кнопки удалены.")
        await state.clear()
        return

    lines = text_input.split("\n")
    buttons = []

    for line in lines:
        if "|" not in line:
            await message.answer("❌ Неверный формат. Используйте: Текст | ссылка")
            return

        parts = line.split("|")
        if len(parts) != 2:
            await message.answer("❌ Неверный формат строки.")
            return

        btn_text = parts[0].strip()
        btn_url = parts[1].strip()

        if not btn_text or not btn_url.startswith("http"):
            await message.answer("❌ Проверьте текст и ссылку.")
            return

        buttons.append({
            "text": btn_text,
            "url": btn_url
        })

    try:
        current = await backend_request(
            "GET",
            f"/bots/{bot_id}/welcome",
            telegram_id=owner_id,
        )
    except:
        current = {}

    await backend_request(
        "POST",
        f"/bots/{bot_id}/welcome",
        telegram_id=owner_id,
        json={
            "text": current.get("text"),
            "photo_path": current.get("photo_path"),
            "buttons": buttons,
            "is_enabled": True
        }
    )

    await message.answer(
        f"🔗 <b>Кнопки обновлены</b>\n\n"
        f"Добавлено кнопок: <code>{len(buttons)}</code>",
        parse_mode="HTML"
    )
    await state.clear()
    await render_welcome_menu(message, owner_id, bot_id)


@dp.callback_query(lambda c: c.data.startswith("welcome_") and c.data.endswith("_reset"))
async def welcome_reset(callback):
    bot_id = callback.data.split("_")[1]
    owner_id = callback.from_user.id

    try:
        await backend_request(
            "POST",
            f"/bots/{bot_id}/welcome",
            telegram_id=owner_id,
            json={
                "text": None,
                "photo_path": None,
                "buttons": None,
                "is_enabled": False
            }
        )
    except Exception:
        await callback.answer("❌ Ошибка сброса")
        return

    text = (
        "🗑 <b>Приветствие сброшено</b>\n\n"
        "Все настройки удалены.\n"
        "Бот больше не отправляет welcome сообщение."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Настроить заново",
                    callback_data=f"bot_{bot_id}_message"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ К боту",
                    callback_data=f"bot_{bot_id}"
                )
            ],
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_delayed"))
async def delayed_menu(callback):
    bot_id = callback.data.split("_")[1]
    owner_id = callback.from_user.id

    await render_delayed_menu(
        callback.message,
        owner_id,
        bot_id,
        edit=True
    )

    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_text"))
async def delayed_text_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(DelayedStates.waiting_text)

    await callback.message.answer("📝 Отправьте текст отложенного сообщения.")
    await callback.answer()


@dp.message(DelayedStates.waiting_text)
async def delayed_text_save(message: Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["bot_id"]
    owner_id = message.from_user.id

    current = await backend_request(
        "GET",
        f"/bots/{bot_id}/delayed",
        telegram_id=owner_id,
    )

    await backend_request(
        "POST",
        f"/bots/{bot_id}/delayed",
        telegram_id=owner_id,
        json={
            "text": message.text,
            "buttons": current.get("buttons"),
            "delay_minutes": current.get("delay_minutes")
        }
    )

    await message.answer(
        "✅ <b>Текст отложенного сообщения обновлён</b>\n\n"
        f"<blockquote>{message.text}</blockquote>",
        parse_mode="HTML"
    )
    await state.clear()
    await render_delayed_menu(message, owner_id, bot_id)


@dp.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_delay"))
async def delayed_delay_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(DelayedStates.waiting_delay)

    await callback.message.answer("⏱ Введите задержку в минутах (например: 10)")
    await callback.answer()


@dp.message(DelayedStates.waiting_delay)
async def delayed_delay_save(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите число.")
        return

    minutes = int(message.text)

    data = await state.get_data()
    bot_id = data["bot_id"]
    owner_id = message.from_user.id

    current = await backend_request(
        "GET",
        f"/bots/{bot_id}/delayed",
        telegram_id=owner_id,
    )

    await backend_request(
        "POST",
        f"/bots/{bot_id}/delayed",
        telegram_id=owner_id,
        json={
            "text": current.get("text"),
            "buttons": current.get("buttons"),
            "delay_minutes": minutes
        }
    )

    await message.answer(
        f"✅ <b>Задержка обновлена</b>\n\n"
        f"Теперь сообщение будет отправляться через <b>{minutes} минут</b> после /start.",
        parse_mode="HTML"
    )
    await state.clear()
    await render_delayed_menu(message, owner_id, bot_id)


@dp.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_photo"))
async def delayed_photo_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(DelayedStates.waiting_photo)

    await callback.message.answer("🖼 Отправьте фото для отложенного сообщения.")
    await callback.answer()


@dp.message(DelayedStates.waiting_photo)
async def delayed_photo_save(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Нужно отправить фото.")
        return

    owner_id = message.from_user.id
    data = await state.get_data()
    bot_id = data["bot_id"]

    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)

    async with httpx.AsyncClient() as client:
        file_response = await client.get(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        )

        if file_response.status_code != 200:
            await message.answer("❌ Не удалось скачать файл из Telegram")
            await state.clear()
            return

        extension = os.path.splitext(file.file_path)[1]

        filename = f"delayed{extension}"

        await client.post(
            f"{BACKEND_URL}/bots/{bot_id}/delayed/photo",
            headers=owner_headers(owner_id, with_api_key=True),
            files={"file": (filename, file_response.content)}
        )

    await message.answer("✅ Фото обновлено.")
    await state.clear()
    await render_delayed_menu(message, owner_id, bot_id)


@dp.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_buttons"))
async def delayed_buttons_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]

    await state.update_data(bot_id=bot_id)
    await state.set_state(DelayedStates.waiting_buttons)

    text = (
        "🔗 <b>Настройка кнопок отложенного сообщения</b>\n\n"
        "Отправьте кнопки в формате:\n\n"
        "Текст кнопки | ссылка\n"
        "Кнопка 1 | https://example.com\n\n"
        "Или напишите <i>удалить</i> чтобы убрать все кнопки"
    )

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@dp.message(DelayedStates.waiting_buttons)
async def delayed_buttons_save(message: Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["bot_id"]
    owner_id = message.from_user.id

    text_input = message.text.strip()

    current = await backend_request(
        "GET",
        f"/bots/{bot_id}/delayed",
        telegram_id=owner_id,
    )

    if text_input.lower() == "удалить":
        await backend_request(
            "POST",
            f"/bots/{bot_id}/delayed",
            telegram_id=owner_id,
            json={
                "text": current.get("text"),
                "buttons": None,
                "delay_minutes": current.get("delay_minutes")
            }
        )

        await message.answer("🗑 Кнопки удалены.")
        await state.clear()
        await render_delayed_menu(message, owner_id, bot_id)
        return

    lines = text_input.split("\n")
    buttons = []

    for line in lines:
        if "|" not in line:
            await message.answer("Неверный формат.")
            return

        text, url = [x.strip() for x in line.split("|", 1)]

        if not url.startswith("http"):
            await message.answer("Ссылка должна начинаться с http")
            return

        buttons.append({
            "text": text,
            "url": url
        })

    await backend_request(
        "POST",
        f"/bots/{bot_id}/delayed",
        telegram_id=owner_id,
        json={
            "text": current.get("text"),
            "buttons": buttons,
            "delay_minutes": current.get("delay_minutes")
        }
    )

    await message.answer(
        f"🔗 <b>Кнопки обновлены</b>\n\n"
        f"Добавлено кнопок: <code>{len(buttons)}</code>",
        parse_mode="HTML"
    )
    await state.clear()
    await render_delayed_menu(message, owner_id, bot_id)


@dp.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_reset"))
async def delayed_reset(callback):
    bot_id = callback.data.split("_")[1]
    owner_id = callback.from_user.id

    try:
        await backend_request(
            "POST",
            f"/bots/{bot_id}/delayed",
            telegram_id=owner_id,
            json={
                "text": None,
                "buttons": None,
                "delay_minutes": None
            }
        )
    except Exception:
        await callback.answer("❌ Ошибка сброса")
        return

    text = (
        "🗑 <b>Отложенное сообщение сброшено</b>\n\n"
        "Все настройки удалены.\n"
        "Бот больше не отправляет это отложенное сообщение."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Настроить заново",
                    callback_data=f"bot_{bot_id}_message"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ К боту",
                    callback_data=f"bot_{bot_id}"
                )
            ],
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_test"))
async def delayed_test(callback):
    bot_id = callback.data.split("_")[1]
    owner_id = callback.from_user.id

    delayed = await backend_request(
        "GET",
        f"/bots/{bot_id}/delayed",
        telegram_id=owner_id,
    )

    text = delayed.get("text")
    buttons = delayed.get("buttons")
    photo_path = delayed.get("photo_path")

    if not text:
        await callback.answer("❌ Сообщение не настроено", show_alert=True)
        return

    reply_markup = None
    if buttons:
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=b["text"], url=b["url"])]
                for b in buttons
            ]
        )

    if photo_path:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{BACKEND_URL}/bots/{bot_id}/delayed/photo",
                headers=owner_headers(owner_id),
            )

            content_type = resp.headers.get("content-type", "")

            if "png" in content_type:
                ext = ".png"
            elif "webp" in content_type:
                ext = ".webp"
            else:
                ext = ".jpg"

            photo_file = BufferedInputFile(
                resp.content,
                filename=f"delayed{ext}"
            )

            await callback.message.answer_photo(
                photo=photo_file,
                caption=text,
                reply_markup=reply_markup
            )
    else:
        await callback.message.answer(
            text,
            reply_markup=reply_markup
        )

    await callback.answer("✅ Тест отправлен")


@dp.callback_query(lambda c: c.data.endswith("_create_broadcast"))
async def broadcast_create_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.clear()

    menu_msg_id = callback.message.message_id

    wizard = await callback.message.answer(
        "📢 <b>Создание рассылки</b>\n\n"
        "📝 Отправьте текст рассылки.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
        ]),
        parse_mode="HTML"
    )

    await state.update_data(
        bot_id=bot_id,
        menu_msg_id=menu_msg_id,
        wizard_msg_id=wizard.message_id,
        edit_mode=False
    )
    await state.set_state(BroadcastStates.waiting_text)
    await callback.answer()


@dp.message(BroadcastStates.waiting_text)
async def broadcast_text_save(message: Message, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]

    if message.text.strip() != "-":
        await state.update_data(text=message.text)

    await state.set_state(BroadcastStates.waiting_buttons)

    await safe_edit_by_id(
        chat_id=message.chat.id,
        message_id=wizard_msg_id,
        text=(
            "🔗 <b>Кнопки рассылки</b>\n\n"
            "Отправьте кнопки в формате:\n"
            "<code>Текст | https://example.com</code>\n\n"
            "Или отправьте <code>-</code> чтобы пропустить"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
        ]),
        parse_mode="HTML"
    )

    await safe_delete_message(message)


@dp.message(BroadcastStates.waiting_buttons)
async def broadcast_buttons_save(message: Message, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]

    text_input = message.text.strip()
    buttons = None

    if text_input != "-":
        lines = [x.strip() for x in text_input.split("\n") if x.strip()]
        parsed = []

        for line in lines:
            if "|" not in line:
                await safe_edit_by_id(
                    message.chat.id, wizard_msg_id,
                    "❌ <b>Неверный формат</b>\n\n"
                    "Используйте:\n<code>Текст | https://example.com</code>",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
                    ]),
                    parse_mode="HTML"
                )
                await safe_delete_message(message)
                return

            left, right = [x.strip() for x in line.split("|", 1)]
            if not left or not right.startswith("http"):
                await safe_edit_by_id(
                    message.chat.id, wizard_msg_id,
                    "❌ <b>Проверьте текст и ссылку</b>\n\n"
                    "Ссылка должна начинаться с <code>http</code>.\n"
                    "Пример:\n<code>Кнопка | https://example.com</code>",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
                    ]),
                    parse_mode="HTML"
                )
                await safe_delete_message(message)
                return

            parsed.append({"text": left, "url": right})

        buttons = parsed

    await state.update_data(buttons=buttons)
    await state.set_state(BroadcastStates.waiting_when)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Сейчас", callback_data="broadcast_when_now")],
            [InlineKeyboardButton(text="⏳ Указать время", callback_data="broadcast_when_time")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")],
        ]
    )

    await safe_edit_by_id(
        chat_id=message.chat.id,
        message_id=wizard_msg_id,
        text="⏳ <b>Время отправки</b>\n\nВыберите действие:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await safe_delete_message(message)


@dp.callback_query(lambda c: c.data == "broadcast_cancel")
async def broadcast_cancel(callback, state: FSMContext):
    data = await state.get_data()

    bot_id = data.get("bot_id")
    menu_msg_id = data.get("menu_msg_id")
    wizard_msg_id = data.get("wizard_msg_id")

    chat_id = callback.message.chat.id
    owner_id = callback.from_user.id

    if wizard_msg_id:
        await safe_delete_by_id(chat_id, wizard_msg_id)

    await state.clear()
    await callback.answer("Создание рассылки отменено.")

    if bot_id and menu_msg_id:
        await render_bot_menu_by_id(chat_id, owner_id, bot_id, menu_msg_id)
    else:
        await safe_edit(callback.message, "Главное меню:", reply_markup=main_menu_keyboard())


@dp.callback_query(lambda c: c.data == "broadcast_when_now")
async def broadcast_when_now(callback, state: FSMContext):
    await state.update_data(scheduled_at=parse_utc3_input_to_utc_iso("сейчас"))
    await state.set_state(BroadcastStates.confirm)
    await broadcast_show_confirm(callback.message, state)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "broadcast_when_time")
async def broadcast_when_time(callback, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]

    await state.set_state(BroadcastStates.waiting_time)

    await safe_edit_by_id(
        chat_id=callback.message.chat.id,
        message_id=wizard_msg_id,
        text=(
            "⏳ <b>Введите время (UTC+3)</b>\n\n"
            "Форматы:\n"
            "• <code>ЧЧ:ММ</code>\n"
            "• <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Пример: <code>19:30</code>"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
        ]),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(BroadcastStates.waiting_time)
async def broadcast_time_input(message: Message, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]

    try:
        scheduled_at = parse_utc3_input_to_utc_iso(message.text)
    except Exception:
        await safe_edit_by_id(
            message.chat.id, wizard_msg_id,
            "❌ <b>Неверный формат времени</b>\n\n"
            "Форматы:\n"
            "• <code>ЧЧ:ММ</code>\n"
            "• <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Пример: <code>19:30</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
            ]),
            parse_mode="HTML"
        )
        await safe_delete_message(message)
        return

    await state.update_data(scheduled_at=scheduled_at)
    await state.set_state(BroadcastStates.confirm)

    await broadcast_show_confirm(message, state)
    await safe_delete_message(message)


@dp.callback_query(lambda c: c.data == "broadcast_confirm")
async def broadcast_confirm(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()

    bot_id = data.get("bot_id")
    text = data.get("text")
    buttons = data.get("buttons")
    scheduled_at = data.get("scheduled_at")

    if not bot_id or not text or not scheduled_at:
        await callback.answer("Данные потерялись", show_alert=True)
        await state.clear()
        return

    try:
        created = await backend_request(
            "POST",
            f"/bots/{bot_id}/broadcasts",
            telegram_id=owner_id,
            json={
                "region": "default",
                "text": text,
                "buttons": buttons,
                "scheduled_at": scheduled_at,
            },
            with_api_key=True,
        )
    except Exception:
        await callback.answer("❌ Ошибка создания", show_alert=True)
        return


    broadcast_id = created.get("id")
    status = created.get("status")

    buttons = []

    if status == "draft":
        buttons.append([
            InlineKeyboardButton(
                text="🧪 Отправить сейчас",
                callback_data=f"broadcast_{bot_id}_sendnow_{broadcast_id}"
            )
        ])

    buttons += [
        [InlineKeyboardButton(text="🗂 Отложенные рассылки", callback_data=f"bot_{bot_id}_scheduled_broadcasts")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")]
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    wizard_msg_id = data.get("wizard_msg_id")

    content = (
        "✅ <b>Рассылка создана</b>\n\n"
        f"🆔 ID: <code>{broadcast_id}</code>\n"
        f"📡 Статус: <b>{status}</b>\n"
        f"⏳ Отправка: <b>{utc_iso_to_utc3_human(scheduled_at)}</b> (UTC+3)\n\n"
    )

    await safe_edit_by_id(
        chat_id=callback.message.chat.id,
        message_id=wizard_msg_id,
        text=content,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await state.clear()
    await callback.answer("✅ Готово")


@dp.callback_query(lambda c: c.data.endswith("_scheduled_broadcasts"))
async def broadcasts_list(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    try:
        broadcasts = await backend_request(
            "GET",
            f"/bots/{bot_id}/broadcasts",
            telegram_id=owner_id,
        )
        bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "❌ Ошибка загрузки рассылок.")
        await callback.answer()
        return

    bot_username = next((b["username"] for b in bots if str(b["id"]) == bot_id), "")

    broadcasts = [
        b for b in broadcasts
        if b.get("status") in ("draft", "scheduled", "sending")
    ]

    broadcasts = sorted(
        broadcasts,
        key=lambda x: x.get("id", 0),
        reverse=True
    )[:15]

    if not broadcasts:
        text = (
            f"📢 <b>Рассылки бота @{bot_username}</b>\n\n"
            "— рассылок нет —"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать рассылку", callback_data=f"bot_{bot_id}_create_broadcast")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")],
        ])
        await safe_edit(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        return

    lines = []
    rows = []
    for br in broadcasts:
        br_id = br.get("id")
        st = br.get("status")
        sch3 = utc_iso_to_utc3_human(br.get("scheduled_at"))

        lines.append(
            f"{status_emoji(st)} <b>#{br_id}</b> — {st} — "
            f"<code>{sch3}</code> — {short_text(br.get('text'))}"
        )
        rows.append([InlineKeyboardButton(
            text=f"{status_emoji(st)} #{br_id} ({st})",
            callback_data=f"broadcast_{bot_id}_open_{br_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать рассылку", callback_data=f"bot_{bot_id}_create_broadcast")],
        *rows,
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")],
    ])

    text = (
        f"📢 <b>Рассылки бота @{bot_username}</b>\n\n" +
        "\n".join(lines)
    )

    await safe_edit(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("broadcast_") and "_open_" in c.data)
async def broadcast_open(callback):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    broadcast_id = int(parts[-1])

    try:
        broadcasts = await backend_request("GET", f"/bots/{bot_id}/broadcasts", telegram_id=owner_id)
        br = next((x for x in broadcasts if int(x.get("id")) == broadcast_id), None)
    except Exception:
        await callback.answer("❌ Ошибка загрузки", show_alert=True)
        return

    if not br:
        await callback.answer("Не найдено", show_alert=True)
        return

    st = br.get("status")
    sch3 = utc_iso_to_utc3_human(br.get("scheduled_at"))

    keyboard_rows = []

    if st in ("draft", "scheduled"):
        keyboard_rows.append([
            InlineKeyboardButton(
                text="✏️ Редактировать",
                callback_data=f"broadcast_{bot_id}_edit_{broadcast_id}"
            )
        ])

    if st == "draft":
        keyboard_rows.append([
            InlineKeyboardButton(
                text="🧪 Отправить сейчас",
                callback_data=f"broadcast_{bot_id}_sendnow_{broadcast_id}"
            )
        ])

    keyboard_rows.append([
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"broadcast_{bot_id}_delete_{broadcast_id}"
        )
    ])

    keyboard_rows.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"bot_{bot_id}_scheduled_broadcasts"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    await safe_edit(
        callback.message,
        "📨 <b>Рассылка</b>\n\n"
        f"🆔 ID: <code>{broadcast_id}</code>\n"
        f"📡 Статус: <b>{st}</b>\n"
        f"⏳ Отправка: <b>{sch3}</b> (UTC+3)\n"
        f"🔗 Кнопки: {buttons_status(br.get('buttons'))}\n\n"
        f"📝 <b>Текст:</b>\n<blockquote>{br.get('text') or ''}</blockquote>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("broadcast_") and "_edit_" in c.data)
async def broadcast_edit_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    broadcast_id = int(parts[-1])

    try:
        broadcasts = await backend_request(
            "GET",
            f"/bots/{bot_id}/broadcasts",
            telegram_id=owner_id,
        )
        br = next((x for x in broadcasts if int(x.get("id")) == broadcast_id), None)
    except Exception:
        await callback.answer("Ошибка загрузки", show_alert=True)
        return

    if not br:
        await callback.answer("Не найдено", show_alert=True)
        return

    await state.clear()

    wizard_msg_id = callback.message.message_id

    await state.update_data(
        bot_id=bot_id,
        broadcast_id=broadcast_id,
        wizard_msg_id=wizard_msg_id,
        edit_mode=True,
        text=br.get("text"),
        buttons=br.get("buttons"),
        scheduled_at=br.get("scheduled_at")
    )

    await state.set_state(BroadcastStates.waiting_text)

    await bot.edit_message_text(
        chat_id=callback.message.chat.id,
        message_id=wizard_msg_id,
        text=(
            "✏️ <b>Редактирование рассылки</b>\n\n"
            "Отправьте новый текст.\n"
            "Или отправьте <code>-</code> чтобы оставить без изменений."
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
        ]),
        parse_mode="HTML"
    )

    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("broadcast_") and "_sendnow_" in c.data)
async def broadcast_send_now(callback):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    broadcast_id = int(parts[-1])

    try:
        await backend_request(
            "POST",
            f"/broadcasts/{broadcast_id}/send-now",
            telegram_id=owner_id,
            with_api_key=True
        )
    except Exception:
        await callback.answer("❌ Ошибка отправки", show_alert=True)
        return

    try:
        broadcasts = await backend_request(
            "GET",
            f"/bots/{bot_id}/broadcasts",
            telegram_id=owner_id,
        )
        br = next((x for x in broadcasts if int(x.get("id")) == broadcast_id), None)
    except Exception:
        await callback.answer("Отправлено, но не удалось обновить экран")
        return

    if not br:
        await callback.answer("Отправлено")
        return

    st = br.get("status")
    sch3 = utc_iso_to_utc3_human(br.get("scheduled_at"))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"broadcast_{bot_id}_open_{broadcast_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}_scheduled_broadcasts")],
    ])

    await safe_edit(
        callback.message,
        "📨 <b>Рассылка</b>\n\n"
        f"🆔 ID: <code>{broadcast_id}</code>\n"
        f"📡 Статус: <b>{st}</b>\n"
        f"⏳ Отправка: <b>{sch3}</b> (UTC+3)\n"
        f"🔗 Кнопки: {buttons_status(br.get('buttons'))}\n\n"
        f"📝 <b>Текст:</b>\n<blockquote>{br.get('text') or ''}</blockquote>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer("✅ Отправлено")


@dp.callback_query(lambda c: c.data.startswith("broadcast_") and "_delete_" in c.data and "_delete_yes_" not in c.data)
async def broadcast_delete_confirm(callback, state: FSMContext):
    parts = callback.data.split("_")
    bot_id = parts[1]
    broadcast_id = int(parts[-1])

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"broadcast_{bot_id}_delete_yes_{broadcast_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"broadcast_{bot_id}_open_{broadcast_id}")],
    ])

    await safe_edit(
        callback.message,
        "🗑 <b>Удалить рассылку?</b>\n\n"
        "Она будет переведена в статус <b>cancelled</b>.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("broadcast_") and "_delete_yes_" in c.data)
async def broadcast_delete_yes(callback):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    broadcast_id = int(parts[-1])

    try:
        await backend_request(
            "PATCH",
            f"/broadcasts/{broadcast_id}/cancel",
            telegram_id=owner_id,
            with_api_key=True
        )
    except Exception:
        await callback.answer("❌ Ошибка удаления", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗂 К списку рассылок", callback_data=f"bot_{bot_id}_scheduled_broadcasts")],
        [InlineKeyboardButton(text="⬅️ К боту", callback_data=f"bot_{bot_id}")],
    ])

    await safe_edit(
        callback.message,
        "🗑 <b>Рассылка удалена</b>\nСтатус: <b>cancelled</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer("✅ Удалено")


@dp.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_rename"))
async def rename_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]
    bot_username = await _get_bot_username(owner_id, bot_id)

    await state.clear()
    await state.set_state(RenameStates.choose_type)
    await state.update_data(bot_id=bot_id)

    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите тип изменения названия:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷 Основное название", callback_data=f"rename_{bot_id}_type_main")],
        [InlineKeyboardButton(text="🌍 Мульти-гео", callback_data=f"rename_{bot_id}_type_geo")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"bot_{bot_id}")],
    ])

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("rename_") and "_type_main" in c.data)
async def rename_main_info(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]
    bot_username = await _get_bot_username(owner_id, bot_id)

    await state.set_state(RenameStates.waiting_new_name)
    await state.update_data(mode="default", selected_regions=None)

    text = (
        f"🏷 <b>Изменение основного названия бота @{bot_username}</b>\n\n"
        f"🤖 Бот: @{bot_username}\n"
        "🌍 Тип: Основное название (для всех пользователей)\n\n"
        "Основное название — это те ключевые слова, по которым люди смогут находить бота в поиске.\n\n"
        "Введите новое название:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад", callback_data=f"bot_{bot_id}_rename")],
        [InlineKeyboardButton(text="« К боту", callback_data=f"bot_{bot_id}")],
    ])

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("rename_") and "_type_geo" in c.data)
async def rename_geo_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]
    bot_username = await _get_bot_username(owner_id, bot_id)

    await state.set_state(RenameStates.choose_regions)
    await state.update_data(mode="multi", selected_regions=[])

    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите регионы для настройки названия или используйте быстрые группы.\n\n"
        f"{_render_selected_regions([])}"
    )

    kb = _regions_keyboard(bot_id, set())
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("rename_") and "_geo_t_" in c.data)
async def rename_geo_toggle(callback, state: FSMContext):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    code = parts[-1]

    data = await state.get_data()
    selected = set(data.get("selected_regions") or [])

    if code in selected:
        selected.remove(code)
    else:
        selected.add(code)

    selected_list = sorted(selected)
    await state.update_data(selected_regions=selected_list)

    bot_username = await _get_bot_username(owner_id, bot_id)

    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите регионы для настройки названия или используйте быстрые группы.\n\n"
        f"{_render_selected_regions(selected_list)}"
    )

    kb = _regions_keyboard(bot_id, selected)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("rename_") and "_geo_group_" in c.data)
async def rename_geo_group(callback, state: FSMContext):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    group = parts[-1]  # cis / west / asia

    group_codes = [x["code"] for x in LANG_REGIONS if x["group"] == group]

    data = await state.get_data()
    selected = set(data.get("selected_regions") or [])

    # toggle group: если все уже выбраны — снять, иначе добавить
    if all(c in selected for c in group_codes):
        for c in group_codes:
            selected.discard(c)
    else:
        for c in group_codes:
            selected.add(c)

    selected_list = sorted(selected)
    await state.update_data(selected_regions=selected_list)

    bot_username = await _get_bot_username(owner_id, bot_id)
    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите регионы для настройки названия или используйте быстрые группы.\n\n"
        f"{_render_selected_regions(selected_list)}"
    )

    kb = _regions_keyboard(bot_id, selected)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("rename_") and c.data.endswith("_geo_all"))
async def rename_geo_all(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    all_codes = sorted([x["code"] for x in LANG_REGIONS])
    await state.update_data(selected_regions=all_codes)

    bot_username = await _get_bot_username(owner_id, bot_id)
    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите регионы для настройки названия или используйте быстрые группы.\n\n"
        f"{_render_selected_regions(all_codes)}"
    )
    kb = _regions_keyboard(bot_id, set(all_codes))
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("rename_") and c.data.endswith("_geo_reset"))
async def rename_geo_reset(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    await state.update_data(selected_regions=[])

    bot_username = await _get_bot_username(owner_id, bot_id)
    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите регионы для настройки названия или используйте быстрые группы.\n\n"
        f"{_render_selected_regions([])}"
    )
    kb = _regions_keyboard(bot_id, set())
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("rename_") and c.data.endswith("_geo_back"))
async def rename_geo_back(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]
    bot_username = await _get_bot_username(owner_id, bot_id)

    await state.clear()
    await state.set_state(RenameStates.choose_type)
    await state.update_data(bot_id=bot_id)

    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите тип изменения названия:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷 Основное название", callback_data=f"rename_{bot_id}_type_main")],
        [InlineKeyboardButton(text="🌍 Мульти-гео", callback_data=f"rename_{bot_id}_type_geo")],
        [InlineKeyboardButton(text="« Назад", callback_data=f"bot_{bot_id}")],
    ])

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("rename_") and c.data.endswith("_geo_done"))
async def rename_geo_done(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    data = await state.get_data()
    selected = data.get("selected_regions") or []
    if not selected:
        await callback.answer("Выберите хотя бы 1 регион", show_alert=True)
        return

    bot_username = await _get_bot_username(owner_id, bot_id)

    regions_lines = "\n".join([f"{REGION_BY_CODE[c]['flag']} {REGION_BY_CODE[c]['title']}" for c in selected if c in REGION_BY_CODE])

    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        f"🤖 Бот: @{bot_username}\n"
        f"🌍 Выбрано регионов: {len(selected)}\n"
        f"{regions_lines}\n\n"
        "Введите новое название, которое будет установлено для выбранных регионов."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"rename_{bot_id}_type_geo")],
        [InlineKeyboardButton(text="« К боту", callback_data=f"bot_{bot_id}")],
    ])

    await state.set_state(RenameStates.waiting_new_name)
    await state.update_data(mode="multi")

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.message(RenameStates.waiting_new_name)
async def rename_save_name(message: Message, state: FSMContext):
    owner_id = message.from_user.id
    data = await state.get_data()
    bot_id = data.get("bot_id")

    if not bot_id:
        await message.answer("❌ Ошибка: bot_id потерялся.")
        await state.clear()
        return

    new_name = (message.text or "").strip()
    if not new_name:
        await message.answer("Введите название текстом.")
        return

    mode = data.get("mode", "default")

    # Берём текущие конфиги, чтобы сохранить description
    try:
        configs = await _get_configs_map(owner_id, bot_id)
    except Exception:
        configs = {}

    default_desc = (configs.get("default") or {}).get("description", "") or ""

    bot_username = await _get_bot_username(owner_id, bot_id)

    # Удалим пользовательское сообщение (как ты делал в wizard рассылке)
    await safe_delete_message(message)

    if mode == "default":
        # upsert default
        try:
            await backend_request(
                "POST",
                f"/bots/{bot_id}/configs",
                telegram_id=owner_id,
                json={"region": "default", "name": new_name, "description": default_desc},
                with_api_key=True,
            )
            # apply default
            await backend_request(
                "POST",
                f"/bots/{bot_id}/configs/apply",
                telegram_id=owner_id,
                json={"region": "default"},
                with_api_key=True,
            )
        except Exception:
            await message.answer("❌ Не удалось обновить название (backend/telegram ошибка).")
            await state.clear()
            return

        text = (
            "✅ <b>Основное название бота обновлено!</b>\n\n"
            f"🤖 Бот: @{bot_username}\n"
            "🌍 Тип: Основное название\n"
            f"🏷 <b>Новое название:</b> {new_name}\n\n"
            "Название будет отображаться для всех пользователей по умолчанию."
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Изменить другой", callback_data=f"bot_{bot_id}_rename")],
            [InlineKeyboardButton(text="« К боту", callback_data=f"bot_{bot_id}")],
        ])

        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        await state.clear()
        return

    # mode == multi
    selected = data.get("selected_regions") or []
    if not selected:
        await message.answer("❌ Регионы не выбраны.")
        await state.clear()
        return

    # Для каждого региона: upsert config + apply
    ok = []
    fail = []

    for code in selected:
        desc = (configs.get(code) or {}).get("description")
        if desc is None:
            desc = default_desc

        try:
            await backend_request(
                "POST",
                f"/bots/{bot_id}/configs",
                telegram_id=owner_id,
                json={"region": code, "name": new_name, "description": desc},
                with_api_key=True,
            )
            await backend_request(
                "POST",
                f"/bots/{bot_id}/configs/apply",
                telegram_id=owner_id,
                json={"region": code},
                with_api_key=True,
            )
            ok.append(code)
        except Exception:
            fail.append(code)

    regions_lines = "\n".join([f"{REGION_BY_CODE[c]['flag']} {REGION_BY_CODE[c]['title']}" for c in selected if c in REGION_BY_CODE])

    if fail:
        failed_lines = "\n".join([f"{REGION_BY_CODE[c]['flag']} {REGION_BY_CODE[c]['title']}" for c in fail if c in REGION_BY_CODE])
        text = (
            "⚠️ <b>Частично обновлено</b>\n\n"
            f"🤖 Бот: @{bot_username}\n"
            f"🌍 Регионов выбрано: {len(selected)}\n\n"
            f"{regions_lines}\n\n"
            f"🏷 <b>Новое название:</b> {new_name}\n\n"
            "❌ Не удалось применить для:\n"
            f"{failed_lines}"
        )
    else:
        text = (
            "✅ <b>Названия бота обновлены!</b>\n\n"
            f"🤖 Бот: @{bot_username}\n"
            "🌍 Регионы:\n"
            f"{regions_lines}\n"
            f"\n🏷 <b>Новое название:</b> {new_name}\n\n"
            "Название будет отображаться для всех выбранных регионов."
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Изменить другой", callback_data=f"bot_{bot_id}_rename")],
        [InlineKeyboardButton(text="« К боту", callback_data=f"bot_{bot_id}")],
    ])

    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.clear()


@dp.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_avatar"))
async def avatar_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]

    await state.update_data(bot_id=bot_id)
    await state.set_state(AvatarStates.waiting_photo)

    await callback.message.answer(
        "🖼 <b>Изменение фото бота</b>\n\n"
        "Отправьте фото которое будет использоваться как аватар бота.",
        parse_mode="HTML"
    )

    await callback.answer()


@dp.message(AvatarStates.waiting_photo)
async def avatar_save(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Отправьте фото.")
        return

    owner_id = message.from_user.id
    data = await state.get_data()
    bot_id = data["bot_id"]

    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)

    async with httpx.AsyncClient() as client:
        file_resp = await client.get(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        )

        if file_resp.status_code != 200:
            await message.answer("❌ Не удалось скачать фото")
            await state.clear()
            return

        try:
            resp = await client.post(
                f"{BACKEND_URL}/bots/{bot_id}/avatar",
                headers=owner_headers(owner_id, with_api_key=True),
                files={
                    "file": (
                        "avatar.png",
                        file_resp.content,
                        "image/png",
                    )
                }
            )

            resp.raise_for_status()

        except Exception as e:
            print("AVATAR ERROR:", e)
            await message.answer("❌ Ошибка обновления фото")
            await state.clear()
            return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки бота",
                    callback_data=f"bot_{bot_id}"
                )
            ]
        ]
    )

    await message.answer(
        "✅ <b>Фото бота обновлено!</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.clear()


if __name__ == "__main__":
    asyncio.run(main())