import os

import httpx
from aiogram import Router
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
)
from aiogram.fsm.context import FSMContext

from controller.config import BACKEND_URL, BOT_TOKEN
from controller.common import backend_request, owner_headers, parse_buttons_input
from controller.render import render_delayed_menu
from controller.states import DelayedStates

router = Router()


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_delayed"))
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


@router.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_text"))
async def delayed_text_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(DelayedStates.waiting_text)

    await callback.message.answer("📝 Отправьте текст отложенного сообщения.")
    await callback.answer()


@router.message(DelayedStates.waiting_text)
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
            "text": message.html_text,
            "buttons": current.get("buttons"),
            "delay_minutes": current.get("delay_minutes")
        }
    )

    await message.answer(
        "✅ <b>Текст отложенного сообщения обновлён</b>\n\n"
        f"<blockquote>{message.html_text}</blockquote>",
        parse_mode="HTML"
    )
    await state.clear()
    await render_delayed_menu(message, owner_id, bot_id)


@router.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_delay"))
async def delayed_delay_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(DelayedStates.waiting_delay)

    await callback.message.answer("⏱ Введите задержку в минутах (например: 10)")
    await callback.answer()


@router.message(DelayedStates.waiting_delay)
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


@router.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_photo"))
async def delayed_photo_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(DelayedStates.waiting_photo)

    await callback.message.answer("🖼 Отправьте фото для отложенного сообщения.")
    await callback.answer()


@router.message(DelayedStates.waiting_photo)
async def delayed_photo_save(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Нужно отправить фото.")
        return

    owner_id = message.from_user.id
    data = await state.get_data()
    bot_id = data["bot_id"]

    file_id = message.photo[-1].file_id
    file = await message.bot.get_file(file_id)

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


@router.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_buttons"))
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


@router.message(DelayedStates.waiting_buttons)
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

    try:
        buttons = parse_buttons_input(text_input)
    except ValueError as e:
        await message.answer(f"❌ {e}")
        return

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


@router.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_reset"))
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
                    callback_data=f"bot_{bot_id}_delayed"
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


@router.callback_query(lambda c: c.data.startswith("delayed_") and c.data.endswith("_test"))
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
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    else:
        await callback.message.answer(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    await callback.answer("✅ Тест отправлен")
