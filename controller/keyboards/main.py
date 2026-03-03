from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from controller.config import LANG_REGIONS


main_reply_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Меню")]],
    resize_keyboard=True,
    is_persistent=True,
)


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Мои боты", callback_data="my_bots")],
            [InlineKeyboardButton(text="➕ Добавить бота", callback_data="add_bot")],
            [InlineKeyboardButton(text="🧠 Статус Worker", callback_data="worker_status")],
        ]
    )


def _regions_keyboard(bot_id: str, selected: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="СНГ", callback_data=f"rename_{bot_id}_geo_group_cis"),
            InlineKeyboardButton(text="Запад", callback_data=f"rename_{bot_id}_geo_group_west"),
            InlineKeyboardButton(text="Азия", callback_data=f"rename_{bot_id}_geo_group_asia"),
        ],
        [InlineKeyboardButton(text="🌍 На все регионы", callback_data=f"rename_{bot_id}_geo_all")],
    ]

    grid = []
    for item in LANG_REGIONS:
        code = item["code"]
        flag = item["flag"]
        is_on = code in selected
        txt = f"✅ {flag}" if is_on else flag
        grid.append(InlineKeyboardButton(text=txt, callback_data=f"rename_{bot_id}_geo_t_{code}"))

    for i in range(0, len(grid), 3):
        rows.append(grid[i:i+3])

    rows.append([
        InlineKeyboardButton(text="✅ Готово", callback_data=f"rename_{bot_id}_geo_done"),
        InlineKeyboardButton(text="♻️ Сброс", callback_data=f"rename_{bot_id}_geo_reset"),
    ])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=f"rename_{bot_id}_geo_back"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)
