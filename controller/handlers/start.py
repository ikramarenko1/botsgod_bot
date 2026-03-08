import httpx
from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from controller.config import BACKEND_URL, INTERNAL_API_KEY
from controller.common import backend_request, safe_edit, owner_headers
from controller.utils import parse_utc_iso, UTC3_OFFSET
from controller.keyboards.main import main_reply_keyboard, main_menu_keyboard, BOTS_PER_PAGE, _pagination_row
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


@router.callback_query(lambda c: c.data == "noop")
async def noop_handler(callback):
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("my_bots"))
async def my_bots_handler(callback):
    owner_id = callback.from_user.id

    page = 0
    if callback.data.startswith("my_bots_p"):
        page = int(callback.data[len("my_bots_p"):])

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

    role_icons = {"active": "🟢", "reserve": "🟠", "farm": "🔄", "disabled": "⛔"}

    total_pages = max(1, (len(bots) + BOTS_PER_PAGE - 1) // BOTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_bots = bots[page * BOTS_PER_PAGE : (page + 1) * BOTS_PER_PAGE]

    inline_buttons = []

    for bot_obj in page_bots:
        icon = role_icons.get(bot_obj.get("role"), "")
        label = f"{icon} {bot_obj['username']}" if icon else bot_obj["username"]
        inline_buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"bot_{bot_obj['id']}"
            )
        ])

    if total_pages > 1:
        inline_buttons.append(_pagination_row("my_bots", page, total_pages))

    inline_buttons.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data="back_to_main"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_buttons)

    await safe_edit(
        callback.message,
        f"Ваши боты ({len(bots)}):",
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
        "Чтобы подключить бота, выполните следующие действия:\n\n"
        "1. Перейдите в @BotFather и создайте бота.\n"
        "2. Скопируйте токен (123456:ABCDEF) и отправьте его в этот чат.\n\n"
        "💡 Можно отправить <b>несколько токенов</b> — каждый с новой строки.\n\n"
        "Важно: не подключайте боты, которые уже используются другими сервисами."
    )

    await safe_edit(callback.message, text, parse_mode="HTML")
    await state.set_state(AddBotState.waiting_for_token)
    await callback.answer()


@router.message(AddBotState.waiting_for_token)
async def add_bot_token_handler(message: Message, state: FSMContext):
    lines = [line.strip() for line in message.text.strip().split("\n") if line.strip()]
    tokens = [t for t in lines if ":" in t]

    if not tokens:
        await message.answer("❌ Не найдено ни одного токена. Токен должен содержать ':'.")
        return

    await state.update_data(tokens=tokens)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Активный бот", callback_data="add_role_active")],
            [InlineKeyboardButton(text="🟠 Резервный бот", callback_data="add_role_reserve")],
            [InlineKeyboardButton(text="🔄 Фарм бот", callback_data="add_role_farm")],
        ]
    )

    if len(tokens) > 1:
        count_text = (
            f"✅ Найдено токенов: <b>{len(tokens)}</b>\n\n"
            "Каждый бот будет добавлен с выбранной ролью.\n"
            "Выберите роль:"
        )
    else:
        count_text = "Выберите роль:"

    await message.answer(
        count_text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    await state.set_state(AddBotState.waiting_for_role)


@router.callback_query(AddBotState.waiting_for_role, lambda c: c.data in ("add_role_active", "add_role_reserve", "add_role_farm"))
async def add_bot_role_handler(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()
    tokens = data.get("tokens", [])

    role_map = {
        "add_role_active": "active",
        "add_role_reserve": "reserve",
        "add_role_farm": "farm",
    }
    role = role_map[callback.data]
    role_labels = {"active": "🟢 Активный", "reserve": "🟠 Резервный", "farm": "🔄 Фарм"}
    role_label = role_labels.get(role, role)

    added = []
    failed = []

    for token in tokens:
        try:
            result = await backend_request(
                "POST",
                "/bots/add",
                telegram_id=owner_id,
                json={"token": token, "role": role},
                with_api_key=True,
            )
            added.append(f"@{result.get('username')}")
        except Exception:
            short = token[:15] + "..." if len(token) > 15 else token
            failed.append(short)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Мои боты", callback_data="my_bots")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")],
        ]
    )

    if len(tokens) == 1:
        if added:
            text = f"✅ Бот {added[0]} добавлен\n\nРоль: {role_label}"
        else:
            text = "❌ Неверный токен или бот уже добавлен."
    else:
        header = "⚠️ <b>Результат добавления</b>" if failed else "✅ <b>Боты успешно добавлены</b>"
        lines = [f"{header}\n\nРоль: {role_label}\n"]
        if added:
            lines.append(f"✅ Добавлено: {len(added)}")
            for u in added:
                lines.append(f"  • {u}")
        if failed:
            lines.append(f"\n❌ Ошибки: {len(failed)}")
            for t in failed:
                lines.append(f"  • {t}")
        text = "\n".join(lines)

    await safe_edit(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()
    await state.clear()
