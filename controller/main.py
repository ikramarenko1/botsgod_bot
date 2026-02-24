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

from states import AddBotState, WelcomeStates, DelayedStates

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


async def safe_edit(message, text: str, reply_markup=None):
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await message.answer(text, reply_markup=reply_markup)
    except Exception:
        await message.answer(text, reply_markup=reply_markup)


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
    buttons_status = "🟢" if welcome and welcome.get("buttons") else "🔴"

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
        f"🔗 Кнопки: {buttons_status}\n\n"

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
    buttons_status = "🟢" if delayed_buttons else "🔴"
    delay_value = f"{delay_minutes} мин" if delay_minutes else "не установлено"
    enabled_status = "🟢 Активно" if delayed_text and delay_minutes else "🔴 Не активно"

    text = (
        f"⏳ <b>Отложенное сообщение для @{bot_username}</b>\n\n"
        f"📝 <b>Текст:</b>\n{text_block}\n\n"
        f"📸 Фото: {photo_status}\n"
        f"🔗 Кнопки: {buttons_status}\n"
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

    try:
        bots = await backend_request("GET", "/bots", owner_id)
    except Exception:
        await safe_edit(callback.message, "Ошибка загрузки данных бота.")
        await callback.answer()
        return

    bot_username = None
    for b in bots:
        if str(b["id"]) == bot_id:
            bot_username = b["username"]
            break

    if not bot_username:
        await safe_edit(callback.message, "Бот не найден.")
        await callback.answer()
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data=f"bot_{bot_id}_stats")],
            [InlineKeyboardButton(text="📩 Сообщение", callback_data=f"bot_{bot_id}_message")],
            [InlineKeyboardButton(text="⏳ Отложенное сообщение", callback_data=f"bot_{bot_id}_delayed")],
            [InlineKeyboardButton(text="📢 Создать рассылку", callback_data=f"bot_{bot_id}_create_broadcast")],
            [InlineKeyboardButton(text="🗂 Отложенные рассылки", callback_data=f"bot_{bot_id}_scheduled_broadcasts")],
            [InlineKeyboardButton(text="✏ Изменить название", callback_data=f"bot_{bot_id}_rename")],
            [InlineKeyboardButton(text="⛔ Выключить бота", callback_data=f"bot_{bot_id}_disable")],
            [InlineKeyboardButton(text="📦 Выгрузить пользователей", callback_data=f"bot_{bot_id}_export_users")],
            [InlineKeyboardButton(text="🗑 Удалить бота", callback_data=f"bot_{bot_id}_delete")],
            [InlineKeyboardButton(text="« Назад", callback_data="my_bots")]
        ]
    )

    await safe_edit(
        callback.message,
        f"Управление ботом @{bot_username}.",
        reply_markup=keyboard,
    )

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
    buttons_status = "🟢" if welcome and welcome.get("buttons") else "🔴"

    text_block = (
        f"<blockquote>{welcome.get('text')}</blockquote>"
        if welcome and welcome.get("text")
        else "— не задано —"
    )

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
        "Или напишите <i>удалить</i> чтобы убрать все кнопки"
    )

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@dp.message(WelcomeStates.waiting_buttons)
async def welcome_buttons_save(message: Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["bot_id"]
    owner_id = message.from_user.id

    text_input = message.text.strip()

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


@dp.callback_query(lambda c: c.data.endswith("_delayed"))
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

        text, url = [x.strip() for x in line.split("|")]

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


if __name__ == "__main__":
    asyncio.run(main())