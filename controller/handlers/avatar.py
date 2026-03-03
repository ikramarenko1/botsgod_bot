import httpx
from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from controller.config import BACKEND_URL, BOT_TOKEN
from controller.common import owner_headers
from controller.states import AvatarStates

router = Router()


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_avatar"))
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
