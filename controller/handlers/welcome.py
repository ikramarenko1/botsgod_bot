import os
import logging

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
from controller.render import render_welcome_menu
from controller.states import WelcomeStates

logger = logging.getLogger("stagecontrol")

router = Router()


@router.callback_query(lambda c: c.data.endswith("_message"))
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


@router.callback_query(lambda c: c.data.startswith("welcome_") and c.data.endswith("_text"))
async def welcome_text_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(WelcomeStates.waiting_text)

    await callback.message.answer("📝 Отправьте новый текст приветствия.")
    await callback.answer()


@router.message(WelcomeStates.waiting_text)
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
            "text": message.html_text,
            "photo_path": current.get("photo_path"),
            "buttons": current.get("buttons"),
            "is_enabled": True
        }
    )

    await message.answer(
        "✅ <b>Текст приветствия обновлён</b>\n\n"
        f"<blockquote>{message.html_text}</blockquote>",
        parse_mode="HTML"
    )
    await state.clear()
    await render_welcome_menu(message, owner_id, bot_id)


@router.callback_query(lambda c: c.data.startswith("welcome_") and c.data.endswith("_photo"))
async def welcome_photo_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.update_data(bot_id=bot_id)
    await state.set_state(WelcomeStates.waiting_photo)

    await callback.message.answer("🖼 Отправьте фото которое будет показываться с приветственным сообщением.")
    await callback.answer()


@router.message(WelcomeStates.waiting_photo)
async def welcome_photo_save(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("❌ Нужно отправить фото.")
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


@router.callback_query(lambda c: c.data.startswith("welcome_") and c.data.endswith("_test"))
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
                    parse_mode="HTML",
                )

            elif text:
                await callback.message.answer(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
            else:
                await callback.answer("❌ Сообщение пустое")
                return

        await callback.answer("✅ Тест отправлен")

    except Exception as e:
        logger.error(f"Welcome test error: {e}")
        await callback.answer("❌ Ошибка отправки теста")


@router.callback_query(lambda c: c.data.startswith("welcome_") and c.data.endswith("_buttons"))
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


@router.message(WelcomeStates.waiting_buttons)
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

    try:
        buttons = parse_buttons_input(text_input)
    except ValueError as e:
        await message.answer(f"❌ {e}")
        return

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


@router.callback_query(lambda c: c.data.startswith("welcome_") and c.data.endswith("_reset"))
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
