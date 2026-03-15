import httpx
from aiogram import Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from controller.config import BACKEND_URL, BOT_TOKEN
from controller.common import owner_headers, backend_request
from controller.states import AvatarStates

router = Router()


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_avatar") and "_avatar_delete" not in c.data)
async def avatar_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]

    await state.update_data(bot_id=bot_id)
    await state.set_state(AvatarStates.waiting_photo)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")],
    ])

    await callback.message.answer(
        "🖼 <b>Изменение фото бота</b>\n\n"
        "Отправьте фото которое будет использоваться как аватар бота.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AvatarStates.waiting_photo)
async def avatar_save(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Отправьте фото.")
        return

    owner_id = message.from_user.id
    data = await state.get_data()
    bot_id = data["bot_id"]

    file_id = message.photo[-1].file_id
    file = await message.bot.get_file(file_id)

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


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_avatar_delete") and "_avatar_delete_confirm" not in c.data)
async def avatar_delete_ask(callback: CallbackQuery):
    bot_id = callback.data.split("_")[1]

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"bot_{bot_id}_avatar_delete_confirm")],
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"bot_{bot_id}")],
    ])

    await callback.message.edit_text(
        "🗑 <b>Удалить фото бота?</b>\n\n"
        "Фото профиля бота будет удалено.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_avatar_delete_confirm"))
async def avatar_delete_confirm(callback: CallbackQuery):
    bot_id = callback.data.split("_")[1]
    owner_id = callback.from_user.id

    try:
        await backend_request(
            "DELETE",
            f"/bots/{bot_id}/avatar",
            telegram_id=owner_id,
            with_api_key=True,
        )
    except Exception:
        await callback.answer("❌ Ошибка удаления фото", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Настройки бота", callback_data=f"bot_{bot_id}")],
    ])

    await callback.message.edit_text(
        "✅ <b>Фото бота удалено!</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


