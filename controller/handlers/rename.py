from aiogram import Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from controller.config import LANG_REGIONS, REGION_BY_CODE
from controller.common import (
    backend_request,
    safe_edit,
    safe_delete_message,
    _render_selected_regions,
    _get_bot_username,
    _get_configs_map,
)
from controller.keyboards.main import _regions_keyboard
from controller.states import RenameStates

router = Router()


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_rename"))
async def rename_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    fk_parts = callback.data.split("_fk_")
    bot_id = fk_parts[0].split("_")[1]
    if len(fk_parts) > 1:
        key_id = fk_parts[1].removesuffix("_rename")
        back_to_bot = f"bot_{bot_id}_fk_{key_id}"
    else:
        back_to_bot = f"bot_{bot_id}"

    bot_username = await _get_bot_username(owner_id, bot_id)

    await state.clear()
    await state.set_state(RenameStates.choose_type)
    await state.update_data(bot_id=bot_id, back_to_bot=back_to_bot)

    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите тип изменения названия:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷 Основное название", callback_data=f"rename_{bot_id}_type_main")],
        [InlineKeyboardButton(text="🌍 Мульти-гео", callback_data=f"rename_{bot_id}_type_geo")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_to_bot)],
    ])

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("rename_") and "_type_main" in c.data)
async def rename_main_info(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]
    bot_username = await _get_bot_username(owner_id, bot_id)

    data = await state.get_data()
    back_to_bot = data.get("back_to_bot", f"bot_{bot_id}")
    rename_start_cb = back_to_bot + "_rename"

    await state.set_state(RenameStates.waiting_new_name)
    await state.update_data(mode="default", selected_regions=None)

    text = (
        f"🏷 <b>Изменение основного названия бота @{bot_username}</b>\n\n"
        f"🤖 Бот: @{bot_username}\n"
        "🌍 Тип: Основное название (для всех пользователей)\n\n"
        "Основное название — это те ключевые слова, по которым люди смогут находить бота в поиске.\n\n"
        "Введите новое название:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=rename_start_cb)],
        [InlineKeyboardButton(text="⬅️ К боту", callback_data=back_to_bot)],
    ])

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("rename_") and "_type_geo" in c.data)
async def rename_geo_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]
    bot_username = await _get_bot_username(owner_id, bot_id)

    await state.set_state(RenameStates.choose_regions)
    await state.update_data(mode="multi", selected_regions=[])

    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите регионы для настройки названия или используйте быстрые группы.\n\n"
        f"{_render_selected_regions([])}"
    )

    kb = _regions_keyboard(bot_id, set())
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("rename_") and "_geo_t_" in c.data)
async def rename_geo_toggle(callback, state: FSMContext):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    code = parts[-1]

    data = await state.get_data()
    selected = set(data.get("selected_regions") or [])

    if code in selected:
        selected.remove(code)
    else:
        selected.add(code)

    selected_list = sorted(selected)
    await state.update_data(selected_regions=selected_list)

    bot_username = await _get_bot_username(owner_id, bot_id)

    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите регионы для настройки названия или используйте быстрые группы.\n\n"
        f"{_render_selected_regions(selected_list)}"
    )

    kb = _regions_keyboard(bot_id, selected)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("rename_") and "_geo_group_" in c.data)
async def rename_geo_group(callback, state: FSMContext):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    group = parts[-1]

    group_codes = [x["code"] for x in LANG_REGIONS if x["group"] == group]

    data = await state.get_data()
    selected = set(data.get("selected_regions") or [])

    if all(c in selected for c in group_codes):
        for c in group_codes:
            selected.discard(c)
    else:
        for c in group_codes:
            selected.add(c)

    selected_list = sorted(selected)
    await state.update_data(selected_regions=selected_list)

    bot_username = await _get_bot_username(owner_id, bot_id)
    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите регионы для настройки названия или используйте быстрые группы.\n\n"
        f"{_render_selected_regions(selected_list)}"
    )

    kb = _regions_keyboard(bot_id, selected)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("rename_") and c.data.endswith("_geo_all"))
async def rename_geo_all(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    all_codes = sorted([x["code"] for x in LANG_REGIONS])
    await state.update_data(selected_regions=all_codes)

    bot_username = await _get_bot_username(owner_id, bot_id)
    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите регионы для настройки названия или используйте быстрые группы.\n\n"
        f"{_render_selected_regions(all_codes)}"
    )
    kb = _regions_keyboard(bot_id, set(all_codes))
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("rename_") and c.data.endswith("_geo_reset"))
async def rename_geo_reset(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    await state.update_data(selected_regions=[])

    bot_username = await _get_bot_username(owner_id, bot_id)
    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите регионы для настройки названия или используйте быстрые группы.\n\n"
        f"{_render_selected_regions([])}"
    )
    kb = _regions_keyboard(bot_id, set())
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("rename_") and c.data.endswith("_geo_back"))
async def rename_geo_back(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]
    bot_username = await _get_bot_username(owner_id, bot_id)

    data = await state.get_data()
    back_to_bot = data.get("back_to_bot", f"bot_{bot_id}")

    await state.clear()
    await state.set_state(RenameStates.choose_type)
    await state.update_data(bot_id=bot_id, back_to_bot=back_to_bot)

    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        "Выберите тип изменения названия:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷 Основное название", callback_data=f"rename_{bot_id}_type_main")],
        [InlineKeyboardButton(text="🌍 Мульти-гео", callback_data=f"rename_{bot_id}_type_geo")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_to_bot)],
    ])

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("rename_") and c.data.endswith("_geo_done"))
async def rename_geo_done(callback, state: FSMContext):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    data = await state.get_data()
    selected = data.get("selected_regions") or []
    if not selected:
        await callback.answer("Выберите хотя бы 1 регион", show_alert=True)
        return

    back_to_bot = data.get("back_to_bot", f"bot_{bot_id}")
    bot_username = await _get_bot_username(owner_id, bot_id)

    regions_lines = "\n".join([f"{REGION_BY_CODE[c]['flag']} {REGION_BY_CODE[c]['title']}" for c in selected if c in REGION_BY_CODE])

    text = (
        f"🏷 <b>Изменение названия бота @{bot_username}</b>\n\n"
        f"🤖 Бот: @{bot_username}\n"
        f"🌍 Выбрано регионов: {len(selected)}\n"
        f"{regions_lines}\n\n"
        "Введите новое название, которое будет установлено для выбранных регионов."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"rename_{bot_id}_type_geo")],
        [InlineKeyboardButton(text="⬅️ К боту", callback_data=back_to_bot)],
    ])

    await state.set_state(RenameStates.waiting_new_name)
    await state.update_data(mode="multi")

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.message(RenameStates.waiting_new_name)
async def rename_save_name(message, state: FSMContext):
    owner_id = message.from_user.id
    data = await state.get_data()
    bot_id = data.get("bot_id")

    if not bot_id:
        await message.answer("❌ Ошибка: bot_id потерялся.")
        await state.clear()
        return

    new_name = (message.text or "").strip()
    if not new_name:
        await message.answer("Введите название текстом.")
        return

    mode = data.get("mode", "default")

    try:
        configs = await _get_configs_map(owner_id, bot_id)
    except Exception:
        configs = {}

    default_desc = (configs.get("default") or {}).get("description", "") or ""

    bot_username = await _get_bot_username(owner_id, bot_id)

    await safe_delete_message(message)

    back_to_bot = data.get("back_to_bot", f"bot_{bot_id}")
    rename_start_cb = back_to_bot + "_rename"

    if mode == "default":
        try:
            await backend_request(
                "POST",
                f"/bots/{bot_id}/configs",
                telegram_id=owner_id,
                json={"region": "default", "name": new_name, "description": default_desc},
                with_api_key=True,
            )
            await backend_request(
                "POST",
                f"/bots/{bot_id}/configs/apply",
                telegram_id=owner_id,
                json={"region": "default"},
                with_api_key=True,
            )
        except Exception:
            await message.answer("❌ Не удалось обновить название (backend/telegram ошибка).")
            await state.clear()
            return

        text = (
            "✅ <b>Основное название бота обновлено!</b>\n\n"
            f"🤖 Бот: @{bot_username}\n"
            "🌍 Тип: Основное название\n"
            f"🏷 <b>Новое название:</b> {new_name}\n\n"
            "Название будет отображаться для всех пользователей по умолчанию."
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔁 Изменить другой", callback_data=rename_start_cb)],
            [InlineKeyboardButton(text="⬅️ К боту", callback_data=back_to_bot)],
        ])

        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        await state.clear()
        return

    selected = data.get("selected_regions") or []
    if not selected:
        await message.answer("❌ Регионы не выбраны.")
        await state.clear()
        return

    ok = []
    fail = []

    for code in selected:
        desc = (configs.get(code) or {}).get("description")
        if desc is None:
            desc = default_desc

        try:
            await backend_request(
                "POST",
                f"/bots/{bot_id}/configs",
                telegram_id=owner_id,
                json={"region": code, "name": new_name, "description": desc},
                with_api_key=True,
            )
            await backend_request(
                "POST",
                f"/bots/{bot_id}/configs/apply",
                telegram_id=owner_id,
                json={"region": code},
                with_api_key=True,
            )
            ok.append(code)
        except Exception:
            fail.append(code)

    regions_lines = "\n".join([f"{REGION_BY_CODE[c]['flag']} {REGION_BY_CODE[c]['title']}" for c in selected if c in REGION_BY_CODE])

    if fail:
        failed_lines = "\n".join([f"{REGION_BY_CODE[c]['flag']} {REGION_BY_CODE[c]['title']}" for c in fail if c in REGION_BY_CODE])
        text = (
            "⚠️ <b>Частично обновлено</b>\n\n"
            f"🤖 Бот: @{bot_username}\n"
            f"🌍 Регионов выбрано: {len(selected)}\n\n"
            f"{regions_lines}\n\n"
            f"🏷 <b>Новое название:</b> {new_name}\n\n"
            "❌ Не удалось применить для:\n"
            f"{failed_lines}"
        )
    else:
        text = (
            "✅ <b>Названия бота обновлены!</b>\n\n"
            f"🤖 Бот: @{bot_username}\n"
            "🌍 Регионы:\n"
            f"{regions_lines}\n"
            f"\n🏷 <b>Новое название:</b> {new_name}\n\n"
            "Название будет отображаться для всех выбранных регионов."
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Изменить другой", callback_data=rename_start_cb)],
        [InlineKeyboardButton(text="⬅️ К боту", callback_data=back_to_bot)],
    ])

    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.clear()
