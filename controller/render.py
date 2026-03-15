from typing import Optional

from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from controller.common import backend_request, safe_edit, safe_edit_by_id
from controller.utils import buttons_status, utc_iso_to_utc3_human
from controller.messages import (
    bot_menu_keyboard,
    bot_menu_text,
    welcome_menu_text,
    delayed_menu_text,
    broadcast_confirm_text,
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
    buttons_flag = "🟢" if welcome and welcome.get("buttons") else "🔴"

    text_block = (
        f"<blockquote>{welcome.get('text')}</blockquote>"
        if welcome and welcome.get("text")
        else "— не задано —"
    )

    text = welcome_menu_text(bot_username, text_block, photo_status, buttons_flag)

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

    text = delayed_menu_text(bot_username, text_block, photo_status, buttons_flag, delay_value, enabled_status)

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


async def render_bot_menu(message: Message, owner_id: int, bot_id: str, edit: bool = False, back_callback: str = "my_bots"):
    try:
        bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    except Exception:
        await safe_edit(message, "Ошибка загрузки данных бота.")
        return

    bot_username = next((b["username"] for b in bots if str(b["id"]) == str(bot_id)), None)
    bot_obj = next((b for b in bots if str(b["id"]) == str(bot_id)), None)

    if not bot_obj:
        await safe_edit(message, "Бот не найден.")
        return

    role = bot_obj.get("role", "active")
    key_name = bot_obj.get("key_name")
    has_avatar = bool(bot_obj.get("avatar_path"))
    keyboard = bot_menu_keyboard(bot_id, role, back_callback=back_callback, has_avatar=has_avatar)
    text = bot_menu_text(bot_username, role, key_name=key_name)

    if edit:
        await safe_edit(message, text, reply_markup=keyboard)
    else:
        await message.answer(text, reply_markup=keyboard)


async def render_bot_menu_by_id(bot: Bot, chat_id: int, owner_id: int, bot_id: str, message_id: int, back_callback: str = "my_bots"):
    try:
        bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    except Exception:
        await safe_edit_by_id(bot, chat_id, message_id, "Ошибка загрузки данных бота.")
        return

    bot_username = next((b["username"] for b in bots if str(b["id"]) == str(bot_id)), None)
    bot_obj = next((b for b in bots if str(b["id"]) == str(bot_id)), None)

    if not bot_obj:
        await safe_edit_by_id(bot, chat_id, message_id, "Бот не найден.")
        return

    role = bot_obj.get("role", "active")
    key_name = bot_obj.get("key_name")
    has_avatar = bool(bot_obj.get("avatar_path"))
    keyboard = bot_menu_keyboard(bot_id, role, back_callback=back_callback, has_avatar=has_avatar)

    await safe_edit_by_id(
        bot,
        chat_id=chat_id,
        message_id=message_id,
        text=bot_menu_text(bot_username, role, key_name=key_name),
        reply_markup=keyboard
    )


async def broadcast_show_confirm(bot: Bot, message: Message, state: FSMContext):
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

    content = broadcast_confirm_text(text, buttons_status(buttons), utc_iso_to_utc3_human(scheduled_at))

    if wizard_msg_id:
        await safe_edit_by_id(bot, message.chat.id, wizard_msg_id, content, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(content, reply_markup=kb, parse_mode="HTML")
