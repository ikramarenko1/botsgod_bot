from aiogram import Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from controller.common import backend_request, safe_edit
from controller.keyboards.main import bots_checkbox_keyboard, main_menu_keyboard
from controller.states import MassRoleStates

router = Router()

PREFIX = "mrl"


@router.callback_query(lambda c: c.data == "mass_role")
async def mass_role_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    await state.clear()

    try:
        bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "Ошибка получения списка ботов.")
        await callback.answer()
        return

    if not bots:
        await safe_edit(callback.message, "Нет ботов.")
        await callback.answer()
        return

    await state.update_data(bots=bots, selected_ids=set())
    await state.set_state(MassRoleStates.selecting_bots)

    kb = bots_checkbox_keyboard(PREFIX, bots, set(), back_callback="back_to_main")
    await safe_edit(
        callback.message,
        "🔄 <b>Массовая смена роли</b>\n\nВыберите ботов:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassRoleStates.selecting_bots, lambda c: c.data.startswith(f"{PREFIX}_page_"))
async def mrl_page(callback, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    selected = set(data.get("selected_ids", set()))
    await state.update_data(page=page)
    kb = bots_checkbox_keyboard(PREFIX, data["bots"], selected, page=page)
    await safe_edit(callback.message, f"🔄 <b>Массовая смена роли</b>\n\nВыбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(MassRoleStates.selecting_bots, lambda c: c.data.startswith(f"{PREFIX}_toggle_"))
async def mrl_toggle(callback, state: FSMContext):
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
        f"🔄 <b>Массовая смена роли</b>\n\nВыбрано: {len(selected)}",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassRoleStates.selecting_bots, lambda c: c.data == f"{PREFIX}_select_all")
async def mrl_select_all(callback, state: FSMContext):
    data = await state.get_data()
    selected = {b["id"] for b in data["bots"]}
    page = data.get("page", 0)
    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(PREFIX, data["bots"], selected, page=page)
    await safe_edit(
        callback.message,
        f"🔄 <b>Массовая смена роли</b>\n\nВыбрано: {len(selected)}",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassRoleStates.selecting_bots, lambda c: c.data == f"{PREFIX}_reset")
async def mrl_reset(callback, state: FSMContext):
    data = await state.get_data()
    await state.update_data(selected_ids=set(), page=0)
    kb = bots_checkbox_keyboard(PREFIX, data["bots"], set())
    await safe_edit(
        callback.message,
        "🔄 <b>Массовая смена роли</b>\n\nВыберите ботов:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassRoleStates.selecting_bots, lambda c: c.data == f"{PREFIX}_done")
async def mrl_done_selecting(callback, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_ids", set())

    if not selected:
        await callback.answer("Выберите хотя бы одного бота", show_alert=True)
        return

    await state.set_state(MassRoleStates.selecting_role)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Активный", callback_data="mrl_role_active")],
            [InlineKeyboardButton(text="🟠 Резервный", callback_data="mrl_role_reserve")],
            [InlineKeyboardButton(text="🔄 Фарм", callback_data="mrl_role_farm")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="mass_role")],
        ]
    )

    await safe_edit(
        callback.message,
        f"Выбрано ботов: <b>{len(selected)}</b>\n\nВыберите новую роль:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassRoleStates.selecting_role, lambda c: c.data in ("mrl_role_active", "mrl_role_reserve", "mrl_role_farm"))
async def mrl_apply_role(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()
    selected_ids = list(data.get("selected_ids", []))

    role_map = {
        "mrl_role_active": "active",
        "mrl_role_reserve": "reserve",
        "mrl_role_farm": "farm",
    }
    role = role_map[callback.data]
    role_labels = {"active": "🟢 Активный", "reserve": "🟠 Резервный", "farm": "🔄 Фарм"}

    success = 0
    failed = 0

    for bot_id in selected_ids:
        try:
            await backend_request(
                "PATCH",
                f"/bots/{bot_id}/role",
                telegram_id=owner_id,
                json={"role": role},
                with_api_key=True,
            )
            success += 1
        except Exception:
            failed += 1

    lines = [
        f"🔄 <b>Результат смены роли</b>\n",
        f"Новая роль: {role_labels.get(role, role)}\n",
        f"✅ Успешно: {success}",
    ]
    if failed:
        lines.append(f"❌ Ошибок: {failed}")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Мои боты", callback_data="my_bots")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")],
        ]
    )

    await safe_edit(
        callback.message,
        "\n".join(lines),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()
    await state.clear()
