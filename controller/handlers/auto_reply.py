import logging

from aiogram import Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from controller.common import backend_request, safe_edit
from controller.states import AutoReplyStates

logger = logging.getLogger("stagecontrol")

router = Router()


@router.callback_query(lambda c: c.data.endswith("_autoreply"))
async def autoreply_menu(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    try:
        data = await backend_request(
            "GET",
            f"/bots/{bot_id}/auto-reply",
            telegram_id=owner_id,
        )
    except Exception:
        await safe_edit(callback.message, "❌ Ошибка загрузки авто-ответа.")
        await callback.answer()
        return

    current_text = data.get("auto_reply_text")
    status = "🟢 Включён" if current_text else "🔴 Отключён"
    display_text = f"<blockquote>{current_text}</blockquote>" if current_text else "<i>не задан</i>"

    text = (
        f"💬 <b>Авто-ответ</b>\n\n"
        f"📡 Статус: {status}\n\n"
        f"📝 Текст:\n{display_text}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"autoreply_{bot_id}_edit")],
        [InlineKeyboardButton(text="🗑 Сбросить (отключить)", callback_data=f"autoreply_{bot_id}_reset")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")],
    ])

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("autoreply_") and c.data.endswith("_edit"))
async def autoreply_edit_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(AutoReplyStates.waiting_text)

    await callback.message.answer(
        "💬 Отправьте новый текст авто-ответа.\n\n"
        "Этот текст будет отправляться в ответ на <b>любое</b> входящее сообщение.\n"
        "Поддерживается HTML-форматирование.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AutoReplyStates.waiting_text)
async def autoreply_text_save(message, state: FSMContext):
    data = await state.get_data()
    bot_id = data["bot_id"]
    owner_id = message.from_user.id

    try:
        await backend_request(
            "PATCH",
            f"/bots/{bot_id}/auto-reply",
            telegram_id=owner_id,
            json={"text": message.html_text},
        )
    except Exception:
        await message.answer("❌ Ошибка сохранения.")
        await state.clear()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 К авто-ответу", callback_data=f"bot_{bot_id}_autoreply")],
        [InlineKeyboardButton(text="⬅️ К боту", callback_data=f"bot_{bot_id}")],
    ])

    await message.answer(
        f"✅ <b>Авто-ответ обновлён</b>\n\n"
        f"<blockquote>{message.html_text}</blockquote>",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(lambda c: c.data.startswith("autoreply_") and c.data.endswith("_reset"))
async def autoreply_reset(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    try:
        await backend_request(
            "PATCH",
            f"/bots/{bot_id}/auto-reply",
            telegram_id=owner_id,
            json={"text": None},
        )
    except Exception:
        await callback.answer("❌ Ошибка сброса", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 К авто-ответу", callback_data=f"bot_{bot_id}_autoreply")],
        [InlineKeyboardButton(text="⬅️ К боту", callback_data=f"bot_{bot_id}")],
    ])

    await safe_edit(
        callback.message,
        "🗑 <b>Авто-ответ отключён</b>\n\nБот больше не отправляет авто-ответы.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()
