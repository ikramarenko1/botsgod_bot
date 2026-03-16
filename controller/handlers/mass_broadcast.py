from aiogram import Router
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)
from aiogram.fsm.context import FSMContext

from controller.common import backend_request, safe_edit, safe_edit_by_id, safe_delete_message
from controller.keyboards.main import bots_checkbox_keyboard, main_menu_keyboard
from controller.utils import parse_utc3_input_to_utc_iso, utc_iso_to_utc3_human, buttons_status
from controller.messages import broadcast_confirm_text
from controller.states import MassBroadcastStates

router = Router()

PREFIX = "mbc"


@router.callback_query(lambda c: c.data == "mass_broadcast")
async def mass_broadcast_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    await state.clear()

    try:
        bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "Ошибка получения списка ботов.")
        await callback.answer()
        return

    active_bots = [b for b in bots if b.get("role") in ("active", "farm")]

    if not active_bots:
        await safe_edit(callback.message, "Нет активных ботов для рассылки.")
        await callback.answer()
        return

    await state.update_data(
        bots=active_bots,
        selected_ids=set(),
        menu_msg_id=callback.message.message_id,
    )
    await state.set_state(MassBroadcastStates.selecting_bots)

    kb = bots_checkbox_keyboard(PREFIX, active_bots, set())
    await safe_edit(
        callback.message,
        "📢 <b>Массовая рассылка</b>\n\nВыберите ботов:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassBroadcastStates.selecting_bots, lambda c: c.data.startswith(f"{PREFIX}_page_"))
async def mbc_page(callback, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    selected = set(data.get("selected_ids", set()))
    await state.update_data(page=page)
    kb = bots_checkbox_keyboard(PREFIX, data["bots"], selected, page=page)
    await safe_edit(callback.message, f"📢 <b>Массовая рассылка</b>\n\nВыбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(MassBroadcastStates.selecting_bots, lambda c: c.data.startswith(f"{PREFIX}_toggle_"))
async def mbc_toggle(callback, state: FSMContext):
    bot_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    selected = set(data.get("selected_ids", set()))
    page = data.get("page", 0)

    if bot_id in selected:
        selected.discard(bot_id)
    else:
        selected.add(bot_id)

    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(PREFIX, data["bots"], selected, page=page)
    await safe_edit(
        callback.message,
        f"📢 <b>Массовая рассылка</b>\n\nВыбрано: {len(selected)}",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassBroadcastStates.selecting_bots, lambda c: c.data == f"{PREFIX}_select_all")
async def mbc_select_all(callback, state: FSMContext):
    data = await state.get_data()
    selected = {b["id"] for b in data["bots"]}
    page = data.get("page", 0)
    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(PREFIX, data["bots"], selected, page=page)
    await safe_edit(
        callback.message,
        f"📢 <b>Массовая рассылка</b>\n\nВыбрано: {len(selected)}",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassBroadcastStates.selecting_bots, lambda c: c.data == f"{PREFIX}_reset")
async def mbc_reset(callback, state: FSMContext):
    data = await state.get_data()
    await state.update_data(selected_ids=set(), page=0)
    kb = bots_checkbox_keyboard(PREFIX, data["bots"], set())
    await safe_edit(
        callback.message,
        "📢 <b>Массовая рассылка</b>\n\nВыберите ботов:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassBroadcastStates.selecting_bots, lambda c: c.data == f"{PREFIX}_done")
async def mbc_done_selecting(callback, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_ids", set())

    if not selected:
        await callback.answer("Выберите хотя бы одного бота", show_alert=True)
        return

    wizard = await callback.message.answer(
        "📝 <b>Текст рассылки</b>\n\nОтправьте текст сообщения.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mass_broadcast")]
        ]),
        parse_mode="HTML",
    )
    await state.update_data(wizard_msg_id=wizard.message_id)
    await state.set_state(MassBroadcastStates.waiting_text)
    await callback.answer()


@router.message(MassBroadcastStates.waiting_text)
async def mbc_text_save(message: Message, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]

    await state.update_data(text=message.html_text)
    await state.set_state(MassBroadcastStates.waiting_buttons)

    await safe_edit_by_id(
        message.bot,
        chat_id=message.chat.id,
        message_id=wizard_msg_id,
        text=(
            "🔗 <b>Кнопки рассылки</b>\n\n"
            "Отправьте кнопки в формате:\n"
            "<code>Текст | https://example.com</code>\n\n"
            "Или отправьте <code>-</code> чтобы пропустить"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mass_broadcast")]
        ]),
        parse_mode="HTML",
    )
    await safe_delete_message(message)


@router.message(MassBroadcastStates.waiting_buttons)
async def mbc_buttons_save(message: Message, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]

    text_input = message.text.strip()
    buttons = None

    if text_input != "-":
        lines = [x.strip() for x in text_input.split("\n") if x.strip()]
        parsed = []
        for line in lines:
            if "|" not in line:
                await safe_delete_message(message)
                return
            left, right = [x.strip() for x in line.split("|", 1)]
            if not left or not right.startswith("http"):
                await safe_delete_message(message)
                return
            parsed.append({"text": left, "url": right})
        buttons = parsed

    await state.update_data(buttons=buttons)
    await state.set_state(MassBroadcastStates.waiting_when)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Сейчас", callback_data="mbc_when_now")],
            [InlineKeyboardButton(text="⏳ Указать время", callback_data="mbc_when_time")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mass_broadcast")],
        ]
    )

    await safe_edit_by_id(
        message.bot,
        chat_id=message.chat.id,
        message_id=wizard_msg_id,
        text="⏳ <b>Время отправки</b>\n\nВыберите действие:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await safe_delete_message(message)


@router.callback_query(lambda c: c.data == "mbc_when_now")
async def mbc_when_now(callback, state: FSMContext):
    await state.update_data(scheduled_at=parse_utc3_input_to_utc_iso("сейчас"))
    await state.set_state(MassBroadcastStates.confirm)
    await _show_mbc_confirm(callback, state)
    await callback.answer()


@router.callback_query(lambda c: c.data == "mbc_when_time")
async def mbc_when_time(callback, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]
    await state.set_state(MassBroadcastStates.waiting_time)

    await safe_edit_by_id(
        callback.bot,
        chat_id=callback.message.chat.id,
        message_id=wizard_msg_id,
        text=(
            "⏳ <b>Введите время (UTC+3)</b>\n\n"
            "Форматы:\n"
            "- <code>ЧЧ:ММ</code>\n"
            "- <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mass_broadcast")]
        ]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(MassBroadcastStates.waiting_time)
async def mbc_time_input(message: Message, state: FSMContext):
    try:
        scheduled_at = parse_utc3_input_to_utc_iso(message.text)
    except Exception:
        await safe_delete_message(message)
        return

    await state.update_data(scheduled_at=scheduled_at)
    await state.set_state(MassBroadcastStates.confirm)
    await _show_mbc_confirm_msg(message, state)
    await safe_delete_message(message)


async def _show_mbc_confirm(callback, state: FSMContext):
    data = await state.get_data()
    text = data.get("text", "")
    buttons = data.get("buttons")
    scheduled_at = data.get("scheduled_at")
    wizard_msg_id = data.get("wizard_msg_id")
    selected = data.get("selected_ids", set())

    content = (
        f"📢 <b>Массовая рассылка — подтверждение</b>\n\n"
        f"🤖 Ботов: <b>{len(selected)}</b>\n"
        f"📝 <b>Текст:</b>\n<blockquote>{text}</blockquote>\n\n"
        f"🔗 Кнопки: {buttons_status(buttons)}\n"
        f"⏳ Отправка: <b>{utc_iso_to_utc3_human(scheduled_at)}</b> (UTC+3)"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать", callback_data="mbc_confirm")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mass_broadcast")],
        ]
    )

    await safe_edit_by_id(callback.bot, callback.message.chat.id, wizard_msg_id, content, reply_markup=kb, parse_mode="HTML")


async def _show_mbc_confirm_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("text", "")
    buttons = data.get("buttons")
    scheduled_at = data.get("scheduled_at")
    wizard_msg_id = data.get("wizard_msg_id")
    selected = data.get("selected_ids", set())

    content = (
        f"📢 <b>Массовая рассылка — подтверждение</b>\n\n"
        f"🤖 Ботов: <b>{len(selected)}</b>\n"
        f"📝 <b>Текст:</b>\n<blockquote>{text}</blockquote>\n\n"
        f"🔗 Кнопки: {buttons_status(buttons)}\n"
        f"⏳ Отправка: <b>{utc_iso_to_utc3_human(scheduled_at)}</b> (UTC+3)"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать", callback_data="mbc_confirm")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mass_broadcast")],
        ]
    )

    await safe_edit_by_id(message.bot, message.chat.id, wizard_msg_id, content, reply_markup=kb, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "mbc_confirm")
async def mbc_confirm(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()

    text = data.get("text")
    buttons = data.get("buttons")
    scheduled_at = data.get("scheduled_at")
    selected_ids = list(data.get("selected_ids", []))
    wizard_msg_id = data.get("wizard_msg_id")

    if not selected_ids or not text or not scheduled_at:
        await callback.answer("Данные потерялись", show_alert=True)
        await state.clear()
        return

    first_bot_id = selected_ids[0]

    try:
        created = await backend_request(
            "POST",
            f"/bots/{first_bot_id}/broadcasts",
            telegram_id=owner_id,
            json={
                "region": "default",
                "text": text,
                "buttons": buttons,
                "scheduled_at": scheduled_at,
                "bot_ids": selected_ids,
            },
            with_api_key=True,
        )
    except Exception:
        await callback.answer("Ошибка создания рассылки", show_alert=True)
        return

    broadcast_id = created.get("id")
    status = created.get("status")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_to_main")],
        ]
    )

    content = (
        f"✅ <b>Массовая рассылка создана</b>\n\n"
        f"🆔 ID: <code>{broadcast_id}</code>\n"
        f"📡 Статус: <b>{status}</b>\n"
        f"🤖 Ботов: <b>{len(selected_ids)}</b>\n"
        f"⏳ Отправка: <b>{utc_iso_to_utc3_human(scheduled_at)}</b> (UTC+3)"
    )

    await safe_edit_by_id(
        callback.bot,
        chat_id=callback.message.chat.id,
        message_id=wizard_msg_id,
        text=content,
        reply_markup=kb,
        parse_mode="HTML",
    )

    await state.clear()
    await callback.answer("✅ Готово")
