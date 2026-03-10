from aiogram import Router
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext

from controller.common import backend_request, safe_edit, safe_edit_by_id, safe_delete_message
from controller.keyboards.main import bots_checkbox_keyboard, BOTS_PER_PAGE, _pagination_row
from controller.utils import parse_utc3_input_to_utc_iso, utc_iso_to_utc3_human, buttons_status
from controller.states import KeyStates, KeyAddBotStates, KeyBroadcastStates, KeyRoleStates

router = Router()


@router.callback_query(lambda c: c.data == "my_keys")
async def keys_list(callback):
    owner_id = callback.from_user.id

    try:
        keys = await backend_request("GET", "/keys", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "Ошибка получения ключей.")
        await callback.answer()
        return

    if not keys:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать ключ", callback_data="key_create")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")],
        ])
        await safe_edit(callback.message, "🔑 <b>Мои ключи</b>\n\n— ключей нет —", reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return

    rows = []
    for k in keys:
        rows.append([InlineKeyboardButton(
            text=f"🔑 {k['short_name']}",
            callback_data=f"key_{k['id']}"
        )])

    rows.append([InlineKeyboardButton(text="➕ Создать ключ", callback_data="key_create")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await safe_edit(callback.message, "🔑 <b>Мои ключи</b>\n\nВыберите ключ:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data == "key_create")
async def key_create_start(callback, state: FSMContext):
    await state.set_state(KeyStates.waiting_full_name)
    await safe_edit(
        callback.message,
        "🔑 <b>Создание ключа</b>\n\nОтправьте полное название ключа:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(KeyStates.waiting_full_name)
async def key_full_name(message: Message, state: FSMContext):
    data = await state.get_data()

    if data.get("rename_field") == "full_name":
        owner_id = message.from_user.id
        key_id = data["key_id"]
        new_name = message.text.strip()
        try:
            await backend_request(
                "PATCH", f"/keys/{key_id}",
                telegram_id=owner_id,
                json={"full_name": new_name},
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 К ключу", callback_data=f"key_{key_id}")],
            ])
            await message.answer(f"✅ Название обновлено: <b>{new_name}</b>", reply_markup=kb, parse_mode="HTML")
        except Exception:
            await message.answer("❌ Ошибка обновления.")
        await state.clear()
        return

    await state.update_data(full_name=message.text.strip())
    await state.set_state(KeyStates.waiting_short_name)
    await message.answer("Отправьте короткое название (до 50 символов):")


@router.message(KeyStates.waiting_short_name)
async def key_short_name(message: Message, state: FSMContext):
    owner_id = message.from_user.id
    data = await state.get_data()
    full_name = data["full_name"]
    short_name = message.text.strip()[:50]

    try:
        key = await backend_request(
            "POST",
            "/keys",
            telegram_id=owner_id,
            json={"full_name": full_name, "short_name": short_name},
        )
    except Exception:
        await message.answer("❌ Ошибка создания ключа.")
        await state.clear()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 К ключу", callback_data=f"key_{key['id']}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="my_keys")],
    ])

    await message.answer(
        f"✅ Ключ <b>{short_name}</b> создан.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await state.clear()


@router.callback_query(lambda c: c.data.startswith("key_") and c.data[4:].isdigit())
async def key_detail(callback):
    key_id = callback.data.split("_")[1]
    await _render_key_detail(callback, key_id, page=0)


@router.callback_query(lambda c: c.data.startswith("key_") and "_page_" in c.data and c.data.split("_")[1].isdigit())
async def key_detail_page(callback):
    key_id = callback.data.split("_")[1]
    page = int(callback.data.split("_page_")[1])
    await _render_key_detail(callback, key_id, page=page)


async def _render_key_detail(callback, key_id: str, page: int = 0):
    owner_id = callback.from_user.id

    try:
        key = await backend_request("GET", f"/keys/{key_id}", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "Ключ не найден.")
        await callback.answer()
        return

    bots = key.get("bots", [])
    role_icons = {"active": "🟢", "reserve": "🟠", "farm": "🔄", "disabled": "⛔"}

    text = (
        f"🔑 <b>Ключ: {key['short_name']}</b>\n\n"
        f"🔑 Полное имя: {key['full_name']}\n"
        f"Farm-текст для ответов на сообщения: <i>{(key.get('farm_text') or '—')[:100]}</i>\n\n"
        f"<b>Боты ({len(bots)}):</b>"
    )

    rows = []

    total_pages = max(1, (len(bots) + BOTS_PER_PAGE - 1) // BOTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_bots = bots[page * BOTS_PER_PAGE : (page + 1) * BOTS_PER_PAGE]

    for b in page_bots:
        icon = role_icons.get(b['role'], '🤖')
        rows.append([InlineKeyboardButton(
            text=f"{icon} @{b['username']}",
            callback_data=f"bot_{b['id']}"
        )])

    if total_pages > 1:
        rows.append(_pagination_row(f"key_{key_id}", page, total_pages))

    rows += [
        [
            InlineKeyboardButton(text="➕ Добавить бота", callback_data=f"key_{key_id}_add_bot"),
            InlineKeyboardButton(text="🔗 Привязать бота", callback_data=f"key_{key_id}_assign"),
        ],
        [
            InlineKeyboardButton(text="📢 Рассылка", callback_data=f"key_{key_id}_broadcast"),
            InlineKeyboardButton(text="🔄 Смена роли", callback_data=f"key_{key_id}_mass_role"),
        ],
        [
            InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"key_{key_id}_rename"),
            InlineKeyboardButton(text="🗑 Удалить ключ", callback_data=f"key_{key_id}_delete")
        ],
        [InlineKeyboardButton(text="🔄 Настроить farm-текст", callback_data=f"key_{key_id}_farm")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_keys")],
    ]

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: "_add_bot" in c.data and c.data.startswith("key_") and c.data.split("_")[1].isdigit())
async def key_add_bot_start(callback, state: FSMContext):
    key_id = callback.data.split("_")[1]
    await state.clear()
    await state.update_data(key_id=key_id)
    await state.set_state(KeyAddBotStates.waiting_tokens)

    text = (
        "Чтобы подключить бот(ы), Вам нужно выполнить следующие действия:\n\n"
        "1. Перейдите в @BotFather и создайте новый бот (можно импортировать существующий).\n"
        "2. После создания бота Вы получите токен (123456:ABCDEF) — скопируйте или перешлите его в этот чат.\n\n"
        "Важно: не подключайте боты, которые уже используются другими сервисами.\n"
        "💡 Можно отправить <b>несколько токенов</b> — каждый с новой строки."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"key_{key_id}")],
    ])

    await safe_edit(callback.message, text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.message(KeyAddBotStates.waiting_tokens)
async def key_add_bot_tokens(message: Message, state: FSMContext):
    lines = [line.strip() for line in message.text.strip().split("\n") if line.strip()]
    tokens = [t for t in lines if ":" in t]

    if not tokens:
        await message.answer("❌ Не найдено ни одного токена. Токен должен содержать ':'.")
        return

    await state.update_data(tokens=tokens)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Активный бот", callback_data="kadd_role_active")],
            [InlineKeyboardButton(text="🟠 Резервный бот", callback_data="kadd_role_reserve")],
            [InlineKeyboardButton(text="🔄 Фарм бот", callback_data="kadd_role_farm")],
        ]
    )

    if len(tokens) > 1:
        count_text = (
            f"✅ Найдено токенов: <b>{len(tokens)}</b>\n\n"
            "Каждый бот будет добавлен с выбранной ролью.\n"
            "Выберите роль:"
        )
    else:
        count_text = "Выберите роль:"

    await message.answer(count_text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(KeyAddBotStates.waiting_role)


@router.callback_query(KeyAddBotStates.waiting_role, lambda c: c.data in ("kadd_role_active", "kadd_role_reserve", "kadd_role_farm"))
async def key_add_bot_role(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()
    tokens = data.get("tokens", [])
    key_id = data["key_id"]

    role_map = {
        "kadd_role_active": "active",
        "kadd_role_reserve": "reserve",
        "kadd_role_farm": "farm",
    }
    role = role_map[callback.data]
    role_labels = {"active": "🟢 Активный", "reserve": "🟠 Резервный", "farm": "🔄 Фарм"}
    role_label = role_labels.get(role, role)

    added = []
    failed = []

    for token in tokens:
        try:
            result = await backend_request(
                "POST",
                "/bots/add",
                telegram_id=owner_id,
                json={"token": token, "role": role},
                with_api_key=True,
            )
            bot_id = result.get("id")
            username = result.get("username")
            added.append({"id": bot_id, "username": username})

            try:
                await backend_request(
                    "POST",
                    f"/keys/{key_id}/bots/{bot_id}",
                    telegram_id=owner_id,
                )
            except Exception:
                pass
        except Exception:
            short = token[:15] + "..." if len(token) > 15 else token
            failed.append(short)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔑 К ключу", callback_data=f"key_{key_id}")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_to_main")],
        ]
    )

    if len(tokens) == 1:
        if added:
            text = f"✅ Бот @{added[0]['username']} добавлен и привязан к ключу\n\nРоль: {role_label}"
        else:
            text = "❌ Неверный токен или бот уже добавлен."
    else:
        header = "⚠️ <b>Результат добавления</b>" if failed else "✅ <b>Боты успешно добавлены</b>"
        lines = [f"{header}\n\nРоль: {role_label}\n"]
        if added:
            lines.append(f"✅ Добавлено и привязано: {len(added)}")
            for b in added:
                lines.append(f"  • @{b['username']}")
        if failed:
            lines.append(f"\n❌ Ошибки: {len(failed)}")
            for t in failed:
                lines.append(f"  • {t}")
        text = "\n".join(lines)

    await safe_edit(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()
    await state.clear()


@router.callback_query(lambda c: "_assign" in c.data and c.data.startswith("key_"))
async def key_assign_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    key_id = callback.data.split("_")[1]

    try:
        bots = await backend_request("GET", "/bots", telegram_id=owner_id)
        key = await backend_request("GET", f"/keys/{key_id}", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "Ошибка загрузки.")
        await callback.answer()
        return

    assigned_ids = {b["id"] for b in key.get("bots", [])}
    unassigned = [b for b in bots if b["id"] not in assigned_ids]

    if not unassigned:
        await callback.answer("Все боты уже привязаны к этому ключу", show_alert=True)
        return

    await state.update_data(key_id=key_id, bots=unassigned, selected_ids=set())
    await state.set_state(KeyStates.assign_bots)

    kb = bots_checkbox_keyboard(f"ka{key_id}", unassigned, set(), back_callback=f"key_{key_id}")
    await safe_edit(
        callback.message,
        f"🔑 <b>Добавить ботов в ключ {key.get('short_name')}</b>\n\nВыберите ботов:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(KeyStates.assign_bots, lambda c: "_page_" in c.data)
async def ka_page(callback, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    key_id = data["key_id"]
    selected = set(data.get("selected_ids", set()))
    await state.update_data(page=page)
    kb = bots_checkbox_keyboard(f"ka{key_id}", data["bots"], selected, back_callback=f"key_{key_id}", page=page)
    await safe_edit(callback.message, f"🔑 Выбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyStates.assign_bots, lambda c: "_toggle_" in c.data)
async def ka_toggle(callback, state: FSMContext):
    bot_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    selected = set(data.get("selected_ids", set()))
    key_id = data["key_id"]
    page = data.get("page", 0)

    if bot_id in selected:
        selected.discard(bot_id)
    else:
        selected.add(bot_id)

    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(f"ka{key_id}", data["bots"], selected, back_callback=f"key_{key_id}", page=page)
    await safe_edit(
        callback.message,
        f"🔑 Выбрано: {len(selected)}",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(KeyStates.assign_bots, lambda c: "_select_all" in c.data)
async def ka_select_all(callback, state: FSMContext):
    data = await state.get_data()
    selected = {b["id"] for b in data["bots"]}
    key_id = data["key_id"]
    page = data.get("page", 0)
    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(f"ka{key_id}", data["bots"], selected, back_callback=f"key_{key_id}", page=page)
    await safe_edit(callback.message, f"🔑 Выбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyStates.assign_bots, lambda c: "_reset" in c.data)
async def ka_reset(callback, state: FSMContext):
    data = await state.get_data()
    key_id = data["key_id"]
    await state.update_data(selected_ids=set(), page=0)
    kb = bots_checkbox_keyboard(f"ka{key_id}", data["bots"], set(), back_callback=f"key_{key_id}")
    await safe_edit(callback.message, "🔑 Выберите ботов:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyStates.assign_bots, lambda c: "_done" in c.data)
async def ka_done(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()
    selected = data.get("selected_ids", set())
    key_id = data["key_id"]

    if not selected:
        await callback.answer("Выберите хотя бы одного бота", show_alert=True)
        return

    success = 0
    for bot_id in selected:
        try:
            await backend_request(
                "POST",
                f"/keys/{key_id}/bots/{bot_id}",
                telegram_id=owner_id,
            )
            success += 1
        except Exception:
            pass

    await state.clear()
    await callback.answer(f"Привязано ботов: {success}")

    try:
        key = await backend_request("GET", f"/keys/{key_id}", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "Готово.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="my_keys")]
        ]))
        return

    bots = key.get("bots", [])
    bots_text = "\n".join([f"  • @{b['username']} ({b['role']})" for b in bots]) if bots else "— нет ботов —"

    text = (
        f"🔑 <b>Ключ: {key['short_name']}</b>\n\n"
        f"✅ Привязано ботов: {success}\n\n"
        f"🤖 <b>Боты ({len(bots)}):</b>\n{bots_text}"
    )

    rows = [
        [InlineKeyboardButton(text="🔑 К ключу", callback_data=f"key_{key_id}")],
        [InlineKeyboardButton(text="⬅️ К списку", callback_data="my_keys")],
    ]

    await safe_edit(callback.message, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@router.callback_query(lambda c: "_rename" in c.data and c.data.startswith("key_") and c.data.split("_")[1].isdigit())
async def key_rename_start(callback, state: FSMContext):
    key_id = callback.data.split("_")[1]
    await state.update_data(key_id=key_id, rename_field="full_name")
    await state.set_state(KeyStates.waiting_full_name)
    await safe_edit(callback.message, "✏️ Отправьте новое полное название:")
    await callback.answer()


@router.callback_query(lambda c: "_farm" in c.data and c.data.startswith("key_") and c.data.split("_")[1].isdigit())
async def key_farm_start(callback, state: FSMContext):
    key_id = callback.data.split("_")[1]
    await state.update_data(key_id=key_id)
    await state.set_state(KeyStates.waiting_farm_text)
    await safe_edit(
        callback.message,
        "🔄 <b>Farm-текст</b>\n\nОтправьте текст, который будет отправляться пользователям farm-ботов этого ключа.\n\n"
        "Поддерживается HTML-форматирование.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(KeyStates.waiting_farm_text)
async def key_farm_save(message: Message, state: FSMContext):
    owner_id = message.from_user.id
    data = await state.get_data()
    key_id = data["key_id"]

    try:
        await backend_request(
            "PATCH",
            f"/keys/{key_id}",
            telegram_id=owner_id,
            json={"farm_text": message.html_text},
        )
    except Exception:
        await message.answer("❌ Ошибка обновления.")
        await state.clear()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 К ключу", callback_data=f"key_{key_id}")],
    ])

    await message.answer("✅ Farm-текст обновлён.", reply_markup=kb)
    await state.clear()


@router.callback_query(lambda c: "_delete" in c.data and c.data.startswith("key_") and c.data.split("_")[1].isdigit() and "yes" not in c.data)
async def key_delete_confirm(callback):
    key_id = callback.data.split("_")[1]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"key_{key_id}_delete_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"key_{key_id}")],
    ])

    await safe_edit(
        callback.message,
        "🗑 <b>Удалить ключ?</b>\n\nБоты будут отвязаны от ключа, но не удалены.",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: "_delete_yes" in c.data and c.data.startswith("key_"))
async def key_delete_yes(callback):
    owner_id = callback.from_user.id
    key_id = callback.data.split("_")[1]

    try:
        await backend_request("DELETE", f"/keys/{key_id}", telegram_id=owner_id)
    except Exception:
        await callback.answer("❌ Ошибка удаления", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Мои ключи", callback_data="my_keys")],
    ])

    await safe_edit(callback.message, "✅ Ключ удалён.", reply_markup=kb)
    await callback.answer()


KBC_PREFIX = "kbc"


@router.callback_query(lambda c: "_broadcast" in c.data and c.data.startswith("key_") and c.data.split("_")[1].isdigit())
async def key_broadcast_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    key_id = callback.data.split("_")[1]
    await state.clear()

    try:
        key = await backend_request("GET", f"/keys/{key_id}", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "Ошибка загрузки.")
        await callback.answer()
        return

    bots = key.get("bots", [])
    active_bots = [b for b in bots if b.get("role") in ("active", "farm")]

    if not active_bots:
        await callback.answer("Нет активных ботов в этом ключе", show_alert=True)
        return

    await state.update_data(
        key_id=key_id,
        bots=active_bots,
        selected_ids=set(),
    )
    await state.set_state(KeyBroadcastStates.selecting_bots)

    kb = bots_checkbox_keyboard(KBC_PREFIX, active_bots, set(), back_callback=f"key_{key_id}", show_role_filters=True)
    await safe_edit(
        callback.message,
        f"📢 <b>Рассылка по ключу {key['short_name']}</b>\n\nВыберите ботов:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(KeyBroadcastStates.selecting_bots, lambda c: c.data.startswith(f"{KBC_PREFIX}_page_"))
async def kbc_page(callback, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    key_id = data["key_id"]
    selected = set(data.get("selected_ids", set()))
    await state.update_data(page=page)
    kb = bots_checkbox_keyboard(KBC_PREFIX, data["bots"], selected, back_callback=f"key_{key_id}", show_role_filters=True, page=page)
    await safe_edit(callback.message, f"📢 Выбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyBroadcastStates.selecting_bots, lambda c: c.data.startswith(f"{KBC_PREFIX}_toggle_"))
async def kbc_toggle(callback, state: FSMContext):
    bot_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    selected = set(data.get("selected_ids", set()))
    key_id = data["key_id"]
    page = data.get("page", 0)

    if bot_id in selected:
        selected.discard(bot_id)
    else:
        selected.add(bot_id)

    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(KBC_PREFIX, data["bots"], selected, back_callback=f"key_{key_id}", show_role_filters=True, page=page)
    await safe_edit(
        callback.message,
        f"📢 Выбрано: {len(selected)}",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(KeyBroadcastStates.selecting_bots, lambda c: c.data == f"{KBC_PREFIX}_select_all")
async def kbc_select_all(callback, state: FSMContext):
    data = await state.get_data()
    selected = {b["id"] for b in data["bots"]}
    key_id = data["key_id"]
    page = data.get("page", 0)
    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(KBC_PREFIX, data["bots"], selected, back_callback=f"key_{key_id}", show_role_filters=True, page=page)
    await safe_edit(callback.message, f"📢 Выбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyBroadcastStates.selecting_bots, lambda c: c.data == f"{KBC_PREFIX}_select_active")
async def kbc_select_active(callback, state: FSMContext):
    data = await state.get_data()
    selected = {b["id"] for b in data["bots"] if b.get("role") == "active"}
    key_id = data["key_id"]
    page = data.get("page", 0)
    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(KBC_PREFIX, data["bots"], selected, back_callback=f"key_{key_id}", show_role_filters=True, page=page)
    await safe_edit(callback.message, f"📢 Выбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyBroadcastStates.selecting_bots, lambda c: c.data == f"{KBC_PREFIX}_select_farm")
async def kbc_select_farm(callback, state: FSMContext):
    data = await state.get_data()
    selected = {b["id"] for b in data["bots"] if b.get("role") == "farm"}
    key_id = data["key_id"]
    page = data.get("page", 0)
    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(KBC_PREFIX, data["bots"], selected, back_callback=f"key_{key_id}", show_role_filters=True, page=page)
    await safe_edit(callback.message, f"📢 Выбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyBroadcastStates.selecting_bots, lambda c: c.data == f"{KBC_PREFIX}_reset")
async def kbc_reset(callback, state: FSMContext):
    data = await state.get_data()
    key_id = data["key_id"]
    await state.update_data(selected_ids=set(), page=0)
    kb = bots_checkbox_keyboard(KBC_PREFIX, data["bots"], set(), back_callback=f"key_{key_id}", show_role_filters=True)
    await safe_edit(callback.message, "📢 Выберите ботов:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyBroadcastStates.selecting_bots, lambda c: c.data == f"{KBC_PREFIX}_done")
async def kbc_done_selecting(callback, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_ids", set())

    if not selected:
        await callback.answer("Выберите хотя бы одного бота", show_alert=True)
        return

    wizard = await callback.message.answer(
        "📝 <b>Текст рассылки</b>\n\nОтправьте текст сообщения.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"key_{data['key_id']}_broadcast")]
        ]),
        parse_mode="HTML",
    )
    await state.update_data(wizard_msg_id=wizard.message_id)
    await state.set_state(KeyBroadcastStates.waiting_text)
    await callback.answer()


@router.message(KeyBroadcastStates.waiting_text)
async def kbc_text_save(message: Message, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]
    key_id = data["key_id"]

    await state.update_data(text=message.html_text)
    await state.set_state(KeyBroadcastStates.waiting_buttons)

    await safe_edit_by_id(
        message.bot, message.chat.id, wizard_msg_id,
        "🔗 <b>Кнопки рассылки</b>\n\n"
        "Отправьте кнопки в формате:\n"
        "<code>Текст | https://example.com</code>\n\n"
        "Или отправьте <code>-</code> чтобы пропустить",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"key_{key_id}_broadcast")]
        ]),
        parse_mode="HTML",
    )
    await safe_delete_message(message)


@router.message(KeyBroadcastStates.waiting_buttons)
async def kbc_buttons_save(message: Message, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]
    key_id = data["key_id"]

    text_input = message.text.strip()
    buttons = None

    if text_input != "-":
        lines = [x.strip() for x in text_input.split("\n") if x.strip()]
        parsed = []
        for line in lines:
            if "|" not in line:
                await safe_delete_message(message)
                return
            left, right = [x.strip() for x in line.split("|", 1)]
            if not left or not right.startswith("http"):
                await safe_delete_message(message)
                return
            parsed.append({"text": left, "url": right})
        buttons = parsed

    await state.update_data(buttons=buttons)
    await state.set_state(KeyBroadcastStates.waiting_when)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Сейчас", callback_data="kbc_when_now")],
            [InlineKeyboardButton(text="⏳ Указать время", callback_data="kbc_when_time")],
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"key_{key_id}_broadcast")],
        ]
    )

    await safe_edit_by_id(
        message.bot, message.chat.id, wizard_msg_id,
        "⏳ <b>Время отправки</b>\n\nВыберите действие:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await safe_delete_message(message)


@router.callback_query(lambda c: c.data == "kbc_when_now")
async def kbc_when_now(callback, state: FSMContext):
    await state.update_data(scheduled_at=parse_utc3_input_to_utc_iso("сейчас"))
    await state.set_state(KeyBroadcastStates.confirm)
    await _show_kbc_confirm(callback, state)
    await callback.answer()


@router.callback_query(lambda c: c.data == "kbc_when_time")
async def kbc_when_time(callback, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]
    key_id = data["key_id"]
    await state.set_state(KeyBroadcastStates.waiting_time)

    await safe_edit_by_id(
        callback.bot, callback.message.chat.id, wizard_msg_id,
        "⏳ <b>Введите время (UTC+3)</b>\n\n"
        "Форматы:\n"
        "• <code>ЧЧ:ММ</code>\n"
        "• <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"key_{key_id}_broadcast")]
        ]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(KeyBroadcastStates.waiting_time)
async def kbc_time_input(message: Message, state: FSMContext):
    try:
        scheduled_at = parse_utc3_input_to_utc_iso(message.text)
    except Exception:
        await safe_delete_message(message)
        return

    await state.update_data(scheduled_at=scheduled_at)
    await state.set_state(KeyBroadcastStates.confirm)

    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]
    selected = data.get("selected_ids", set())
    key_id = data["key_id"]
    text = data.get("text", "")
    btns = data.get("buttons")

    content = (
        f"📢 <b>Рассылка по ключу — подтверждение</b>\n\n"
        f"🤖 Ботов: <b>{len(selected)}</b>\n"
        f"📝 <b>Текст:</b>\n<blockquote>{text}</blockquote>\n\n"
        f"🔗 Кнопки: {buttons_status(btns)}\n"
        f"⏳ Отправка: <b>{utc_iso_to_utc3_human(scheduled_at)}</b> (UTC+3)"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать", callback_data="kbc_confirm")],
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"key_{key_id}_broadcast")],
        ]
    )

    await safe_edit_by_id(message.bot, message.chat.id, wizard_msg_id, content, reply_markup=kb, parse_mode="HTML")
    await safe_delete_message(message)


async def _show_kbc_confirm(callback, state: FSMContext):
    data = await state.get_data()
    text = data.get("text", "")
    btns = data.get("buttons")
    scheduled_at = data.get("scheduled_at")
    wizard_msg_id = data.get("wizard_msg_id")
    selected = data.get("selected_ids", set())
    key_id = data["key_id"]

    content = (
        f"📢 <b>Рассылка по ключу — подтверждение</b>\n\n"
        f"🤖 Ботов: <b>{len(selected)}</b>\n"
        f"📝 <b>Текст:</b>\n<blockquote>{text}</blockquote>\n\n"
        f"🔗 Кнопки: {buttons_status(btns)}\n"
        f"⏳ Отправка: <b>{utc_iso_to_utc3_human(scheduled_at)}</b> (UTC+3)"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать", callback_data="kbc_confirm")],
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"key_{key_id}_broadcast")],
        ]
    )

    await safe_edit_by_id(callback.bot, callback.message.chat.id, wizard_msg_id, content, reply_markup=kb, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "kbc_confirm")
async def kbc_confirm(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()

    text = data.get("text")
    btns = data.get("buttons")
    scheduled_at = data.get("scheduled_at")
    selected_ids = list(data.get("selected_ids", []))
    wizard_msg_id = data.get("wizard_msg_id")
    key_id = data.get("key_id")

    if not selected_ids or not text or not scheduled_at:
        await callback.answer("Данные потерялись", show_alert=True)
        await state.clear()
        return

    first_bot_id = selected_ids[0]

    try:
        created = await backend_request(
            "POST",
            f"/bots/{first_bot_id}/broadcasts",
            telegram_id=owner_id,
            json={
                "region": "default",
                "text": text,
                "buttons": btns,
                "scheduled_at": scheduled_at,
                "bot_ids": selected_ids,
            },
            with_api_key=True,
        )
    except Exception:
        await callback.answer("Ошибка создания рассылки", show_alert=True)
        return

    broadcast_id = created.get("id")
    status = created.get("status")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔑 К ключу", callback_data=f"key_{key_id}")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_to_main")],
        ]
    )

    content = (
        f"✅ <b>Рассылка создана</b>\n\n"
        f"🆔 ID: <code>{broadcast_id}</code>\n"
        f"📡 Статус: <b>{status}</b>\n"
        f"🤖 Ботов: <b>{len(selected_ids)}</b>\n"
        f"⏳ Отправка: <b>{utc_iso_to_utc3_human(scheduled_at)}</b> (UTC+3)"
    )

    await safe_edit_by_id(
        callback.bot, callback.message.chat.id, wizard_msg_id,
        content, reply_markup=kb, parse_mode="HTML",
    )

    await state.clear()
    await callback.answer("✅ Готово")


KR_PREFIX = "krl"


@router.callback_query(lambda c: "_mass_role" in c.data and c.data.startswith("key_") and c.data.split("_")[1].isdigit())
async def key_role_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    key_id = callback.data.split("_")[1]
    await state.clear()

    try:
        key = await backend_request("GET", f"/keys/{key_id}", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "Ошибка загрузки.")
        await callback.answer()
        return

    bots = key.get("bots", [])

    if not bots:
        await callback.answer("Нет ботов в этом ключе", show_alert=True)
        return

    await state.update_data(key_id=key_id, bots=bots, selected_ids=set())
    await state.set_state(KeyRoleStates.selecting_bots)

    kb = bots_checkbox_keyboard(KR_PREFIX, bots, set(), back_callback=f"key_{key_id}")
    await safe_edit(
        callback.message,
        f"🔄 <b>Смена роли — ключ {key['short_name']}</b>\n\nВыберите ботов:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(KeyRoleStates.selecting_bots, lambda c: c.data.startswith(f"{KR_PREFIX}_page_"))
async def krl_page(callback, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    data = await state.get_data()
    key_id = data["key_id"]
    selected = set(data.get("selected_ids", set()))
    await state.update_data(page=page)
    kb = bots_checkbox_keyboard(KR_PREFIX, data["bots"], selected, back_callback=f"key_{key_id}", page=page)
    await safe_edit(callback.message, f"🔄 Выбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyRoleStates.selecting_bots, lambda c: c.data.startswith(f"{KR_PREFIX}_toggle_"))
async def krl_toggle(callback, state: FSMContext):
    bot_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    selected = set(data.get("selected_ids", set()))
    key_id = data["key_id"]
    page = data.get("page", 0)

    if bot_id in selected:
        selected.discard(bot_id)
    else:
        selected.add(bot_id)

    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(KR_PREFIX, data["bots"], selected, back_callback=f"key_{key_id}", page=page)
    await safe_edit(
        callback.message,
        f"🔄 Выбрано: {len(selected)}",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(KeyRoleStates.selecting_bots, lambda c: c.data == f"{KR_PREFIX}_select_all")
async def krl_select_all(callback, state: FSMContext):
    data = await state.get_data()
    selected = {b["id"] for b in data["bots"]}
    key_id = data["key_id"]
    page = data.get("page", 0)
    await state.update_data(selected_ids=selected)
    kb = bots_checkbox_keyboard(KR_PREFIX, data["bots"], selected, back_callback=f"key_{key_id}", page=page)
    await safe_edit(callback.message, f"🔄 Выбрано: {len(selected)}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyRoleStates.selecting_bots, lambda c: c.data == f"{KR_PREFIX}_reset")
async def krl_reset(callback, state: FSMContext):
    data = await state.get_data()
    key_id = data["key_id"]
    await state.update_data(selected_ids=set(), page=0)
    kb = bots_checkbox_keyboard(KR_PREFIX, data["bots"], set(), back_callback=f"key_{key_id}")
    await safe_edit(callback.message, "🔄 Выберите ботов:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(KeyRoleStates.selecting_bots, lambda c: c.data == f"{KR_PREFIX}_done")
async def krl_done_selecting(callback, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_ids", set())
    key_id = data["key_id"]

    if not selected:
        await callback.answer("Выберите хотя бы одного бота", show_alert=True)
        return

    await state.set_state(KeyRoleStates.selecting_role)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Активный", callback_data="krl_role_active")],
            [InlineKeyboardButton(text="🟠 Резервный", callback_data="krl_role_reserve")],
            [InlineKeyboardButton(text="🔄 Фарм", callback_data="krl_role_farm")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"key_{key_id}_mass_role")],
        ]
    )

    await safe_edit(
        callback.message,
        f"Выбрано ботов: <b>{len(selected)}</b>\n\nВыберите новую роль:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(KeyRoleStates.selecting_role, lambda c: c.data in ("krl_role_active", "krl_role_reserve", "krl_role_farm"))
async def krl_apply_role(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()
    selected_ids = list(data.get("selected_ids", []))
    key_id = data["key_id"]

    role_map = {
        "krl_role_active": "active",
        "krl_role_reserve": "reserve",
        "krl_role_farm": "farm",
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
            [InlineKeyboardButton(text="🔑 К ключу", callback_data=f"key_{key_id}")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_to_main")],
        ]
    )

    await safe_edit(callback.message, "\n".join(lines), reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()
    await state.clear()
