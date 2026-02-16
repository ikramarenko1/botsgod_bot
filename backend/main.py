from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from datetime import datetime, timedelta
import httpx
from typing import List

from backend.db.session import get_db

from backend.models.bot import Bot, BotRole, BotStatus
from backend.schemas.bot import BotAddRequest, BotResponse, BotRoleUpdateRequest, BotStatusUpdate, BotApplyConfigRequest

from backend.models.bot_config import BotConfig
from backend.schemas.bot_config import BotConfigCreate, BotConfigResponse

from backend.models.broadcast import Broadcast, BroadcastStatus
from backend.schemas.broadcast import BroadcastResponse, BroadcastCreateRequest, BroadcastStatusUpdate, BroadcastScheduleUpdate

from backend.models.bot_welcome import BotWelcome
from backend.schemas.bot_welcome import WelcomeCreateRequest, WelcomeResponse

from backend.models.delayed_message import DelayedMessage, DelayedStatus
from backend.schemas.delayed_message import DelayedConfigRequest

from backend.models.user import BotUser

app = FastAPI(title="StageControl Backend")

# ===== GET =====
@app.get("/")
async def health():
    return {"status": "ok"}


@app.get("/bots", response_model=List[BotResponse])
async def list_bots(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Bot))
    bots = result.scalars().all()

    return [
        BotResponse(
            id=b.id,
            username=b.username,
            role=b.role.value,
            status=b.status.value,
        )
        for b in bots
    ]


@app.get("/bots/{bot_id}/configs", response_model=list[BotConfigResponse])
async def list_bot_configs(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BotConfig).where(BotConfig.bot_id == bot_id)
    )
    return result.scalars().all()


@app.get(
    "/bots/{bot_id}/broadcasts",
    response_model=list[BroadcastResponse],
)
async def list_broadcasts(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Broadcast).where(Broadcast.bot_id == bot_id)
    )
    broadcasts = result.scalars().all()

    return [
        BroadcastResponse(
            id=b.id,
            bot_id=b.bot_id,
            region=b.region,
            text=b.text,
            buttons=b.buttons,
            status=b.status.value,

            total_users=b.total_users,
            sent_count=b.sent_count,
            failed_count=b.failed_count,
            started_at=b.started_at,
            finished_at=b.finished_at,
            scheduled_at=b.scheduled_at,
        )
        for b in broadcasts
    ]


@app.get("/bots/{bot_id}/users")
async def list_bot_users(bot_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(BotUser).where(BotUser.bot_id == bot_id, BotUser.is_active == True)
    )
    users = result.scalars().all()

    return [
        {
            "id": u.id,
            "telegram_id": u.telegram_id,
        }
        for u in users
    ]


@app.get("/broadcasts/scheduled")
async def get_scheduled(db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()

    result = await db.execute(
        select(Broadcast, Bot)
        .join(Bot, Broadcast.bot_id == Bot.id)
        .where(
            Broadcast.status == BroadcastStatus.scheduled,
            or_(
                Broadcast.scheduled_at == None,
                Broadcast.scheduled_at <= now
            )
        )
    )

    rows = result.all()

    return [
        {
            "id": broadcast.id,
            "bot_id": broadcast.bot_id,
            "text": broadcast.text,
            "buttons": broadcast.buttons,
            "token": bot.token,
        }
        for broadcast, bot in rows
    ]


@app.get("/bots/{bot_id}/stats")
async def bot_stats(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
):
    bot = await db.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)

    # === USERS ===
    total_users_result = await db.execute(
        select(func.count()).select_from(BotUser)
        .where(BotUser.bot_id == bot_id)
    )
    total_users = total_users_result.scalar() or 0

    active_users_result = await db.execute(
        select(func.count()).select_from(BotUser)
        .where(
            BotUser.bot_id == bot_id,
            BotUser.last_seen_at >= last_24h,
        )
    )
    active_last_24h = active_users_result.scalar() or 0

    # === BROADCASTS ===
    total_broadcasts_result = await db.execute(
        select(func.count()).select_from(Broadcast)
        .where(Broadcast.bot_id == bot_id)
    )
    total_broadcasts = total_broadcasts_result.scalar() or 0

    sent_result = await db.execute(
        select(func.count()).select_from(Broadcast)
        .where(
            Broadcast.bot_id == bot_id,
            Broadcast.status == BroadcastStatus.sent,
        )
    )
    sent_broadcasts = sent_result.scalar() or 0

    failed_result = await db.execute(
        select(func.count()).select_from(Broadcast)
        .where(
            Broadcast.bot_id == bot_id,
            Broadcast.status == BroadcastStatus.failed,
        )
    )
    failed_broadcasts = failed_result.scalar() or 0

    draft_result = await db.execute(
        select(func.count()).select_from(Broadcast)
        .where(
            Broadcast.bot_id == bot_id,
            Broadcast.status == BroadcastStatus.draft,
        )
    )
    draft_broadcasts = draft_result.scalar() or 0

    return {
        "total_users": total_users,
        "active_last_24h": active_last_24h,
        "total_broadcasts": total_broadcasts,
        "sent_broadcasts": sent_broadcasts,
        "failed_broadcasts": failed_broadcasts,
        "draft_broadcasts": draft_broadcasts,
    }


@app.get("/bots/{bot_id}/welcome", response_model=WelcomeResponse)
async def get_welcome(bot_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(BotWelcome).where(BotWelcome.bot_id == bot_id)
    )
    welcome = result.scalar_one_or_none()

    if not welcome:
        raise HTTPException(404, "Welcome message not set")

    return welcome


@app.get("/delayed/pending")
async def get_pending_delayed(db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()

    result = await db.execute(
        select(DelayedMessage, Bot, BotUser)
        .join(Bot, DelayedMessage.bot_id == Bot.id)
        .join(BotUser, DelayedMessage.user_id == BotUser.id)
        .where(
            DelayedMessage.status == DelayedStatus.pending,
            DelayedMessage.send_at <= now,
        )
    )

    rows = result.all()

    return [
        {
            "id": msg.id,
            "telegram_id": user.telegram_id,
            "text": msg.text,
            "buttons": msg.buttons,
            "token": bot.token,
        }
        for msg, bot, user in rows
    ]


# ===== POST =====
@app.post("/bots/add", response_model=BotResponse)
async def add_bot(
    data: BotAddRequest,
    db: AsyncSession = Depends(get_db),
):
    # проверка токена бота
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.telegram.org/bot{data.token}/getMe",
            timeout=10,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Invalid bot token")

    payload = resp.json()
    if not payload.get("ok"):
        raise HTTPException(status_code=400, detail="Invalid bot token")

    tg_bot = payload["result"]
    username = tg_bot["username"]

    # проверка, есть ли такой бот уже в бд
    existing = await db.execute(select(Bot).where(Bot.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Bot already exists")

    bot = Bot(
        username=username,
        token=data.token,
        role=BotRole.reserve,
        status=BotStatus.alive,
    )

    db.add(bot)
    await db.commit()
    await db.refresh(bot)

    return BotResponse(
        id=bot.id,
        username=bot.username,
        role=bot.role.value,
        status=bot.status.value,
    )


@app.post("/bots/{bot_id}/health-check", response_model=BotResponse)
async def health_check_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Bot).where(Bot.id == bot_id))
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{bot.token}/getMe"
            )

        if resp.status_code != 200 or not resp.json().get("ok"):
            bot.status = BotStatus.dead
        else:
            bot.status = BotStatus.alive

    except httpx.TimeoutException:
        bot.status = BotStatus.degraded

    await db.commit()
    await db.refresh(bot)

    return BotResponse(
        id=bot.id,
        username=bot.username,
        role=bot.role.value,
        status=bot.status.value,
    )


@app.post("/bots/health-check/all")
async def health_check_all(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Bot).where(Bot.role.in_([BotRole.active, BotRole.reserve]))
    )
    bots = result.scalars().all()

    checked = []

    for bot in bots:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{bot.token}/getMe"
                )

            if resp.status_code != 200 or not resp.json().get("ok"):
                bot.status = BotStatus.dead
            else:
                bot.status = BotStatus.alive

        except httpx.TimeoutException:
            bot.status = BotStatus.degraded

        checked.append({
            "id": bot.id,
            "username": bot.username,
            "role": bot.role.value,
            "status": bot.status.value,
        })

    await db.commit()
    return {"checked": checked}


@app.post("/bots/replacement")
async def replacement(db: AsyncSession = Depends(get_db)):
    # ищу мертвых active
    result = await db.execute(
        select(Bot).where(
            Bot.role == BotRole.active,
            Bot.status == BotStatus.dead,
        )
    )
    dead_actives = result.scalars().all()

    if not dead_actives:
        return {"message": "No dead active bots"}

    replaced = []

    for dead_bot in dead_actives:
        # ищу живого reserve
        reserve_result = await db.execute(
            select(Bot).where(
                Bot.role == BotRole.reserve,
                Bot.status == BotStatus.alive,
            )
        )
        reserve_bot = reserve_result.scalars().first()

        if not reserve_bot:
            replaced.append({
                "dead_bot": dead_bot.username,
                "status": "no_reserve_available",
            })
            continue

        # меняю роли
        dead_bot.role = BotRole.disabled
        reserve_bot.role = BotRole.active

        replaced.append({
            "dead_bot": dead_bot.username,
            "new_active": reserve_bot.username,
        })

    await db.commit()

    return {
        "replacements": replaced
    }


@app.post("/bots/{bot_id}/configs", response_model=BotConfigResponse)
async def upsert_bot_config(
    bot_id: int,
    data: BotConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    bot = await db.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    result = await db.execute(
        select(BotConfig).where(
            BotConfig.bot_id == bot_id,
            BotConfig.region == data.region,
        )
    )
    config = result.scalar_one_or_none()

    if config:
        config.name = data.name
        config.description = data.description
    else:
        config = BotConfig(
            bot_id=bot_id,
            region=data.region,
            name=data.name,
            description=data.description,
        )
        db.add(config)

    await db.commit()
    await db.refresh(config)
    return config


@app.post("/bots/{bot_id}/configs/apply")
async def apply_bot_config(
    bot_id: int,
    data: BotApplyConfigRequest,
    db: AsyncSession = Depends(get_db),
):

    result = await db.execute(select(Bot).where(Bot.id == bot_id))
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    result = await db.execute(
        select(BotConfig).where(
            BotConfig.bot_id == bot_id,
            BotConfig.region == data.region,
        )
    )
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"Config for region '{data.region}' not found",
        )

    async with httpx.AsyncClient(timeout=10) as client:
        # setMyName
        resp_name = await client.post(
            f"https://api.telegram.org/bot{bot.token}/setMyName",
            json={"name": config.name},
        )

        if resp_name.status_code != 200 or not resp_name.json().get("ok"):
            raise HTTPException(
                status_code=502,
                detail="Failed to set bot name in Telegram",
            )

        # setMyDescription
        resp_desc = await client.post(
            f"https://api.telegram.org/bot{bot.token}/setMyDescription",
            json={"description": config.description},
        )

        if resp_desc.status_code != 200 or not resp_desc.json().get("ok"):
            raise HTTPException(
                status_code=502,
                detail="Failed to set bot description in Telegram",
            )

    bot.last_applied_region = data.region
    bot.last_applied_at = datetime.utcnow()

    await db.commit()
    await db.refresh(bot)

    return {
        "bot_id": bot.id,
        "username": bot.username,
        "applied_region": data.region,
        "applied_at": bot.last_applied_at,
    }


@app.post(
    "/bots/{bot_id}/broadcasts",
    response_model=BroadcastResponse,
)
async def create_broadcast(
    bot_id: int,
    data: BroadcastCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Bot).where(Bot.id == bot_id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(404, "Bot not found")

    broadcast = Broadcast(
        bot_id=bot_id,
        region=data.region,
        text=data.text,
        buttons=data.buttons,
        scheduled_at=data.scheduled_at,
    )

    db.add(broadcast)
    await db.commit()
    await db.refresh(broadcast)

    return BroadcastResponse(
        id=broadcast.id,
        bot_id=broadcast.bot_id,
        region=broadcast.region,
        text=broadcast.text,
        buttons=broadcast.buttons,
        status=broadcast.status.value,
    )


@app.post("/webhooks/{bot_id}")
async def telegram_webhook(
    bot_id: int,
    update: dict,
    db: AsyncSession = Depends(get_db),
):
    message = update.get("message") or update.get("callback_query", {}).get("message")

    if not message:
        return {"status": "ignored"}

    user_data = message.get("from")
    if not user_data:
        return {"status": "no_user"}

    telegram_id = user_data["id"]

    # проверяю, есть ли уже такой пользователь
    result = await db.execute(
        select(BotUser).where(
            BotUser.bot_id == bot_id,
            BotUser.telegram_id == telegram_id,
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        user = BotUser(
            bot_id=bot_id,
            telegram_id=telegram_id,
            username=user_data.get("username"),
            first_name=user_data.get("first_name"),
            last_name=user_data.get("last_name"),
            created_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
        db.add(user)
    else:
        user.last_seen_at = datetime.utcnow()

    await db.commit()

    bot = await db.get(Bot, bot_id)

    # если это /start - отправляю welcome message
    if message.get("text") == "/start":
        if bot.delayed_text and bot.delayed_delay_minutes:
            existing_delayed = await db.execute(
                select(DelayedMessage).where(
                    DelayedMessage.bot_id == bot_id,
                    DelayedMessage.user_id == user.id,
                    DelayedMessage.status == DelayedStatus.pending,
                )
            )

            if not existing_delayed.scalar_one_or_none():
                send_time = datetime.utcnow() + timedelta(
                    minutes=bot.delayed_delay_minutes
                )

                delayed = DelayedMessage(
                    bot_id=bot_id,
                    user_id=user.id,
                    text=bot.delayed_text,
                    buttons=bot.delayed_buttons,
                    send_at=send_time,
                )

                db.add(delayed)
                await db.commit()

        result = await db.execute(
            select(BotWelcome).where(
                BotWelcome.bot_id == bot_id,
                BotWelcome.is_enabled == True,
            )
        )
        welcome = result.scalar_one_or_none()

        if welcome:
            payload = {
                "chat_id": telegram_id,
            }

            if welcome.photo_file_id:
                payload["photo"] = welcome.photo_file_id
                payload["caption"] = welcome.text
                method = "sendPhoto"
            else:
                payload["text"] = welcome.text
                method = "sendMessage"

            if welcome.buttons:
                payload["reply_markup"] = {
                    "inline_keyboard": [
                        [{"text": b["text"], "url": b["url"]}]
                        for b in welcome.buttons
                    ]
                }

            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{bot.token}/{method}",
                    json=payload,
                )

    return {"status": "ok"}


@app.post("/bots/{bot_id}/welcome", response_model=WelcomeResponse)
async def upsert_welcome(
    bot_id: int,
    data: WelcomeCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BotWelcome).where(BotWelcome.bot_id == bot_id)
    )
    welcome = result.scalar_one_or_none()

    if welcome:
        welcome.text = data.text
        welcome.photo_file_id = data.photo_file_id
        welcome.buttons = data.buttons
        welcome.is_enabled = data.is_enabled
    else:
        welcome = BotWelcome(
            bot_id=bot_id,
            text=data.text,
            photo_file_id=data.photo_file_id,
            buttons=data.buttons,
            is_enabled=data.is_enabled,
        )
        db.add(welcome)

    await db.commit()
    await db.refresh(welcome)

    return welcome


@app.post("/bots/{bot_id}/delayed")
async def set_delayed_message(
    bot_id: int,
    data: DelayedConfigRequest,
    db: AsyncSession = Depends(get_db),
):
    bot = await db.get(Bot, bot_id)
    if not bot:
        raise HTTPException(404, "Bot not found")

    bot.delayed_text = data.text
    bot.delayed_buttons = data.buttons
    bot.delayed_delay_minutes = data.delay_minutes

    await db.commit()

    return {"status": "configured"}


# ===== PATCH =====
@app.patch("/bots/{bot_id}/role", response_model=BotResponse)
async def update_bot_role(
    bot_id: int,
    data: BotRoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    if data.role not in ("active", "reserve", "disabled"):
        raise HTTPException(status_code=400, detail="Invalid role")

    result = await db.execute(select(Bot).where(Bot.id == bot_id))
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    bot.role = BotRole(data.role)
    await db.commit()
    await db.refresh(bot)

    return BotResponse(
        id=bot.id,
        username=bot.username,
        role=bot.role.value,
        status=bot.status.value,
    )


@app.patch("/bots/{bot_id}/status", response_model=BotResponse)
async def update_bot_status(
    bot_id: int,
    data: BotStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Bot).where(Bot.id == bot_id))
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    bot.status = BotStatus(data.status)
    await db.commit()
    await db.refresh(bot)

    return BotResponse(
        id=bot.id,
        username=bot.username,
        role=bot.role.value,
        status=bot.status.value,
    )


@app.patch("/broadcasts/{broadcast_id}/status")
async def update_broadcast_status(
    broadcast_id: int,
    data: BroadcastStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Broadcast).where(Broadcast.id == broadcast_id)
    )
    broadcast = result.scalar_one_or_none()

    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    current = broadcast.status.value
    new = data.status

    allowed_transitions = {
        "draft": ["scheduled", "cancelled"],
        "scheduled": ["sending", "cancelled"],
        "sending": ["sent", "failed"],
        "failed": ["scheduled"],
        "sent": [],
        "cancelled": [],
    }

    if new not in allowed_transitions[current]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change status from {current} to {new}",
        )

    broadcast.status = BroadcastStatus(new)

    await db.commit()
    await db.refresh(broadcast)

    return {
        "id": broadcast.id,
        "status": broadcast.status.value,
    }


@app.patch("/broadcasts/{broadcast_id}/stats")
async def update_broadcast_stats(
    broadcast_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Broadcast).where(Broadcast.id == broadcast_id)
    )
    broadcast = result.scalar_one_or_none()

    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    if "total_users" in data:
        broadcast.total_users = data["total_users"]

    if "sent_count" in data:
        broadcast.sent_count = data["sent_count"]

    if "failed_count" in data:
        broadcast.failed_count = data["failed_count"]

    if "started_at" in data:
        broadcast.started_at = datetime.utcnow()

    if "finished_at" in data:
        broadcast.finished_at = datetime.utcnow()

    await db.commit()
    await db.refresh(broadcast)

    return {"status": "ok"}


@app.patch("/broadcasts/{broadcast_id}/schedule")
async def update_broadcast_schedule(
    broadcast_id: int,
    data: BroadcastScheduleUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Broadcast).where(Broadcast.id == broadcast_id)
    )
    broadcast = result.scalar_one_or_none()

    if not broadcast:
        raise HTTPException(status_code=404, detail="Broadcast not found")

    if broadcast.status not in (
        BroadcastStatus.draft,
        BroadcastStatus.scheduled,
    ):
        raise HTTPException(
            status_code=400,
            detail="Can edit schedule only for draft or scheduled broadcasts",
        )

    broadcast.scheduled_at = data.scheduled_at

    # если было draft → автоматически делаю scheduled
    if broadcast.status == BroadcastStatus.draft:
        broadcast.status = BroadcastStatus.scheduled

    await db.commit()
    await db.refresh(broadcast)

    return {
        "id": broadcast.id,
        "status": broadcast.status.value,
        "scheduled_at": broadcast.scheduled_at,
    }


@app.patch("/delayed/{msg_id}/sent")
async def mark_delayed_sent(msg_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DelayedMessage).where(DelayedMessage.id == msg_id)
    )
    msg = result.scalar_one_or_none()

    if not msg:
        raise HTTPException(404, "Delayed message not found")

    msg.status = DelayedStatus.sent
    await db.commit()

    return {"status": "ok"}