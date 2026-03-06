import httpx
from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from controller.config import BACKEND_URL, INTERNAL_API_KEY
from controller.common import backend_request, safe_edit, owner_headers
from controller.utils import parse_utc_iso, UTC3_OFFSET
from controller.keyboards.main import main_reply_keyboard, main_menu_keyboard
from controller.messages import worker_status_text
from controller.states import AddBotState

router = Router()


@router.message(CommandStart())
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


@router.message(lambda message: message.text == "Меню")
async def menu_handler(message: Message):
    await message.answer(
        "Главное меню:",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(lambda c: c.data == "my_bots")
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

    for bot_obj in bots:
        label = bot_obj["username"]
        if bot_obj.get("role") == "reserve":
            label = f"🔄 {label}"
        elif bot_obj.get("role") == "disabled":
            label = f"⛔ {label}"
        inline_buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"bot_{bot_obj['id']}"
            )
        ])

    inline_buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
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


@router.callback_query(lambda c: c.data == "worker_status")
async def worker_status_handler(callback):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BACKEND_URL}/system/worker-status",
                headers={"X-API-KEY": INTERNAL_API_KEY},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        await safe_edit(callback.message, "❌ Ошибка получения статуса Worker.")
        await callback.answer()
        return

    status = data.get("status", "unknown")

    last_hb = data.get("last_heartbeat")
    last_hc = data.get("last_health_check")
    last_rr = data.get("last_replacement_run")

    def fmt(iso_str):
        if not iso_str:
            return "—"
        try:
            dt = parse_utc_iso(iso_str)
            return (dt + UTC3_OFFSET).strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            return str(iso_str)

    text = worker_status_text(status, fmt(last_hb), fmt(last_hc), fmt(last_rr))

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="worker_status")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")],
        ]
    )

    await safe_edit(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_handler(callback):
    await safe_edit(
        callback.message,
        "Главное меню:",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "add_bot")
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


@router.message(AddBotState.waiting_for_token)
async def add_bot_token_handler(message: Message, state: FSMContext):
    token = message.text.strip()

    if ":" not in token:
        await message.answer("❌ Похоже это не токен. Попробуйте снова.")
        return

    await state.update_data(token=token)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Активный бот", callback_data="add_role_active")],
            [InlineKeyboardButton(text="🔄 Резервный бот", callback_data="add_role_reserve")],
        ]
    )

    await message.answer(
        "Выберите роль для бота:",
        reply_markup=keyboard,
    )

    await state.set_state(AddBotState.waiting_for_role)


@router.callback_query(AddBotState.waiting_for_role, lambda c: c.data in ("add_role_active", "add_role_reserve"))
async def add_bot_role_handler(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()
    token = data.get("token")

    role = "active" if callback.data == "add_role_active" else "reserve"

    try:
        result = await backend_request(
            "POST",
            "/bots/add",
            telegram_id=owner_id,
            json={"token": token, "role": role},
            with_api_key=True,
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            await safe_edit(callback.message, "❌ Неверный токен или бот уже добавлен.")
        else:
            await safe_edit(callback.message, "❌ Ошибка сервера.")
        await callback.answer()
        await state.clear()
        return
    except Exception:
        await safe_edit(callback.message, "❌ Ошибка подключения к backend.")
        await callback.answer()
        await state.clear()
        return

    username = result.get("username")
    role_label = "активный" if role == "active" else "резервный"

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Мои боты", callback_data="my_bots")]
        ]
    )

    await safe_edit(
        callback.message,
        f"✅ Бот @{username} добавлен как {role_label}.",
        reply_markup=keyboard,
    )

    await callback.answer()
    await state.clear()
