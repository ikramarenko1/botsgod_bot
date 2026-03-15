from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from controller.config import LANG_REGIONS

BOTS_PER_PAGE = 10


main_reply_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Меню")]],
    resize_keyboard=True,
)


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Мои ключи", callback_data="my_keys")],
            [InlineKeyboardButton(text="🔎 Мои боты", callback_data="my_bots")],
            [InlineKeyboardButton(text="⚙️ Глобальные конфиги", callback_data="global_configs")],
            [InlineKeyboardButton(text="👥 Моя команда", callback_data="my_team")],
            [InlineKeyboardButton(text="🧠 Статус Worker", callback_data="worker_status")],
            [InlineKeyboardButton(text="🔄 Синхронизировать вебхуки", callback_data="sync_webhooks")],
        ]
    )


def _pagination_row(prefix: str, page: int, total_pages: int) -> list[InlineKeyboardButton]:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{prefix}_page_{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{prefix}_page_{page + 1}"))
    return nav


def bots_checkbox_keyboard(
    prefix: str,
    bots: list,
    selected_ids: set,
    back_callback: str = "back_to_main",
    show_role_filters: bool = False,
    page: int = 0,
) -> InlineKeyboardMarkup:
    rows = []

    if show_role_filters:
        rows.append([
            InlineKeyboardButton(text="☑️ Выбрать все", callback_data=f"{prefix}_select_all"),
        ])
        rows.append([
            InlineKeyboardButton(text="🟢 Все активные", callback_data=f"{prefix}_select_active"),
            InlineKeyboardButton(text="🔄 Все фарм", callback_data=f"{prefix}_select_farm"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="☑️ Выбрать все", callback_data=f"{prefix}_select_all"),
        ])

    total_pages = max(1, (len(bots) + BOTS_PER_PAGE - 1) // BOTS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    page_bots = bots[page * BOTS_PER_PAGE : (page + 1) * BOTS_PER_PAGE]

    for bot in page_bots:
        bot_id = bot["id"]
        check = "✅" if bot_id in selected_ids else "⬜"
        role = bot.get("role", "")
        role_icons = {"active": "🟢", "reserve": "🟠", "farm": "🔄", "disabled": "⛔"}
        icon = role_icons.get(role, "")
        label = f"{check} {icon} @{bot['username']}" if icon else f"{check} @{bot['username']}"
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"{prefix}_toggle_{bot_id}"
            )
        ])

    if total_pages > 1:
        rows.append(_pagination_row(prefix, page, total_pages))

    rows.append([
        InlineKeyboardButton(text="✅ Готово", callback_data=f"{prefix}_done"),
        InlineKeyboardButton(text="♻️ Сброс", callback_data=f"{prefix}_reset"),
    ])
    rows.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def gc_region_picker_keyboard(config_id: str, already_added_codes: set[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    groups = {"cis": "СНГ", "west": "Запад", "asia": "Азия"}
    for group_key, group_title in groups.items():
        group_items = [item for item in LANG_REGIONS if item["group"] == group_key]
        grid = []
        for item in group_items:
            code = item["code"]
            flag = item["flag"]
            if code in already_added_codes:
                grid.append(InlineKeyboardButton(text=f"✅ {flag}", callback_data="noop"))
            else:
                grid.append(InlineKeyboardButton(text=flag, callback_data=f"gcr_{config_id}_{code}"))
        for i in range(0, len(grid), 3):
            rows.append(grid[i:i+3])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"gc_{config_id}_regions")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
