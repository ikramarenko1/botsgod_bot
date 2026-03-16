from aiogram import Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from controller.common import backend_request, safe_edit
from controller.keyboards.main import bots_checkbox_keyboard, main_menu_keyboard
from controller.states import MassKeyStates

router = Router()

PREFIX = "mky"


@router.callback_query(lambda c: c.data == "mass_key")
async def mass_key_start(callback, state: FSMContext):
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
    await state.set_state(MassKeyStates.selecting_bots)

    kb = bots_checkbox_keyboard(PREFIX, bots, set(), back_callback="back_to_main")
    await safe_edit(
        callback.message,
        "🔑 <b>Массовая смена ключа</b>\n\nВыберите ботов:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassKeyStates.selecting_bots, lambda c: c.data.startswith(f"{PREFIX}_page_"))
async def mky_page(callback, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    selected = set(data.get("selected_ids", set()))
    await state.update_data(page=page)
    kb = bots_checkbox_keyboard(PREFIX, data["bots"], selected, page=page)
    await safe_edit(callback.message, f"🔑 <b>Массовая смена ключа</b>\n\nВыбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(MassKeyStates.selecting_bots, lambda c: c.data.startswith(f"{PREFIX}_toggle_"))
async def mky_toggle(callback, state: FSMContext):
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
        f"🔑 <b>Массовая смена ключа</b>\n\nВыбрано: {len(selected)}",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassKeyStates.selecting_bots, lambda c: c.data == f"{PREFIX}_select_all")
async def mky_select_all(callback, state: FSMContext):
    data = await state.get_data()
    selected = {b["id"] for b in data["bots"]}
    page = data.get("page", 0)
    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(PREFIX, data["bots"], selected, page=page)
    await safe_edit(
        callback.message,
        f"🔑 <b>Массовая смена ключа</b>\n\nВыбрано: {len(selected)}",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassKeyStates.selecting_bots, lambda c: c.data == f"{PREFIX}_reset")
async def mky_reset(callback, state: FSMContext):
    data = await state.get_data()
    await state.update_data(selected_ids=set(), page=0)
    kb = bots_checkbox_keyboard(PREFIX, data["bots"], set())
    await safe_edit(
        callback.message,
        "🔑 <b>Массовая смена ключа</b>\n\nВыберите ботов:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassKeyStates.selecting_bots, lambda c: c.data == f"{PREFIX}_done")
async def mky_done_selecting(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()
    selected = data.get("selected_ids", set())

    if not selected:
        await callback.answer("Выберите хотя бы одного бота", show_alert=True)
        return

    try:
        keys = await backend_request("GET", "/keys", telegram_id=owner_id)
    except Exception:
        keys = []

    await state.set_state(MassKeyStates.selecting_key)

    keys_map = {k["id"]: k["short_name"] for k in keys}
    await state.update_data(keys_map=keys_map)

    rows = []
    for key in keys:
        rows.append([InlineKeyboardButton(
            text=f"🔑 {key['short_name']}",
            callback_data=f"mky_key_{key['id']}",
        )])
    rows.append([InlineKeyboardButton(text="🚫 Без ключа", callback_data="mky_key_0")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="mass_key")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)

    await safe_edit(
        callback.message,
        f"Выбрано ботов: <b>{len(selected)}</b>\n\nВыберите ключ:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MassKeyStates.selecting_key, lambda c: c.data.startswith("mky_key_"))
async def mky_apply_key(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()
    selected_ids = list(data.get("selected_ids", []))

    key_id_str = callback.data.split("mky_key_")[1]
    key_id = int(key_id_str)
    key_id_value = key_id if key_id != 0 else None

    bots = data.get("bots", [])
    bots_by_id = {b["id"]: b for b in bots}

    success_bots = []
    failed_bots = []

    for bot_id in selected_ids:
        bot_info = bots_by_id.get(bot_id, {})
        username = bot_info.get("username", str(bot_id))
        try:
            await backend_request(
                "PATCH",
                f"/bots/{bot_id}/key",
                telegram_id=owner_id,
                json={"key_id": key_id_value},
                with_api_key=True,
            )
            success_bots.append(username)
        except Exception:
            failed_bots.append(username)

    keys_map = data.get("keys_map", {})
    key_name = keys_map.get(key_id, str(key_id)) if key_id != 0 else None
    key_label = "🚫 Без ключа" if key_id == 0 else f"🔑 {key_name}"
    lines = [
        f"🔑 <b>Результат смены ключа</b>\n",
        f"Новый ключ: {key_label}\n",
        f"✅ Успешно: {len(success_bots)}",
    ]
    for u in success_bots:
        lines.append(f"  - @{u}")
    if failed_bots:
        lines.append(f"\n❌ Ошибок: {len(failed_bots)}")
        for u in failed_bots:
            lines.append(f"  - @{u}")

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
