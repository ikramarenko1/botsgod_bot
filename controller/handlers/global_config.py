import httpx
from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from controller.config import BACKEND_URL, BOT_TOKEN
from controller.common import backend_request, safe_edit, owner_headers, parse_buttons_input
from controller.keyboards.main import gc_region_picker_keyboard
from controller.config import REGION_BY_CODE
from controller.states import GlobalConfigStates

router = Router()


@router.callback_query(lambda c: c.data == "global_configs")
async def gc_list(callback, state: FSMContext):
    await state.clear()
    owner_id = callback.from_user.id
    try:
        configs = await backend_request("GET", "/global-configs", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "❌ Ошибка загрузки конфигов.")
        await callback.answer()
        return

    rows = []
    for c in configs:
        icon = "🟢" if c["is_active"] else "⚪"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {c['name']}",
            callback_data=f"gc_{c['id']}"
        )])

    if len(configs) < 5:
        rows.append([InlineKeyboardButton(text="➕ Создать конфиг", callback_data="gc_create")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    text = "⚙️ <b>Глобальные конфиги</b>\n\n"
    if not configs:
        text += "— конфигов нет —"
    else:
        text += f"Конфигов: {len(configs)}/5\n🟢 = активный"

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data == "gc_create")
async def gc_create_start(callback, state: FSMContext):
    await state.set_state(GlobalConfigStates.waiting_name)
    await safe_edit(
        callback.message,
        "⚙️ <b>Создание конфига</b>\n\nОтправьте название:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(GlobalConfigStates.waiting_name)
async def gc_create_name(message: Message, state: FSMContext):
    owner_id = message.from_user.id
    name = message.text.strip()[:100]

    try:
        result = await backend_request(
            "POST", "/global-configs",
            telegram_id=owner_id,
            json={"name": name},
        )
    except Exception:
        await message.answer("❌ Ошибка создания конфига.")
        await state.clear()
        return

    config_id = result["id"]
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Настроить", callback_data=f"gc_{config_id}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="global_configs")],
    ])

    await message.answer(
        f"✅ Конфиг <b>{name}</b> создан.",
        reply_markup=kb, parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data.startswith("gc_") and c.data[3:].isdigit())
async def gc_detail(callback, state: FSMContext):
    await state.clear()
    config_id = callback.data.split("_")[1]
    await _render_gc_detail(callback, config_id)


async def _render_gc_detail(callback, config_id: str):
    owner_id = callback.from_user.id

    try:
        config = await backend_request("GET", f"/global-configs/{config_id}", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "Конфиг не найден.")
        await callback.answer()
        return

    status_icon = "🟢 Активен" if config["is_active"] else "⚪ Неактивен"
    welcome_status = "🟢" if config.get("welcome_text") else "🔴"
    avatar_status = "🟢" if config.get("avatar_path") else "🔴"
    auto_reply_status = "🟢" if config.get("auto_reply_text") else "🔴"
    buttons_flag = "🟢" if config.get("welcome_buttons") else "🔴"
    regions_count = len(config.get("regions", []))

    text = (
        f"⚙️ <b>Конфиг: {config['name']}</b>\n\n"
        f"📡 Статус: {status_icon}\n\n"
        f"🖼 Аватар: {avatar_status}\n"
        f"📩 Приветствие: {welcome_status}\n"
        f"🔗 Кнопки: {buttons_flag}\n"
        f"💬 Авто-ответ: {auto_reply_status}\n"
        f"🌍 Регионы: {regions_count}\n"
    )

    rows = [
        [
            InlineKeyboardButton(text="🖼 Аватар", callback_data=f"gc_{config_id}_avatar"),
            InlineKeyboardButton(text="📩 Приветствие", callback_data=f"gc_{config_id}_welcome"),
        ],
        [
            InlineKeyboardButton(text="🔗 Кнопки", callback_data=f"gc_{config_id}_buttons"),
            InlineKeyboardButton(text="💬 Авто-ответ", callback_data=f"gc_{config_id}_autoreply"),
        ],
        [InlineKeyboardButton(text="🌍 Регионы", callback_data=f"gc_{config_id}_regions")],
    ]

    if config["is_active"]:
        rows.append([InlineKeyboardButton(text="⏸ Деактивировать", callback_data=f"gc_{config_id}_deactivate")])
        rows.append([InlineKeyboardButton(text="🔄 Обновить на ботах", callback_data=f"gc_{config_id}_reapply")])
    else:
        rows.append([InlineKeyboardButton(text="▶️ Активировать", callback_data=f"gc_{config_id}_activate")])

    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"gc_{config_id}_delete")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="global_configs")])

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# --- Welcome text ---
@router.callback_query(lambda c: c.data.endswith("_welcome") and c.data.startswith("gc_"))
async def gc_edit_welcome(callback, state: FSMContext):
    config_id = callback.data.split("_")[1]
    owner_id = callback.from_user.id

    # Загрузить текущий текст
    current_text = None
    try:
        config = await backend_request("GET", f"/global-configs/{config_id}", telegram_id=owner_id)
        current_text = config.get("welcome_text")
    except Exception:
        pass

    await state.update_data(gc_id=config_id)
    await state.set_state(GlobalConfigStates.editing_welcome_text)

    display = f"<blockquote>{current_text}</blockquote>" if current_text else "<i>не задан</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gc_{config_id}")],
    ])

    await safe_edit(
        callback.message,
        f"📩 <b>Приветствие</b>\n\n📝 Текущий текст:\n{display}\n\n"
        "Отправьте новый текст приветственного сообщения.\n"
        "Поддерживается HTML-форматирование.",
        reply_markup=kb, parse_mode="HTML",
    )
    await callback.answer()


@router.message(GlobalConfigStates.editing_welcome_text)
async def gc_welcome_text_save(message: Message, state: FSMContext):
    owner_id = message.from_user.id
    data = await state.get_data()
    config_id = data["gc_id"]

    try:
        await backend_request(
            "PATCH", f"/global-configs/{config_id}",
            telegram_id=owner_id,
            json={"welcome_text": message.html_text},
        )
    except Exception:
        await message.answer("❌ Ошибка сохранения.")
        await state.clear()
        return

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ К конфигу", callback_data=f"gc_{config_id}")],
    ])
    await message.answer("✅ Приветствие обновлено.", reply_markup=kb)


# --- Buttons ---
@router.callback_query(lambda c: c.data.endswith("_buttons") and c.data.startswith("gc_"))
async def gc_edit_buttons(callback, state: FSMContext):
    config_id = callback.data.split("_")[1]
    await state.update_data(gc_id=config_id)
    await state.set_state(GlobalConfigStates.editing_welcome_buttons)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gc_{config_id}")],
    ])

    await safe_edit(
        callback.message,
        "🔗 <b>Кнопки приветствия</b>\n\n"
        "Отправьте кнопки в формате:\n"
        "<code>Текст | https://example.com</code>\n\n"
        "Или отправьте <code>-</code> чтобы убрать кнопки",
        reply_markup=kb, parse_mode="HTML",
    )
    await callback.answer()


@router.message(GlobalConfigStates.editing_welcome_buttons)
async def gc_buttons_save(message: Message, state: FSMContext):
    owner_id = message.from_user.id
    data = await state.get_data()
    config_id = data["gc_id"]

    text_input = message.text.strip()
    buttons = None

    if text_input != "-":
        try:
            buttons = parse_buttons_input(text_input)
        except ValueError:
            await message.answer("❌ Неверный формат кнопок.")
            return

    try:
        await backend_request(
            "PATCH", f"/global-configs/{config_id}",
            telegram_id=owner_id,
            json={"welcome_buttons": buttons},
        )
    except Exception:
        await message.answer("❌ Ошибка сохранения.")
        await state.clear()
        return

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ К конфигу", callback_data=f"gc_{config_id}")],
    ])
    await message.answer("✅ Кнопки обновлены.", reply_markup=kb)


# --- Auto-reply ---
@router.callback_query(lambda c: c.data.endswith("_autoreply") and c.data.startswith("gc_"))
async def gc_edit_autoreply(callback, state: FSMContext):
    config_id = callback.data.split("_")[1]
    owner_id = callback.from_user.id

    # Загрузить текущий текст
    current_text = None
    try:
        config = await backend_request("GET", f"/global-configs/{config_id}", telegram_id=owner_id)
        current_text = config.get("auto_reply_text")
    except Exception:
        pass

    await state.update_data(gc_id=config_id)
    await state.set_state(GlobalConfigStates.editing_auto_reply)

    display = f"<blockquote>{current_text}</blockquote>" if current_text else "<i>не задан</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gc_{config_id}")],
    ])

    await safe_edit(
        callback.message,
        f"💬 <b>Авто-ответ</b>\n\n📝 Текущий текст:\n{display}\n\n"
        "Отправьте новый текст авто-ответа.",
        reply_markup=kb, parse_mode="HTML",
    )
    await callback.answer()


@router.message(GlobalConfigStates.editing_auto_reply)
async def gc_autoreply_save(message: Message, state: FSMContext):
    owner_id = message.from_user.id
    data = await state.get_data()
    config_id = data["gc_id"]

    try:
        await backend_request(
            "PATCH", f"/global-configs/{config_id}",
            telegram_id=owner_id,
            json={"auto_reply_text": message.html_text},
        )
    except Exception:
        await message.answer("❌ Ошибка сохранения.")
        await state.clear()
        return

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ К конфигу", callback_data=f"gc_{config_id}")],
    ])
    await message.answer("✅ Авто-ответ обновлён.", reply_markup=kb)


# --- Avatar ---
@router.callback_query(lambda c: c.data.endswith("_avatar") and c.data.startswith("gc_"))
async def gc_edit_avatar(callback, state: FSMContext):
    config_id = callback.data.split("_")[1]
    await state.update_data(gc_id=config_id)
    await state.set_state(GlobalConfigStates.editing_avatar)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gc_{config_id}")],
    ])

    await safe_edit(
        callback.message,
        "🖼 <b>Аватар конфига</b>\n\nОтправьте фото для аватара ботов.",
        reply_markup=kb, parse_mode="HTML",
    )
    await callback.answer()


@router.message(GlobalConfigStates.editing_avatar)
async def gc_avatar_save(message: Message, state: FSMContext):
    if not message.photo:
        await message.answer("Отправьте фото.")
        return

    owner_id = message.from_user.id
    data = await state.get_data()
    config_id = data["gc_id"]

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
                f"{BACKEND_URL}/global-configs/{config_id}/avatar",
                headers=owner_headers(owner_id),
                files={"file": ("avatar.jpg", file_resp.content, "image/jpeg")},
            )
            resp.raise_for_status()
        except Exception:
            await message.answer("❌ Ошибка загрузки аватара")
            await state.clear()
            return

    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ К конфигу", callback_data=f"gc_{config_id}")],
    ])
    await message.answer("✅ Аватар обновлён.", reply_markup=kb)


# --- Activate / Deactivate ---
@router.callback_query(lambda c: "_activate" in c.data and c.data.startswith("gc_") and "deactivate" not in c.data)
async def gc_activate(callback, state: FSMContext):
    await state.clear()
    owner_id = callback.from_user.id
    config_id = callback.data.split("_")[1]

    try:
        result = await backend_request(
            "POST", f"/global-configs/{config_id}/activate",
            telegram_id=owner_id,
            with_api_key=True,
        )
    except Exception:
        await callback.answer("❌ Ошибка активации", show_alert=True)
        return

    skipped = result.get("skipped_bots", {})
    applied = result.get("applied", 0)
    applied_bots = result.get("applied_bots", [])
    api_errors = result.get("api_errors", {})

    text = f"✅ Конфиг активирован.\n\n🤖 Применён к {applied} ботам:"

    if applied_bots:
        for ab in applied_bots:
            key_part = f" [{ab['key_name']}]" if ab.get("key_name") else ""
            text += f"\n  🟢 @{ab['username']}{key_part}"

    if skipped:
        text += "\n\n⚠️ <b>Пропущены поля:</b>\n"
        for username, fields in skipped.items():
            text += f"  @{username}: {', '.join(fields)}\n"
        text += "\n<i>Сбросить индивидуальный конфиг можно в настройках бота.</i>"

    if api_errors:
        text += "\n\n⚠️ <b>Ошибки API:</b>\n"
        for username, errors in api_errors.items():
            for err in errors:
                text += f"  @{username}: {err}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ К конфигу", callback_data=f"gc_{config_id}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="global_configs")],
    ])

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: "_deactivate" in c.data and c.data.startswith("gc_"))
async def gc_deactivate(callback, state: FSMContext):
    await state.clear()
    owner_id = callback.from_user.id
    config_id = callback.data.split("_")[1]

    try:
        await backend_request(
            "POST", f"/global-configs/{config_id}/deactivate",
            telegram_id=owner_id,
        )
    except Exception:
        await callback.answer("❌ Ошибка деактивации", show_alert=True)
        return

    await callback.answer("Конфиг деактивирован")
    await _render_gc_detail(callback, config_id)


# --- Reapply ---
@router.callback_query(lambda c: "_reapply" in c.data and c.data.startswith("gc_"))
async def gc_reapply(callback, state: FSMContext):
    await state.clear()
    owner_id = callback.from_user.id
    config_id = callback.data.split("_")[1]

    try:
        result = await backend_request(
            "POST", f"/global-configs/{config_id}/reapply",
            telegram_id=owner_id,
            with_api_key=True,
        )
    except Exception:
        await callback.answer("❌ Ошибка обновления", show_alert=True)
        return

    skipped = result.get("skipped_bots", {})
    applied = result.get("applied", 0)
    applied_bots = result.get("applied_bots", [])
    api_errors = result.get("api_errors", {})

    text = f"🔄 Конфиг обновлён на ботах.\n\n🤖 Применён к {applied} ботам:"

    if applied_bots:
        for ab in applied_bots:
            key_part = f" [{ab['key_name']}]" if ab.get("key_name") else ""
            text += f"\n  🟢 @{ab['username']}{key_part}"

    if skipped:
        text += "\n\n⚠️ <b>Пропущены поля:</b>\n"
        for username, fields in skipped.items():
            text += f"  @{username}: {', '.join(fields)}\n"

    if api_errors:
        text += "\n\n⚠️ <b>Ошибки API:</b>\n"
        for username, errors in api_errors.items():
            for err in errors:
                text += f"  @{username}: {err}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ К конфигу", callback_data=f"gc_{config_id}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="global_configs")],
    ])

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# --- Delete ---
@router.callback_query(lambda c: "_delete" in c.data and c.data.startswith("gc_") and "yes" not in c.data)
async def gc_delete_confirm(callback, state: FSMContext):
    await state.clear()
    config_id = callback.data.split("_")[1]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"gc_{config_id}_delete_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"gc_{config_id}")],
    ])

    await safe_edit(
        callback.message,
        "🗑 <b>Удалить конфиг?</b>\n\nНастройки уже применённых ботов не изменятся.",
        reply_markup=kb, parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: "_delete_yes" in c.data and c.data.startswith("gc_"))
async def gc_delete_yes(callback):
    owner_id = callback.from_user.id
    config_id = callback.data.split("_")[1]

    try:
        await backend_request("DELETE", f"/global-configs/{config_id}", telegram_id=owner_id)
    except Exception:
        await callback.answer("❌ Ошибка удаления", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Глобальные конфиги", callback_data="global_configs")],
    ])

    await safe_edit(callback.message, "✅ Конфиг удалён.", reply_markup=kb)
    await callback.answer()


# --- Regions ---
@router.callback_query(lambda c: c.data.endswith("_regions") and c.data.startswith("gc_"))
async def gc_regions_list(callback, state: FSMContext):
    await state.clear()
    owner_id = callback.from_user.id
    config_id = callback.data.split("_")[1]

    try:
        config = await backend_request("GET", f"/global-configs/{config_id}", telegram_id=owner_id)
    except Exception:
        await callback.answer("❌ Ошибка", show_alert=True)
        return

    regions = config.get("regions", [])

    rows = []
    for r in regions:
        rows.append([InlineKeyboardButton(
            text=f"🌍 {r['region']} — {r['name'][:20]}",
            callback_data=f"gc_{config_id}_rdel_{r['region']}",
        )])

    rows.append([InlineKeyboardButton(text="➕ Добавить регион", callback_data=f"gc_{config_id}_radd")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gc_{config_id}")])

    text = f"🌍 <b>Регионы конфига</b>\n\nРегионов: {len(regions)}"
    if regions:
        text += "\n\nНажмите на регион чтобы удалить.\n"
        for r in regions:
            text += f"\n🌍 <b>{r['region']}</b> — {r['name']}"
            if r.get('description'):
                text += f"\n   📎 <i>{r['description'][:100]}</i>"
            if r.get('full_description'):
                text += f"\n   📋 <i>{r['full_description'][:80]}{'...' if len(r['full_description']) > 80 else ''}</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: "_radd" in c.data and c.data.startswith("gc_"))
async def gc_region_add_start(callback, state: FSMContext):
    config_id = callback.data.split("_")[1]
    owner_id = callback.from_user.id

    # Получаем уже добавленные регионы
    try:
        config = await backend_request("GET", f"/global-configs/{config_id}", telegram_id=owner_id)
        already_added = {r["region"] for r in config.get("regions", [])}
    except Exception:
        already_added = set()

    await state.update_data(gc_id=config_id)
    await state.set_state(GlobalConfigStates.selecting_region)

    kb = gc_region_picker_keyboard(config_id, already_added)

    await safe_edit(
        callback.message,
        "🌍 <b>Выберите регион:</b>",
        reply_markup=kb, parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("gcr_"))
async def gc_region_selected(callback, state: FSMContext):
    parts = callback.data.split("_", 2)
    config_id = parts[1]
    region_code = parts[2]

    region_info = REGION_BY_CODE.get(region_code)
    region_label = f"{region_info['flag']} {region_info['title']}" if region_info else region_code

    await state.update_data(gc_id=config_id, selected_region=region_code)
    await state.set_state(GlobalConfigStates.editing_region_name)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gc_{config_id}_radd")],
    ])

    await safe_edit(
        callback.message,
        f"🌍 Регион: <b>{region_label}</b>\n\n"
        "Отправьте название бота для этого региона:",
        reply_markup=kb, parse_mode="HTML",
    )
    await callback.answer()


@router.message(GlobalConfigStates.editing_region_name)
async def gc_region_name_save(message: Message, state: FSMContext):
    data = await state.get_data()
    config_id = data["gc_id"]
    name = message.text.strip()[:64]

    await state.update_data(region_name=name)
    await state.set_state(GlobalConfigStates.editing_region_desc)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gc_{config_id}_radd")],
    ])

    await message.answer(
        f"Название: <b>{name}</b>\n\n"
        "Отправьте краткое описание бота для этого региона.\n\n"
        "Отображается в профиле бота. Можно ввести до 120 символов.\n"
        "Или отправьте <code>-</code> чтобы пропустить.",
        reply_markup=kb, parse_mode="HTML",
    )


@router.message(GlobalConfigStates.editing_region_desc)
async def gc_region_desc_save(message: Message, state: FSMContext):
    data = await state.get_data()
    config_id = data["gc_id"]

    text = message.text.strip()
    if text == "-":
        description = None
    elif len(text) > 120:
        await message.answer(f"⚠️ Краткое описание слишком длинное. Максимум 120 символов (сейчас {len(text)}). Сократите текст.")
        return
    else:
        description = text

    await state.update_data(region_desc=description)
    await state.set_state(GlobalConfigStates.editing_region_full_desc)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gc_{config_id}_radd")],
    ])

    await message.answer(
        "<b>Полное описание бота</b> - Что умеет этот бот?\n\n"
        "Отображается при первом открытии чата. Можно ввести до 512 символов.\n"
        "Или отправьте <code>-</code> чтобы пропустить.",
        reply_markup=kb, parse_mode="HTML",
    )


@router.message(GlobalConfigStates.editing_region_full_desc)
async def gc_region_full_desc_save(message: Message, state: FSMContext):
    owner_id = message.from_user.id
    data = await state.get_data()
    config_id = data["gc_id"]
    region = data["selected_region"]
    name = data["region_name"]
    description = data.get("region_desc")

    text = message.text.strip()
    if text == "-":
        full_description = None
    elif len(text) > 512:
        await message.answer(f"⚠️ Полное описание слишком длинное. Максимум 512 символов (сейчас {len(text)}). Сократите текст.")
        return
    else:
        full_description = text

    try:
        await backend_request(
            "POST", f"/global-configs/{config_id}/regions",
            telegram_id=owner_id,
            json={"region": region, "name": name, "description": description, "full_description": full_description},
        )
    except Exception:
        await message.answer("❌ Ошибка сохранения региона.")
        await state.clear()
        return

    await state.clear()

    region_info = REGION_BY_CODE.get(region)
    region_label = f"{region_info['flag']} {region_info['title']}" if region_info else region

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ещё регион", callback_data=f"gc_{config_id}_radd")],
        [InlineKeyboardButton(text="🌍 Регионы", callback_data=f"gc_{config_id}_regions")],
        [InlineKeyboardButton(text="⚙️ К конфигу", callback_data=f"gc_{config_id}")],
    ])
    await message.answer(f"✅ Регион {region_label} добавлен.", reply_markup=kb, parse_mode="HTML")


@router.callback_query(lambda c: "_rdel_" in c.data and c.data.startswith("gc_"))
async def gc_region_delete(callback, state: FSMContext):
    await state.clear()
    owner_id = callback.from_user.id
    parts = callback.data.split("_rdel_")
    config_id = parts[0].split("_")[1]
    region = parts[1]

    try:
        await backend_request(
            "DELETE", f"/global-configs/{config_id}/regions/{region}",
            telegram_id=owner_id,
        )
    except Exception:
        await callback.answer("❌ Ошибка удаления", show_alert=True)
        return

    await callback.answer(f"Регион {region} удалён")

    try:
        config = await backend_request("GET", f"/global-configs/{config_id}", telegram_id=owner_id)
    except Exception:
        return

    regions = config.get("regions", [])
    rows = []
    for r in regions:
        rows.append([InlineKeyboardButton(
            text=f"🌍 {r['region']} — {r['name'][:20]}",
            callback_data=f"gc_{config_id}_rdel_{r['region']}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить регион", callback_data=f"gc_{config_id}_radd")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gc_{config_id}")])

    text = f"🌍 <b>Регионы конфига</b>\n\nРегионов: {len(regions)}"
    if regions:
        text += "\n\nНажмите на регион чтобы удалить.\n"
        for r in regions:
            text += f"\n🌍 <b>{r['region']}</b> — {r['name']}"
            if r.get('description'):
                text += f"\n   📎 <i>{r['description'][:100]}</i>"
            if r.get('full_description'):
                text += f"\n   📋 <i>{r['full_description'][:80]}{'...' if len(r['full_description']) > 80 else ''}</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await safe_edit(
        callback.message,
        text,
        reply_markup=kb, parse_mode="HTML",
    )
