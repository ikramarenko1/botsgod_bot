from typing import Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# === Клавиатуры ===

def bot_menu_keyboard(bot_id: str, role: str) -> InlineKeyboardMarkup:
    is_active = role == "active"
    is_disabled = role == "disabled"

    if is_disabled:
        toggle_text = "✅ Включить бота"
        toggle_data = f"bot_{bot_id}_enable"
    else:
        toggle_text = "⛔ Выключить бота"
        toggle_data = f"bot_{bot_id}_disable"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data=f"bot_{bot_id}_stats")],
            [InlineKeyboardButton(text="📩 Сообщение", callback_data=f"bot_{bot_id}_message")],
            [InlineKeyboardButton(text="⏳ Отложенное сообщение", callback_data=f"bot_{bot_id}_delayed")],
            [InlineKeyboardButton(text="📢 Создать рассылку", callback_data=f"bot_{bot_id}_create_broadcast")],
            [InlineKeyboardButton(text="🗂 Отложенные рассылки", callback_data=f"bot_{bot_id}_scheduled_broadcasts")],
            [InlineKeyboardButton(text="✏ Изменить название", callback_data=f"bot_{bot_id}_rename")],
            [InlineKeyboardButton(text="🖼 Изменить фото", callback_data=f"bot_{bot_id}_avatar")],
            [InlineKeyboardButton(text=toggle_text, callback_data=toggle_data)],
            [InlineKeyboardButton(text="📜 Логи замены", callback_data=f"bot_{bot_id}_replacement_logs")],
            [InlineKeyboardButton(text="📦 Выгрузить пользователей", callback_data=f"bot_{bot_id}_export_users")],
            [InlineKeyboardButton(text="🗑 Удалить бота", callback_data=f"bot_{bot_id}_delete")],
            [InlineKeyboardButton(text="« Назад", callback_data="my_bots")]
        ]
    )


# === Тексты сообщений ===

def bot_menu_text(bot_username: str, role: str) -> str:
    status_line = ""
    if role == "disabled":
        status_line = "\n\n⚠️ Бот выключен и не принимает сообщения."
    elif role == "reserve":
        status_line = "\n\n🔄 Резервный бот"
    return f"Управление ботом @{bot_username}.{status_line}"


def welcome_menu_text(
    bot_username: str,
    text_block: str,
    photo_status: str,
    buttons_flag: str,
) -> str:
    return (
        f"🏠 <b>Настройка приветствия бота @{bot_username}</b>\n\n"
        f"📝 <b>Текущее сообщение:</b>\n"
        f"{text_block}\n\n"
        f"📸 Фото: {photo_status}\n"
        f"🔗 Кнопки: {buttons_flag}\n\n"
        f"Выберите действие:"
    )


def delayed_menu_text(
    bot_username: str,
    text_block: str,
    photo_status: str,
    buttons_flag: str,
    delay_value: str,
    enabled_status: str,
) -> str:
    return (
        f"⏳ <b>Отложенное сообщение для @{bot_username}</b>\n\n"
        f"📝 <b>Текст:</b>\n{text_block}\n\n"
        f"📸 Фото: {photo_status}\n"
        f"🔗 Кнопки: {buttons_flag}\n"
        f"⏳ Задержка: {delay_value}\n\n"
        f"📡 Статус: {enabled_status}\n\n"
        f"Выберите действие:"
    )


def stats_text(
    bot_username: str,
    total: int,
    premium: int,
    normal: int,
    premium_percent: float,
    normal_percent: float,
    geo_lines: str,
    growth_hour: int,
    growth_day: int,
    growth_week: int,
) -> str:
    return (
        f"📊 <b>Статистика пользователей бота @{bot_username}</b>\n\n"
        f"<b>👥 Всего пользователей:</b> {total}\n"
        f"💎 Премиум пользователи: {premium} ({premium_percent}%)\n"
        f"👤 Обычные пользователи: {normal} ({normal_percent}%)\n\n"
        f"<b>🌍 География пользователей:</b>\n"
        f"{geo_lines}\n"
        f"<b>📈 Рост аудитории:</b>\n"
        f"⏰ За последний час: +{growth_hour}\n"
        f"📅 За последний день: +{growth_day}\n"
        f"📊 За последнюю неделю: +{growth_week}"
    )


def replacement_logs_text(bot_username: str, logs: list, total: int, lines: list[str]) -> str:
    if not logs:
        return (
            f"📜 <b>Логи замены бота @{bot_username}</b>\n\n"
            "Замен не было."
        )
    return (
        f"📜 <b>Логи замены бота @{bot_username}</b>\n\n"
        f"Всего замен: {total}\n\n"
        + "\n\n".join(lines)
    )


def worker_status_text(
    status: str,
    last_hb: str,
    last_hc: str,
    last_rr: str,
) -> str:
    status_emoji = "🟢" if status == "online" else "🔴"
    return (
        f"🧠 <b>Статус Worker</b>\n\n"
        f"{status_emoji} Статус: <b>{status}</b>\n\n"
        f"🕐 Последний heartbeat: {last_hb}\n"
        f"🩺 Последний health-check: {last_hc}\n"
        f"🔄 Последняя проверка замены: {last_rr}\n\n"
        f"<i>Время указано в UTC+3</i>"
    )


def export_text(total: str, premium: str, normal: str, file_format: str) -> str:
    return (
        f"📦 <b>Выгрузка пользователей</b>\n\n"
        f"👥 Всего пользователей: <b>{total}</b>\n"
        f"💎 Premium: <b>{premium}</b>\n"
        f"👤 Обычные: <b>{normal}</b>\n\n"
        f"📄 Формат: <b>{file_format.upper()}</b>\n\n"
        f"Формат полей:\n"
        f"<code>ID;Username;Язык;Premium;Дата регистрации;Start Param</code>"
    )


def broadcast_confirm_text(text: str, buttons_flag: str, scheduled_at_human: str) -> str:
    return (
        "📢 <b>Проверка рассылки</b>\n\n"
        f"📝 <b>Текст:</b>\n<blockquote>{text}</blockquote>\n\n"
        f"🔗 Кнопки: {buttons_flag}\n"
        f"⏳ Отправка: <b>{scheduled_at_human}</b> (UTC+3)\n\n"
        "Выберите действие:"
    )


def broadcast_created_text(broadcast_id: int, status: str, scheduled_at_human: str) -> str:
    return (
        "✅ <b>Рассылка создана</b>\n\n"
        f"🆔 ID: <code>{broadcast_id}</code>\n"
        f"📡 Статус: <b>{status}</b>\n"
        f"⏳ Отправка: <b>{scheduled_at_human}</b> (UTC+3)\n\n"
    )


def broadcast_detail_text(broadcast_id: int, status: str, scheduled_at_human: str, buttons_flag: str, text: str) -> str:
    return (
        "📨 <b>Рассылка</b>\n\n"
        f"🆔 ID: <code>{broadcast_id}</code>\n"
        f"📡 Статус: <b>{status}</b>\n"
        f"⏳ Отправка: <b>{scheduled_at_human}</b> (UTC+3)\n"
        f"🔗 Кнопки: {buttons_flag}\n\n"
        f"📝 <b>Текст:</b>\n<blockquote>{text or ''}</blockquote>"
    )
