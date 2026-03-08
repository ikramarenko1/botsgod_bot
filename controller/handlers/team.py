from aiogram import Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from controller.common import backend_request, safe_edit
from controller.states import TeamStates

router = Router()


def _team_keyboard(members: list, created_by: int) -> InlineKeyboardMarkup:
    rows = []
    for m in members:
        tid = m["telegram_id"]
        if tid == created_by:
            continue
        rows.append([
            InlineKeyboardButton(
                text=f"❌ Удалить {tid}",
                callback_data=f"team_remove_{tid}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="➕ Добавить соадминистратора", callback_data="team_add_member"),
    ])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _team_text(team_data: dict) -> str:
    team = team_data["team"]
    members = team_data["members"]
    lines = ["👥 <b>Моя команда</b>\n", "Участники:"]
    for i, m in enumerate(members, 1):
        prefix = "👑" if m["is_creator"] else "👤"
        creator_tag = " (создатель)" if m["is_creator"] else ""
        lines.append(f"{i}. {prefix} <code>{m['telegram_id']}</code>{creator_tag}")
    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "my_team")
async def my_team_handler(callback):
    owner_id = callback.from_user.id
    try:
        data = await backend_request("GET", "/team", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "❌ Ошибка получения данных команды.")
        await callback.answer()
        return

    text = _team_text(data)
    keyboard = _team_keyboard(data["members"], data["team"]["created_by"])
    await safe_edit(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data == "team_add_member")
async def team_add_member_start(callback, state: FSMContext):
    await safe_edit(
        callback.message,
        "Введите Telegram ID пользователя, которого хотите добавить в команду:",
    )
    await state.set_state(TeamStates.waiting_member_id)
    await callback.answer()


@router.message(TeamStates.waiting_member_id)
async def team_add_member_input(message, state: FSMContext):
    owner_id = message.from_user.id
    text = message.text.strip()

    if not text.isdigit():
        await message.answer("❌ Введите числовой Telegram ID.")
        return

    new_member_id = int(text)

    try:
        await backend_request(
            "POST",
            "/team/members",
            telegram_id=owner_id,
            json={"telegram_id": new_member_id},
        )
    except Exception as e:
        error_text = str(e)
        if "400" in error_text:
            await message.answer("❌ Пользователь уже состоит в команде.")
        else:
            await message.answer("❌ Ошибка при добавлении участника.")
        await state.clear()
        return

    await state.clear()

    try:
        data = await backend_request("GET", "/team", telegram_id=owner_id)
        text = _team_text(data)
        keyboard = _team_keyboard(data["members"], data["team"]["created_by"])
        await message.answer(
            f"✅ Участник <code>{new_member_id}</code> добавлен!\n\n{text}",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        await message.answer(f"✅ Участник <code>{new_member_id}</code> добавлен!", parse_mode="HTML")


@router.callback_query(lambda c: c.data.startswith("team_remove_"))
async def team_remove_member(callback):
    owner_id = callback.from_user.id
    tid = int(callback.data.split("team_remove_")[1])

    try:
        await backend_request(
            "DELETE",
            f"/team/members/{tid}",
            telegram_id=owner_id,
        )
    except Exception:
        await callback.answer("❌ Ошибка при удалении", show_alert=True)
        return

    try:
        data = await backend_request("GET", "/team", telegram_id=owner_id)
        text = _team_text(data)
        keyboard = _team_keyboard(data["members"], data["team"]["created_by"])
        await safe_edit(
            callback.message,
            f"✅ Участник удалён.\n\n{text}",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except Exception:
        await safe_edit(callback.message, "✅ Участник удалён.")

    await callback.answer()
