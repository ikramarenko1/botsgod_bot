from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from backend.db.session import get_db
from backend.models.team import Team, TeamMember
from backend.utils.auth import get_owner_id, get_user_team_id
from backend.schemas.team import (
    TeamResponse,
    TeamMemberResponse,
    TeamMembersListResponse,
    AddMemberRequest,
)

router = APIRouter()


@router.get("/team", response_model=TeamMembersListResponse)
async def get_team(
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    result = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id)
    )
    members = result.scalars().all()

    return TeamMembersListResponse(
        team=TeamResponse.model_validate(team),
        members=[
            TeamMemberResponse(
                telegram_id=m.telegram_id,
                is_creator=(m.telegram_id == team.created_by),
                joined_at=m.joined_at,
            )
            for m in members
        ],
    )


@router.post("/team/members", response_model=TeamMemberResponse)
async def add_member(
    data: AddMemberRequest,
    owner_id: int = Depends(get_owner_id),
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    if data.telegram_id == owner_id:
        raise HTTPException(400, "Вы уже в команде")

    # Проверяем что пользователь не в другой команде
    existing = await db.execute(
        select(TeamMember).where(TeamMember.telegram_id == data.telegram_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Пользователь уже состоит в команде")

    member = TeamMember(team_id=team_id, telegram_id=data.telegram_id)
    db.add(member)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(400, "Пользователь уже состоит в команде")

    team = await db.get(Team, team_id)

    return TeamMemberResponse(
        telegram_id=member.telegram_id,
        is_creator=(member.telegram_id == team.created_by),
        joined_at=member.joined_at,
    )


@router.delete("/team/members/{telegram_id}")
async def remove_member(
    telegram_id: int,
    owner_id: int = Depends(get_owner_id),
    team_id: int = Depends(get_user_team_id),
    db: AsyncSession = Depends(get_db),
):
    team = await db.get(Team, team_id)
    if not team:
        raise HTTPException(404, "Team not found")

    if telegram_id == team.created_by:
        raise HTTPException(400, "Нельзя удалить создателя команды")

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.telegram_id == telegram_id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Участник не найден")

    await db.delete(member)
    await db.commit()
    return {"status": "removed"}
