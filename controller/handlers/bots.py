import httpx
from aiogram import Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

from controller.config import BACKEND_URL
from controller.common import backend_request, safe_edit, owner_headers
from controller.utils import parse_utc_iso, UTC3_OFFSET
from controller.render import render_bot_menu
from controller.messages import stats_text, replacement_logs_text, export_text

router = Router()


@router.callback_query(lambda c: c.data.startswith("bot_") and "_" not in c.data[4:])
async def bot_manage_handler(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    await render_bot_menu(callback.message, owner_id, bot_id, edit=True)
    await callback.answer()


@router.callback_query(lambda c: c.data.endswith("_stats"))
async def bot_stats_handler(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    await safe_edit(callback.message, "⏳ Загружаю статистику...")

    try:
        stats = await backend_request(
            "GET",
            f"/bots/{bot_id}/stats",
            telegram_id=owner_id,
        )

        bots = await backend_request(
            "GET",
            "/bots",
            telegram_id=owner_id,
        )
    except Exception:
        await safe_edit(callback.message, "❌ Ошибка загрузки статистики.")
        await callback.answer()
        return

    bot_username = next(
        (b["username"] for b in bots if str(b["id"]) == bot_id),
        ""
    )

    total = stats.get("total_users", 0)
    premium = stats.get("premium_users", 0)
    normal = stats.get("normal_users", 0)

    premium_percent = round((premium / total) * 100, 1) if total else 0
    normal_percent = round((normal / total) * 100, 1) if total else 0

    geo = stats.get("geo", {})

    geo_lines = ""
    if geo:
        for code, count in geo.items():
            percent = round((count / total) * 100, 1) if total else 0
            geo_lines += f"{code.upper()}: {count} ({percent}%)\n"
    else:
        geo_lines = "Нет данных\n"

    text = stats_text(
        bot_username, total, premium, normal,
        premium_percent, normal_percent, geo_lines,
        stats.get('growth_hour', 0),
        stats.get('growth_day', 0),
        stats.get('growth_week', 0),
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"bot_{bot_id}_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data=f"bot_{bot_id}"
                )
            ],
        ]
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        await callback.message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_replacement_logs"))
async def replacement_logs_handler(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    try:
        data = await backend_request(
            "GET",
            f"/bots/{bot_id}/replacement-logs",
            telegram_id=owner_id,
        )
    except Exception:
        await safe_edit(callback.message, "❌ Ошибка загрузки логов замены.")
        await callback.answer()
        return

    logs = data.get("logs", [])
    total = data.get("total", 0)

    bots = await backend_request("GET", "/bots", telegram_id=owner_id)
    bot_username = next((b["username"] for b in bots if str(b["id"]) == bot_id), "")

    lines = []
    for log in logs:
        replaced_at = log.get("replaced_at", "—")
        if replaced_at and "T" in str(replaced_at):
            try:
                dt = parse_utc_iso(replaced_at)
                replaced_at = (dt + UTC3_OFFSET).strftime("%d.%m.%Y %H:%M")
            except Exception:
                pass
        lines.append(
            f"▫️ @{log['dead_bot_username']} → @{log['new_bot_username']}\n"
            f"   📅 {replaced_at} (UTC+3)"
        )
    text = replacement_logs_text(bot_username, logs, total, lines)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"bot_{bot_id}_replacement_logs")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")],
        ]
    )

    await safe_edit(callback.message, text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_disable"))
async def bot_disable(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    try:
        await backend_request(
            "PATCH",
            f"/bots/{bot_id}/disable",
            telegram_id=owner_id,
            with_api_key=True
        )
    except Exception:
        await callback.answer("❌ Ошибка выключения", show_alert=True)
        return

    await callback.answer("⛔ Бот выключен")
    await render_bot_menu(callback.message, owner_id, bot_id, edit=True)


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_enable"))
async def bot_enable(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    try:
        await backend_request(
            "PATCH",
            f"/bots/{bot_id}/enable",
            telegram_id=owner_id,
            with_api_key=True
        )
    except Exception:
        await callback.answer("❌ Ошибка включения", show_alert=True)
        return

    await callback.answer("✅ Бот включён")
    await render_bot_menu(callback.message, owner_id, bot_id, edit=True)


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_export_users"))
async def export_users_menu(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 TXT", callback_data=f"export_{bot_id}_txt"),
                InlineKeyboardButton(text="📊 CSV", callback_data=f"export_{bot_id}_csv"),
            ],
            [
                InlineKeyboardButton(text="🧾 JSON", callback_data=f"export_{bot_id}_json"),
                InlineKeyboardButton(text="⬅️ Назад", callback_data=f"bot_{bot_id}")
            ],
        ]
    )

    await safe_edit(
        callback.message,
        "📦 <b>Выгрузка пользователей</b>\n\nВыберите формат:",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("export_") and c.data.count("_") >= 2)
async def export_users_file(callback):
    owner_id = callback.from_user.id
    parts = callback.data.split("_")

    bot_id = parts[1]
    file_format = parts[2]

    await callback.answer("⏳ Формирую файл...")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{BACKEND_URL}/bots/{bot_id}/users/export",
                params={"format": file_format},
                headers=owner_headers(owner_id, with_api_key=True),
            )

        response.raise_for_status()

    except Exception as e:
        print("EXPORT ERROR:", e)
        await callback.message.answer("❌ Ошибка при выгрузке.")
        return

    content_disposition = response.headers.get("Content-Disposition", "")
    filename = f"users.{file_format}"

    if "filename=" in content_disposition:
        filename = content_disposition.split("filename=")[-1].strip('"')

    total_users = response.headers.get("X-Total-Users", "—")
    premium_users = response.headers.get("X-Premium-Users", "—")
    normal_users = response.headers.get("X-Normal-Users", "—")

    await callback.message.answer(
        export_text(total_users, premium_users, normal_users, file_format),
        parse_mode="HTML"
    )

    file = BufferedInputFile(
        response.content,
        filename=filename
    )

    await callback.message.answer_document(document=file)
    await callback.answer("✅ Файл выгрузки готов!")


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_delete"))
async def bot_delete_confirm(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"bot_{bot_id}_delete_confirm"
                )
            ],
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data=f"bot_{bot_id}"
                )
            ],
        ]
    )

    await safe_edit(
        callback.message,
        "⚠️ <b>Вы уверены, что хотите удалить бота?</b>\n\n"
        "Это действие нельзя отменить.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("bot_") and c.data.endswith("_delete_confirm"))
async def bot_delete_execute(callback):
    owner_id = callback.from_user.id
    bot_id = callback.data.split("_")[1]

    try:
        await backend_request(
            "DELETE",
            f"/bots/{bot_id}",
            telegram_id=owner_id,
            with_api_key=True
        )
    except Exception:
        await callback.answer("❌ Ошибка удаления", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data="my_bots"
                )
            ]
        ]
    )

    await safe_edit(
        callback.message,
        "✅ <b>Бот успешно удалён</b>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    await callback.answer("Удалено")
