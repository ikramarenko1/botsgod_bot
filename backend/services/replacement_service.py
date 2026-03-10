import os
import shutil
import logging
from collections import defaultdict
from datetime import datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, or_, func

from backend.models.bot import Bot, BotRole, BotStatus
from backend.models.bot_config import BotConfig
from backend.models.broadcast import Broadcast
from backend.models.bot_welcome import BotWelcome
from backend.models.delayed_message import DelayedMessage
from backend.models.replacement_log import ReplacementLog
from backend.models.user import BotUser
from backend.models.key import Key
from backend.services.telegram_service import set_webhook, apply_avatar
from backend.models.team import TeamMember
from backend.services.notification_service import notify_admin, notify_owner, notify_team_members

logger = logging.getLogger("stagecontrol")


async def run_replacement(db: AsyncSession, media_dir: str) -> dict:
    dead_result = await db.execute(
        select(Bot).where(
            Bot.role == BotRole.active,
            Bot.status == BotStatus.dead,
        )
    )
    dead_bots = dead_result.scalars().all()

    if not dead_bots:
        logger.info("Replacement: no dead active bots")
        return {"message": "No dead active bots"}

    replacements = []
    not_replaced = []

    valid_dead_bots = [b for b in dead_bots if b.team_id is not None]
    skipped = len(dead_bots) - len(valid_dead_bots)
    if skipped:
        logger.warning(f"Replacement: skipped {skipped} dead bots without team_id")

    dead_by_group = defaultdict(list)
    for bot in valid_dead_bots:
        dead_by_group[(bot.team_id, bot.key_id)].append(bot)

    all_key_ids = {kid for (_, kid) in dead_by_group.keys() if kid is not None}
    key_names = {}
    if all_key_ids:
        keys_result = await db.execute(select(Key).where(Key.id.in_(all_key_ids)))
        key_names = {k.id: k.short_name for k in keys_result.scalars().all()}

    logger.info(f"Replacement started: {len(dead_bots)} dead bots in {len(dead_by_group)} groups")

    http_tasks = []

    for (group_team_id, key_id), group_dead in dead_by_group.items():
        key_name = key_names.get(key_id) if key_id else None
        filters = [
            Bot.role == BotRole.reserve,
            Bot.status == BotStatus.alive,
            Bot.team_id == group_team_id,
        ]
        if key_id is not None:
            filters.append(Bot.key_id == key_id)
        else:
            filters.append(Bot.key_id.is_(None))

        reserve_result = await db.execute(select(Bot).where(*filters))
        group_reserves = reserve_result.scalars().all()

        pairs_count = min(len(group_dead), len(group_reserves))

        for i in range(pairs_count):
            dead_bot = group_dead[i]
            reserve_bot = group_reserves[i]
            dead_bot_username = dead_bot.username
            try:
                old_id = dead_bot.id
                new_id = reserve_bot.id

                existing_tg_ids = (await db.execute(
                    select(BotUser.telegram_id).where(BotUser.bot_id == old_id)
                )).scalars().all()
                if existing_tg_ids:
                    await db.execute(
                        delete(BotUser).where(
                            BotUser.bot_id == new_id,
                            BotUser.telegram_id.in_(existing_tg_ids),
                        )
                    )
                await db.execute(update(BotUser).where(BotUser.bot_id == old_id).values(bot_id=new_id))
                await db.execute(update(Broadcast).where(Broadcast.bot_id == old_id).values(bot_id=new_id))
                await db.execute(update(DelayedMessage).where(DelayedMessage.bot_id == old_id).values(bot_id=new_id))
                await db.execute(delete(BotWelcome).where(BotWelcome.bot_id == new_id))
                await db.execute(update(BotWelcome).where(BotWelcome.bot_id == old_id).values(bot_id=new_id))

                await db.execute(delete(BotConfig).where(BotConfig.bot_id == new_id))
                await db.execute(update(BotConfig).where(BotConfig.bot_id == old_id).values(bot_id=new_id))

                reserve_bot.delayed_text = dead_bot.delayed_text
                reserve_bot.delayed_buttons = dead_bot.delayed_buttons
                reserve_bot.delayed_delay_minutes = dead_bot.delayed_delay_minutes
                reserve_bot.delayed_photo_path = dead_bot.delayed_photo_path
                reserve_bot.auto_reply_text = dead_bot.auto_reply_text
                reserve_bot.last_applied_region = dead_bot.last_applied_region
                _applied_at = dead_bot.last_applied_at
                if _applied_at and _applied_at.tzinfo is not None:
                    _applied_at = _applied_at.replace(tzinfo=None)
                reserve_bot.last_applied_at = _applied_at

                reserve_bot.role = BotRole.active

                configs_result = await db.execute(
                    select(BotConfig).where(BotConfig.bot_id == reserve_bot.id)
                )
                configs = configs_result.scalars().all()
                config_payloads = []
                for cfg in configs:
                    payload_name = {"name": cfg.name}
                    payload_desc = {"description": cfg.description}
                    if cfg.region != "default":
                        payload_name["language_code"] = cfg.region
                        payload_desc["language_code"] = cfg.region
                    config_payloads.append((cfg.region, payload_name, payload_desc))

                has_avatar = False
                if dead_bot.avatar_path and os.path.exists(dead_bot.avatar_path):
                    new_bot_dir = os.path.join(media_dir, f"bot_{reserve_bot.id}")
                    os.makedirs(new_bot_dir, exist_ok=True)
                    new_avatar_path = os.path.join(new_bot_dir, "avatar.jpg")
                    shutil.copyfile(dead_bot.avatar_path, new_avatar_path)
                    reserve_bot.avatar_path = new_avatar_path
                    has_avatar = True

                welcome_result = await db.execute(
                    select(BotWelcome).where(BotWelcome.bot_id == reserve_bot.id)
                )
                welcome = welcome_result.scalar_one_or_none()
                if welcome and welcome.photo_path:
                    old_welcome_photo = welcome.photo_path
                    if os.path.exists(old_welcome_photo):
                        new_bot_dir = os.path.join(media_dir, f"bot_{reserve_bot.id}")
                        os.makedirs(new_bot_dir, exist_ok=True)
                        new_welcome_photo = os.path.join(new_bot_dir, os.path.basename(old_welcome_photo))
                        shutil.copyfile(old_welcome_photo, new_welcome_photo)
                        welcome.photo_path = new_welcome_photo

                if reserve_bot.delayed_photo_path:
                    old_delayed_photo = reserve_bot.delayed_photo_path
                    if os.path.exists(old_delayed_photo):
                        new_bot_dir = os.path.join(media_dir, f"bot_{reserve_bot.id}")
                        os.makedirs(new_bot_dir, exist_ok=True)
                        new_delayed_photo = os.path.join(new_bot_dir, os.path.basename(old_delayed_photo))
                        shutil.copyfile(old_delayed_photo, new_delayed_photo)
                        reserve_bot.delayed_photo_path = new_delayed_photo

                dead_username = dead_bot.username
                dead_token = dead_bot.token
                dead_team_id = dead_bot.team_id
                dead_owner_id = dead_bot.owner_telegram_id
                reserve_token = reserve_bot.token
                reserve_username = reserve_bot.username
                reserve_id = reserve_bot.id
                reserve_avatar_path = reserve_bot.avatar_path

                replacements.append({
                    "dead_bot_id": old_id,
                    "dead_bot_username": dead_username,
                    "new_active_id": reserve_id,
                    "new_active_username": reserve_username,
                    "key_name": key_name,
                })

                log = ReplacementLog(
                    dead_bot_id=old_id,
                    dead_bot_username=dead_username,
                    new_bot_id=reserve_id,
                    new_bot_username=reserve_username,
                    replaced_at=datetime.utcnow()
                )
                db.add(log)

                member_ids = []
                if dead_team_id:
                    members_result = await db.execute(
                        select(TeamMember.telegram_id).where(TeamMember.team_id == dead_team_id)
                    )
                    member_ids = members_result.scalars().all()

                old_media_dir = os.path.join(media_dir, f"bot_{old_id}")
                if os.path.exists(old_media_dir):
                    shutil.rmtree(old_media_dir)
                await db.delete(dead_bot)
                await db.flush()

                http_tasks.append({
                    "dead_token": dead_token,
                    "dead_username": dead_username,
                    "reserve_token": reserve_token,
                    "reserve_username": reserve_username,
                    "reserve_id": reserve_id,
                    "reserve_avatar_path": reserve_avatar_path,
                    "has_avatar": has_avatar,
                    "config_payloads": config_payloads,
                    "dead_team_id": dead_team_id,
                    "dead_owner_id": dead_owner_id,
                    "member_ids": member_ids,
                    "key_name": key_name,
                })

                logger.info(f"Replacement DB done: @{dead_username} -> @{reserve_username}")

            except Exception as e:
                logger.error(
                    f"Replacement failed for @{dead_bot_username}: {e}",
                    exc_info=True,
                )
                not_replaced.append({
                    "dead_bot_id": dead_bot.id,
                    "dead_bot_username": dead_bot_username,
                    "key_name": key_name,
                    "reason": "Replacement error"
                })

        if len(group_dead) > pairs_count:
            for dead_bot in group_dead[pairs_count:]:
                logger.warning(
                    f"No reserve available for @{dead_bot.username}"
                )
                not_replaced.append({
                    "dead_bot_id": dead_bot.id,
                    "dead_bot_username": dead_bot.username,
                    "key_name": key_name,
                    "reason": "No reserve available"
                })

    await db.commit()

    for task in http_tasks:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.telegram.org/bot{task['dead_token']}/deleteWebhook"
                )
        except Exception:
            pass

        applied_regions = []
        failed_regions = []
        for region, payload_name, payload_desc in task["config_payloads"]:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        f"https://api.telegram.org/bot{task['reserve_token']}/setMyName",
                        json=payload_name,
                    )
                    await client.post(
                        f"https://api.telegram.org/bot{task['reserve_token']}/setMyDescription",
                        json=payload_desc,
                    )
                applied_regions.append(region)
            except Exception as cfg_err:
                failed_regions.append(region)
                logger.error(
                    f"Failed to apply config region={region} "
                    f"for @{task['reserve_username']}: {cfg_err}"
                )

        if task["has_avatar"] and task["reserve_avatar_path"] and os.path.exists(task["reserve_avatar_path"]):
            dummy_bot = Bot(
                id=task["reserve_id"],
                token=task["reserve_token"],
                username=task["reserve_username"],
                avatar_path=task["reserve_avatar_path"],
            )
            try:
                await apply_avatar(dummy_bot)
            except Exception as e:
                logger.error(f"Failed to apply avatar for @{task['reserve_username']}: {e}")

        try:
            dummy_bot = Bot(
                id=task["reserve_id"],
                token=task["reserve_token"],
                username=task["reserve_username"],
            )
            await set_webhook(dummy_bot)
        except Exception as e:
            logger.error(f"Failed to set webhook for @{task['reserve_username']}: {e}")

        parts = [f"@{task['dead_username']} -> @{task['reserve_username']}"]
        if applied_regions:
            parts.append(f"{len(applied_regions)} configs applied")
        if failed_regions:
            parts.append(f"{len(failed_regions)} configs failed")
        if task["has_avatar"]:
            parts.append("avatar copied")
        logger.info(f"Replaced: {', '.join(parts)}")

        try:
            key_name = task["key_name"]
            key_line = f"▫️ Ключ: 🔑 {key_name}\n" if key_name else ""
            notify_text = (
                f"🔄 <b>Замена бота</b>\n\n"
                f"Бот @{task['dead_username']} перестал отвечать и был автоматически заменён.\n\n"
                f"{key_line}"
                f"▫️ Старый бот: @{task['dead_username']}\n"
                f"▫️ Новый бот: @{task['reserve_username']}\n"
                f"▫️ Время: {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC"
            )
            notify_markup = {
                "inline_keyboard": [[{
                    "text": "⚙️ Управление ботом",
                    "callback_data": f"bot_{task['reserve_id']}"
                }]]
            }
            if task["member_ids"]:
                await notify_team_members(task["member_ids"], notify_text, notify_markup)
            else:
                await notify_owner(task["dead_owner_id"], notify_text, notify_markup)
        except Exception as notify_err:
            logger.error(f"Failed to notify about replacement: {notify_err}")

    logger.info(
        f"Replacement finished. Success: {len(replacements)}, Not replaced: {len(not_replaced)}"
    )

    text = "🔄 Массовая замена ботов\n\n"

    if replacements:
        text += "✅ Успешные замены:\n"
        for r in replacements:
            key_tag = f" [🔑 {r['key_name']}]" if r.get('key_name') else ""
            text += (
                f"• @{r['dead_bot_username']} → "
                f"@{r['new_active_username']}{key_tag}\n"
            )

    if not_replaced:
        text += "\n❗ Не заменены:\n"
        for r in not_replaced:
            key_tag = f" [🔑 {r['key_name']}]" if r.get('key_name') else ""
            text += f"• @{r['dead_bot_username']} ({r['reason']}){key_tag}\n"

    await notify_admin(text)

    return {
        "replaced_count": len(replacements),
        "not_replaced_count": len(not_replaced),
        "replacements": replacements,
        "not_replaced": not_replaced,
    }


async def get_replacement_logs_all(db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(ReplacementLog).order_by(ReplacementLog.replaced_at.desc())
    )

    logs = result.scalars().all()

    return [
        {
            "dead_bot": log.dead_bot_username,
            "new_bot": log.new_bot_username,
            "replaced_at": log.replaced_at,
        }
        for log in logs
    ]


async def get_replacement_logs_for_bot(db: AsyncSession, bot_id: int, page: int, per_page: int) -> dict:
    base_filter = or_(
        ReplacementLog.dead_bot_id == bot_id,
        ReplacementLog.new_bot_id == bot_id,
    )

    total = (
        await db.execute(
            select(func.count()).select_from(ReplacementLog).where(base_filter)
        )
    ).scalar() or 0

    result = await db.execute(
        select(ReplacementLog)
        .where(base_filter)
        .order_by(ReplacementLog.replaced_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    logs = result.scalars().all()

    return {
        "logs": [
            {
                "id": log.id,
                "dead_bot_id": log.dead_bot_id,
                "dead_bot_username": log.dead_bot_username,
                "new_bot_id": log.new_bot_id,
                "new_bot_username": log.new_bot_username,
                "replaced_at": log.replaced_at.isoformat() if log.replaced_at else None,
            }
            for log in logs
        ],
        "total": total,
        "page": page,
    }
