from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from backend.db.session import get_db
from backend.models.bot import Bot
from backend.models.broadcast import Broadcast, BroadcastStatus
from backend.schemas.broadcast import (
    BroadcastResponse,
    BroadcastCreateRequest,
    BroadcastStatusUpdate,
    BroadcastScheduleUpdate,
)
from backend.utils.auth import verify_api_key, get_owner_id, get_owned_bot, get_owned_broadcast
from backend.services.broadcast_service import (
    get_scheduled_broadcasts,
    create_broadcast as svc_create_broadcast,
    send_broadcast_now as svc_send_broadcast_now,
)

router = APIRouter()


@router.get(
    "/bots/{bot_id}/broadcasts",
    response_model=list[BroadcastResponse],
)
async def list_broadcasts(
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Broadcast).where(Broadcast.bot_id == bot.id)
    )
    broadcasts = result.scalars().all()

    return [
        BroadcastResponse(
            id=b.id,
            bot_id=b.bot_id,
            region=b.region,
            text=b.text,
            buttons=b.buttons,
            bot_ids=b.bot_ids,
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


@router.get("/broadcasts/scheduled")
async def get_scheduled(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    return await get_scheduled_broadcasts(db)


@router.post(
    "/bots/{bot_id}/broadcasts",
    response_model=BroadcastResponse,
)
async def create_broadcast(
    data: BroadcastCreateRequest,
    bot: Bot = Depends(get_owned_bot),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    broadcast = await svc_create_broadcast(db, bot, data)

    return BroadcastResponse(
        id=broadcast.id,
        bot_id=broadcast.bot_id,
        region=broadcast.region,
        text=broadcast.text,
        buttons=broadcast.buttons,
        bot_ids=broadcast.bot_ids,
        status=broadcast.status.value,
        scheduled_at=broadcast.scheduled_at,
    )


@router.post("/broadcasts/{broadcast_id}/send-now")
async def send_broadcast_now(
    broadcast: Broadcast = Depends(get_owned_broadcast),
    db: AsyncSession = Depends(get_db),
):
    try:
        broadcast = await svc_send_broadcast_now(db, broadcast)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "id": broadcast.id,
        "status": broadcast.status.value,
        "scheduled_at": broadcast.scheduled_at,
    }


@router.patch("/broadcasts/{broadcast_id}/status")
async def update_broadcast_status(
    data: BroadcastStatusUpdate,
    broadcast_id: int,
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Broadcast).where(Broadcast.id == broadcast_id)
    )
    broadcast = result.scalar_one_or_none()

    if not broadcast:
        raise HTTPException(404, "Broadcast not found")

    current = broadcast.status.value
    new = data.status

    allowed_transitions = {
        "draft": ["scheduled", "cancelled"],
        "scheduled": ["sending", "cancelled"],
        "sending": ["sending", "sent", "failed"],
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


@router.patch("/broadcasts/{broadcast_id}/stats")
async def update_broadcast_stats(
    data: dict,
    broadcast_id: int,
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    values = {}

    if "total_users" in data:
        values["total_users"] = data["total_users"]
    if "sent_count" in data:
        values["sent_count"] = data["sent_count"]
    if "failed_count" in data:
        values["failed_count"] = data["failed_count"]
    if "started_at" in data:
        values["started_at"] = datetime.utcnow()
    if "finished_at" in data:
        values["finished_at"] = datetime.utcnow()

    if values:
        result = await db.execute(
            update(Broadcast)
            .where(Broadcast.id == broadcast_id)
            .values(**values)
        )
        if result.rowcount == 0:
            raise HTTPException(404, "Broadcast not found")
        await db.commit()

    return {"status": "ok"}


@router.patch("/broadcasts/{broadcast_id}/schedule")
async def update_broadcast_schedule(
    data: BroadcastScheduleUpdate,
    broadcast: Broadcast = Depends(get_owned_broadcast),
    db: AsyncSession = Depends(get_db),
):
    if broadcast.status not in (
        BroadcastStatus.draft,
        BroadcastStatus.scheduled,
    ):
        raise HTTPException(
            status_code=400,
            detail="Can edit schedule only for draft or scheduled broadcasts",
        )

    broadcast.scheduled_at = data.scheduled_at

    if broadcast.status == BroadcastStatus.draft:
        broadcast.status = BroadcastStatus.scheduled

    await db.commit()
    await db.refresh(broadcast)

    return {
        "id": broadcast.id,
        "status": broadcast.status.value,
        "scheduled_at": broadcast.scheduled_at,
    }


@router.patch("/broadcasts/{broadcast_id}/cancel")
async def cancel_broadcast(
    broadcast: Broadcast = Depends(get_owned_broadcast),
    db: AsyncSession = Depends(get_db),
):
    if broadcast.status not in (BroadcastStatus.draft, BroadcastStatus.scheduled):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel broadcast with status {broadcast.status.value}",
        )

    broadcast.status = BroadcastStatus.cancelled
    await db.commit()
    await db.refresh(broadcast)

    return {"id": broadcast.id, "status": broadcast.status.value}


@router.patch("/broadcasts/{broadcast_id}")
async def update_broadcast(
    data: BroadcastCreateRequest,
    broadcast: Broadcast = Depends(get_owned_broadcast),
    db: AsyncSession = Depends(get_db),
):
    if broadcast.status not in (
        BroadcastStatus.draft,
        BroadcastStatus.scheduled,
    ):
        raise HTTPException(
            status_code=400,
            detail="Can edit only draft or scheduled broadcasts"
        )

    if broadcast.status == BroadcastStatus.scheduled and broadcast.started_at:
        raise HTTPException(
            status_code=400,
            detail="Cannot edit broadcast that already started"
        )

    broadcast.text = data.text
    broadcast.buttons = data.buttons
    broadcast.scheduled_at = data.scheduled_at

    await db.commit()
    await db.refresh(broadcast)

    return {
        "id": broadcast.id,
        "status": broadcast.status.value,
        "scheduled_at": broadcast.scheduled_at,
    }
