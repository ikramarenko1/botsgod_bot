from aiogram import Router
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext

from controller.common import (
    backend_request,
    safe_edit,
    safe_edit_by_id,
    safe_delete_message,
    safe_delete_by_id,
)
from controller.utils import (
    parse_utc3_input_to_utc_iso,
    utc_iso_to_utc3_human,
    buttons_status,
    status_emoji,
    short_text,
)
from controller.render import render_bot_menu_by_id, broadcast_show_confirm
from controller.keyboards.main import main_menu_keyboard
from controller.messages import (
    broadcast_created_text,
    broadcast_detail_text,
)
from controller.states import BroadcastStates

router = Router()


@router.callback_query(lambda c: c.data.endswith("_create_broadcast"))
async def broadcast_create_start(callback, state: FSMContext):
    bot_id = callback.data.split("_")[1]
    await state.clear()

    menu_msg_id = callback.message.message_id

    wizard = await callback.message.answer(
        "📢 <b>Создание рассылки</b>\n\n"
        "📝 Отправьте текст рассылки.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
        ]),
        parse_mode="HTML"
    )

    await state.update_data(
        bot_id=bot_id,
        menu_msg_id=menu_msg_id,
        wizard_msg_id=wizard.message_id,
        edit_mode=False
    )
    await state.set_state(BroadcastStates.waiting_text)
    await callback.answer()


@router.message(BroadcastStates.waiting_text)
async def broadcast_text_save(message: Message, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]

    if message.text.strip() != "-":
        await state.update_data(text=message.html_text)

    await state.set_state(BroadcastStates.waiting_buttons)

    await safe_edit_by_id(
        message.bot,
        chat_id=message.chat.id,
        message_id=wizard_msg_id,
        text=(
            "🔗 <b>Кнопки рассылки</b>\n\n"
            "Отправьте кнопки в формате:\n"
            "<code>Текст | https://example.com</code>\n\n"
            "Или отправьте <code>-</code> чтобы пропустить"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
        ]),
        parse_mode="HTML"
    )

    await safe_delete_message(message)


@router.message(BroadcastStates.waiting_buttons)
async def broadcast_buttons_save(message: Message, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]

    text_input = message.text.strip()
    buttons = None

    if text_input != "-":
        lines = [x.strip() for x in text_input.split("\n") if x.strip()]
        parsed = []

        for line in lines:
            if "|" not in line:
                await safe_edit_by_id(
                    message.bot, message.chat.id, wizard_msg_id,
                    "❌ <b>Неверный формат</b>\n\n"
                    "Используйте:\n<code>Текст | https://example.com</code>",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
                    ]),
                    parse_mode="HTML"
                )
                await safe_delete_message(message)
                return

            left, right = [x.strip() for x in line.split("|", 1)]
            if not left or not right.startswith("http"):
                await safe_edit_by_id(
                    message.bot, message.chat.id, wizard_msg_id,
                    "❌ <b>Проверьте текст и ссылку</b>\n\n"
                    "Ссылка должна начинаться с <code>http</code>.\n"
                    "Пример:\n<code>Кнопка | https://example.com</code>",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
                    ]),
                    parse_mode="HTML"
                )
                await safe_delete_message(message)
                return

            parsed.append({"text": left, "url": right})

        buttons = parsed

    await state.update_data(buttons=buttons)
    await state.set_state(BroadcastStates.waiting_when)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Сейчас", callback_data="broadcast_when_now")],
            [InlineKeyboardButton(text="⏳ Указать время", callback_data="broadcast_when_time")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")],
        ]
    )

    await safe_edit_by_id(
        message.bot,
        chat_id=message.chat.id,
        message_id=wizard_msg_id,
        text="⏳ <b>Время отправки</b>\n\nВыберите действие:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await safe_delete_message(message)


@router.callback_query(lambda c: c.data == "broadcast_cancel")
async def broadcast_cancel(callback, state: FSMContext):
    data = await state.get_data()

    bot_id = data.get("bot_id")
    menu_msg_id = data.get("menu_msg_id")
    wizard_msg_id = data.get("wizard_msg_id")

    chat_id = callback.message.chat.id
    owner_id = callback.from_user.id

    if wizard_msg_id:
        await safe_delete_by_id(callback.bot, chat_id, wizard_msg_id)

    await state.clear()
    await callback.answer("Создание рассылки отменено.")

    if bot_id and menu_msg_id:
        await render_bot_menu_by_id(callback.bot, chat_id, owner_id, bot_id, menu_msg_id)
    else:
        await safe_edit(callback.message, "Главное меню:", reply_markup=main_menu_keyboard())


@router.callback_query(lambda c: c.data == "broadcast_when_now")
async def broadcast_when_now(callback, state: FSMContext):
    await state.update_data(scheduled_at=parse_utc3_input_to_utc_iso("сейчас"))
    await state.set_state(BroadcastStates.confirm)
    await broadcast_show_confirm(callback.bot, callback.message, state)
    await callback.answer()


@router.callback_query(lambda c: c.data == "broadcast_when_time")
async def broadcast_when_time(callback, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]

    await state.set_state(BroadcastStates.waiting_time)

    await safe_edit_by_id(
        callback.bot,
        chat_id=callback.message.chat.id,
        message_id=wizard_msg_id,
        text=(
            "⏳ <b>Введите время (UTC+3)</b>\n\n"
            "Форматы:\n"
            "• <code>ЧЧ:ММ</code>\n"
            "• <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Пример: <code>19:30</code>"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
        ]),
        parse_mode="HTML"
    )

    await callback.answer()


@router.message(BroadcastStates.waiting_time)
async def broadcast_time_input(message: Message, state: FSMContext):
    data = await state.get_data()
    wizard_msg_id = data["wizard_msg_id"]

    try:
        scheduled_at = parse_utc3_input_to_utc_iso(message.text)
    except Exception:
        await safe_edit_by_id(
            message.bot, message.chat.id, wizard_msg_id,
            "❌ <b>Неверный формат времени</b>\n\n"
            "Форматы:\n"
            "• <code>ЧЧ:ММ</code>\n"
            "• <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
            "Пример: <code>19:30</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
            ]),
            parse_mode="HTML"
        )
        await safe_delete_message(message)
        return

    await state.update_data(scheduled_at=scheduled_at)
    await state.set_state(BroadcastStates.confirm)

    await broadcast_show_confirm(message.bot, message, state)
    await safe_delete_message(message)


@router.callback_query(lambda c: c.data == "broadcast_confirm")
async def broadcast_confirm(callback, state: FSMContext):
    owner_id = callback.from_user.id
    data = await state.get_data()

    bot_id = data.get("bot_id")
    text = data.get("text")
    buttons = data.get("buttons")
    scheduled_at = data.get("scheduled_at")

    if not bot_id or not text or not scheduled_at:
        await callback.answer("Данные потерялись", show_alert=True)
        await state.clear()
        return

    try:
        created = await backend_request(
            "POST",
            f"/bots/{bot_id}/broadcasts",
            telegram_id=owner_id,
            json={
                "region": "default",
                "text": text,
                "buttons": buttons,
                "scheduled_at": scheduled_at,
            },
            with_api_key=True,
        )
    except Exception:
        await callback.answer("❌ Ошибка создания", show_alert=True)
        return

    broadcast_id = created.get("id")
    status = created.get("status")

    buttons = []

    if status == "draft":
        buttons.append([
            InlineKeyboardButton(
                text="🧪 Отправить сейчас",
                callback_data=f"broadcast_{bot_id}_sendnow_{broadcast_id}"
            )
        ])

    buttons += [
        [InlineKeyboardButton(text="🗂 Отложенные рассылки", callback_data=f"bot_{bot_id}_scheduled_broadcasts")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")]
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    wizard_msg_id = data.get("wizard_msg_id")

    content = broadcast_created_text(broadcast_id, status, utc_iso_to_utc3_human(scheduled_at))

    await safe_edit_by_id(
        callback.bot,
        chat_id=callback.message.chat.id,
        message_id=wizard_msg_id,
        text=content,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await state.clear()
    await callback.answer("✅ Готово")


@router.callback_query(lambda c: c.data.endswith("_scheduled_broadcasts"))
async def broadcasts_list(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    try:
        broadcasts = await backend_request(
            "GET",
            f"/bots/{bot_id}/broadcasts",
            telegram_id=owner_id,
        )
        bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    except Exception:
        await safe_edit(callback.message, "❌ Ошибка загрузки рассылок.")
        await callback.answer()
        return

    bot_username = next((b["username"] for b in bots if str(b["id"]) == bot_id), "")

    broadcasts = sorted(
        broadcasts,
        key=lambda x: x.get("id", 0),
        reverse=True
    )[:20]

    if not broadcasts:
        text = (
            f"📢 <b>Рассылки бота @{bot_username}</b>\n\n"
            "— рассылок нет —"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать рассылку", callback_data=f"bot_{bot_id}_create_broadcast")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")],
        ])
        await safe_edit(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
        return

    lines = []
    rows = []
    for br in broadcasts:
        br_id = br.get("id")
        st = br.get("status")
        sch3 = utc_iso_to_utc3_human(br.get("scheduled_at"))

        lines.append(
            f"{status_emoji(st)} <b>#{br_id}</b> — {st} — "
            f"<code>{sch3}</code> — {short_text(br.get('text'))}"
        )
        rows.append([InlineKeyboardButton(
            text=f"{status_emoji(st)} #{br_id} ({st})",
            callback_data=f"broadcast_{bot_id}_open_{br_id}"
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать рассылку", callback_data=f"bot_{bot_id}_create_broadcast")],
        *rows,
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")],
    ])

    text = (
        f"📢 <b>Рассылки бота @{bot_username}</b>\n\n" +
        "\n".join(lines)
    )

    await safe_edit(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("broadcast_") and "_open_" in c.data)
async def broadcast_open(callback):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    broadcast_id = int(parts[-1])

    try:
        broadcasts = await backend_request("GET", f"/bots/{bot_id}/broadcasts", telegram_id=owner_id)
        br = next((x for x in broadcasts if int(x.get("id")) == broadcast_id), None)
    except Exception:
        await callback.answer("❌ Ошибка загрузки", show_alert=True)
        return

    if not br:
        await callback.answer("Не найдено", show_alert=True)
        return

    st = br.get("status")
    sch3 = utc_iso_to_utc3_human(br.get("scheduled_at"))
    started3 = utc_iso_to_utc3_human(br.get("started_at")) if br.get("started_at") else None
    finished3 = utc_iso_to_utc3_human(br.get("finished_at")) if br.get("finished_at") else None

    keyboard_rows = []

    if st in ("draft", "scheduled"):
        keyboard_rows.append([
            InlineKeyboardButton(
                text="✏️ Редактировать",
                callback_data=f"broadcast_{bot_id}_edit_{broadcast_id}"
            )
        ])

    if st == "draft":
        keyboard_rows.append([
            InlineKeyboardButton(
                text="🧪 Отправить сейчас",
                callback_data=f"broadcast_{bot_id}_sendnow_{broadcast_id}"
            )
        ])

    if st in ("sent", "failed", "sending"):
        keyboard_rows.append([
            InlineKeyboardButton(
                text="🔄 Обновить",
                callback_data=f"broadcast_{bot_id}_open_{broadcast_id}"
            )
        ])

    keyboard_rows.append([
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"broadcast_{bot_id}_delete_{broadcast_id}"
        )
    ])

    keyboard_rows.append([
        InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"bot_{bot_id}_scheduled_broadcasts"
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    await safe_edit(
        callback.message,
        broadcast_detail_text(
            broadcast_id, st, sch3,
            buttons_status(br.get('buttons')), br.get('text'),
            started_at_human=started3,
            finished_at_human=finished3,
            total_users=br.get('total_users', 0),
            sent_count=br.get('sent_count', 0),
            failed_count=br.get('failed_count', 0),
        ),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("broadcast_") and "_edit_" in c.data)
async def broadcast_edit_start(callback, state: FSMContext):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    broadcast_id = int(parts[-1])

    try:
        broadcasts = await backend_request(
            "GET",
            f"/bots/{bot_id}/broadcasts",
            telegram_id=owner_id,
        )
        br = next((x for x in broadcasts if int(x.get("id")) == broadcast_id), None)
    except Exception:
        await callback.answer("Ошибка загрузки", show_alert=True)
        return

    if not br:
        await callback.answer("Не найдено", show_alert=True)
        return

    await state.clear()

    wizard_msg_id = callback.message.message_id

    await state.update_data(
        bot_id=bot_id,
        broadcast_id=broadcast_id,
        wizard_msg_id=wizard_msg_id,
        edit_mode=True,
        text=br.get("text"),
        buttons=br.get("buttons"),
        scheduled_at=br.get("scheduled_at")
    )

    await state.set_state(BroadcastStates.waiting_text)

    await callback.bot.edit_message_text(
        chat_id=callback.message.chat.id,
        message_id=wizard_msg_id,
        text=(
            "✏️ <b>Редактирование рассылки</b>\n\n"
            "Отправьте новый текст.\n"
            "Или отправьте <code>-</code> чтобы оставить без изменений."
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="broadcast_cancel")]
        ]),
        parse_mode="HTML"
    )

    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("broadcast_") and "_sendnow_" in c.data)
async def broadcast_send_now(callback):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    broadcast_id = int(parts[-1])

    try:
        await backend_request(
            "POST",
            f"/broadcasts/{broadcast_id}/send-now",
            telegram_id=owner_id,
            with_api_key=True
        )
    except Exception:
        await callback.answer("❌ Ошибка отправки", show_alert=True)
        return

    try:
        broadcasts = await backend_request(
            "GET",
            f"/bots/{bot_id}/broadcasts",
            telegram_id=owner_id,
        )
        br = next((x for x in broadcasts if int(x.get("id")) == broadcast_id), None)
    except Exception:
        await callback.answer("Отправлено, но не удалось обновить экран")
        return

    if not br:
        await callback.answer("Отправлено")
        return

    st = br.get("status")
    sch3 = utc_iso_to_utc3_human(br.get("scheduled_at"))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"broadcast_{bot_id}_open_{broadcast_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}_scheduled_broadcasts")],
    ])

    await safe_edit(
        callback.message,
        broadcast_detail_text(broadcast_id, st, sch3, buttons_status(br.get('buttons')), br.get('text')),
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer("✅ Отправлено")


@router.callback_query(lambda c: c.data.startswith("broadcast_") and "_delete_" in c.data and "_delete_yes_" not in c.data)
async def broadcast_delete_confirm(callback, state: FSMContext):
    parts = callback.data.split("_")
    bot_id = parts[1]
    broadcast_id = int(parts[-1])

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"broadcast_{bot_id}_delete_yes_{broadcast_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"broadcast_{bot_id}_open_{broadcast_id}")],
    ])

    await safe_edit(
        callback.message,
        "🗑 <b>Удалить рассылку?</b>\n\n"
        "Она будет переведена в статус <b>cancelled</b>.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("broadcast_") and "_delete_yes_" in c.data)
async def broadcast_delete_yes(callback):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")
    bot_id = parts[1]
    broadcast_id = int(parts[-1])

    try:
        await backend_request(
            "PATCH",
            f"/broadcasts/{broadcast_id}/cancel",
            telegram_id=owner_id,
            with_api_key=True
        )
    except Exception:
        await callback.answer("❌ Ошибка удаления", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗂 К списку рассылок", callback_data=f"bot_{bot_id}_scheduled_broadcasts")],
        [InlineKeyboardButton(text="⬅️ К боту", callback_data=f"bot_{bot_id}")],
    ])

    await safe_edit(
        callback.message,
        "🗑 <b>Рассылка удалена</b>\nСтатус: <b>cancelled</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer("✅ Удалено")
