"""
Миграция: создание таблиц teams/team_members, добавление team_id в bots/keys.
Скрипт идемпотентный — безопасно запускать повторно.

Запуск:
    python -m backend.migrate_teams
"""
import asyncio

from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import engine, AsyncSessionLocal
from backend.db.base import Base
from backend.models.team import Team, TeamMember
from backend.models.bot import Bot
from backend.models.key import Key


async def migrate():
    # 1. Создаём таблицы teams и team_members если их нет
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 2. Добавляем колонку team_id в bots если нет
        await _add_column_if_missing(db, "bots", "team_id", "INTEGER REFERENCES teams(id) ON DELETE CASCADE")
        # 3. Добавляем колонку team_id в keys если нет
        await _add_column_if_missing(db, "keys", "team_id", "INTEGER REFERENCES teams(id) ON DELETE CASCADE")

        # 4. Собираем уникальных owner_telegram_id из bots и keys
        bots_owners = (await db.execute(text("SELECT DISTINCT owner_telegram_id FROM bots"))).scalars().all()
        keys_owners = (await db.execute(text("SELECT DISTINCT owner_telegram_id FROM keys"))).scalars().all()
        all_owners = set(bots_owners) | set(keys_owners)

        if not all_owners:
            print("Нет владельцев для миграции.")
            await db.commit()
            return

        # Проверяем какие owner уже имеют team
        existing_members = (await db.execute(text("SELECT DISTINCT telegram_id FROM team_members"))).scalars().all()
        existing_set = set(existing_members)

        created = 0
        mapping = {}  # owner_telegram_id -> team_id

        # Загружаем существующий маппинг
        for tid in existing_set:
            row = (await db.execute(
                text("SELECT team_id FROM team_members WHERE telegram_id = :tid LIMIT 1"),
                {"tid": tid}
            )).scalar_one_or_none()
            if row:
                mapping[tid] = row

        for owner_tid in all_owners:
            if owner_tid in existing_set:
                continue

            # Создаём команду
            result = await db.execute(
                text("INSERT INTO teams (name, created_by) VALUES (:name, :created_by)"),
                {"name": "Моя команда", "created_by": owner_tid}
            )
            team_id = result.lastrowid

            await db.execute(
                text("INSERT INTO team_members (team_id, telegram_id) VALUES (:team_id, :tid)"),
                {"team_id": team_id, "tid": owner_tid}
            )

            mapping[owner_tid] = team_id
            created += 1

        # 5. Обновляем bots.team_id
        for owner_tid, team_id in mapping.items():
            await db.execute(
                text("UPDATE bots SET team_id = :team_id WHERE owner_telegram_id = :owner_id AND (team_id IS NULL)"),
                {"team_id": team_id, "owner_id": owner_tid}
            )

        # 6. Обновляем keys.team_id
        for owner_tid, team_id in mapping.items():
            await db.execute(
                text("UPDATE keys SET team_id = :team_id WHERE owner_telegram_id = :owner_id AND (team_id IS NULL)"),
                {"team_id": team_id, "owner_id": owner_tid}
            )

        await db.commit()
        print(f"Миграция завершена. Создано команд: {created}. Всего владельцев: {len(all_owners)}")


async def _add_column_if_missing(db: AsyncSession, table: str, column: str, col_type: str):
    result = await db.execute(text(f"PRAGMA table_info({table})"))
    columns = [row[1] for row in result.fetchall()]
    if column not in columns:
        await db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
        print(f"Добавлена колонка {column} в {table}")
    else:
        print(f"Колонка {column} уже существует в {table}")


if __name__ == "__main__":
    asyncio.run(migrate())
