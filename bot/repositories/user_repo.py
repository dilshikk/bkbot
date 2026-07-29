from datetime import datetime, timedelta

from sqlalchemy import select, update, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, UserStatus, ActionLog, ActionType


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self._s.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def search(self, query: str, limit: int = 10) -> list[User]:
        """
        Поиск по telegram_id, username, имени.
        query может быть числом (telegram_id) или строкой (username/имя).
        """
        q = query.lstrip("@").strip()

        if q.isdigit():
            result = await self._s.execute(
                select(User).where(User.telegram_id == int(q)).limit(1)
            )
        else:
            pattern = f"%{q}%"
            result = await self._s.execute(
                select(User).where(
                    or_(
                        User.username.ilike(pattern),
                        User.first_name.ilike(pattern),
                        User.last_name.ilike(pattern),
                    )
                ).limit(limit)
            )
        return list(result.scalars().all())

    async def get_paginated(self, offset: int = 0, limit: int = 20) -> list[User]:
        result = await self._s.execute(
            select(User)
            .order_by(User.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def set_source(self, user_id: int, source: str) -> None:
        await self._s.execute(
            update(User)
            .where(User.id == user_id, User.source.is_(None))
            .values(source=source)
        )

    async def ban(self, telegram_id: int, reason: str) -> bool:
        result = await self._s.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(status=UserStatus.BANNED, ban_reason=reason)
            .returning(User.id)
        )
        return result.scalar_one_or_none() is not None

    async def unban(self, telegram_id: int) -> bool:
        result = await self._s.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(status=UserStatus.ACTIVE, ban_reason=None)
            .returning(User.id)
        )
        return result.scalar_one_or_none() is not None

    async def set_subscribed(self, user_id: int, value: bool) -> None:
        await self._s.execute(
            update(User).where(User.id == user_id).values(is_subscribed=value)
        )

    # ── Счётчики ──────────────────────────────────────────

    async def count_total(self) -> int:
        return await self._s.scalar(select(func.count(User.id))) or 0

    async def count_today(self) -> int:
        today = datetime.utcnow().date()
        return await self._s.scalar(
            select(func.count(User.id)).where(
                func.date(User.registered_at) == today
            )
        ) or 0

    async def count_week(self) -> int:
        since = datetime.utcnow() - timedelta(days=7)
        return await self._s.scalar(
            select(func.count(User.id)).where(User.registered_at >= since)
        ) or 0

    async def count_month(self) -> int:
        since = datetime.utcnow() - timedelta(days=30)
        return await self._s.scalar(
            select(func.count(User.id)).where(User.registered_at >= since)
        ) or 0

    async def count_banned(self) -> int:
        return await self._s.scalar(
            select(func.count(User.id)).where(User.status == UserStatus.BANNED)
        ) or 0

    async def count_subscribed(self) -> int:
        return await self._s.scalar(
            select(func.count(User.id)).where(User.is_subscribed == True)
        ) or 0

    # ── Источники трафика ─────────────────────────────────

    async def source_stats(self, limit: int = 10) -> list[tuple[str, int]]:
        """Топ источников: [(source, count), ...]"""
        result = await self._s.execute(
            select(
                func.coalesce(User.source, "direct").label("source"),
                func.count(User.id).label("cnt"),
            )
            .group_by("source")
            .order_by(func.count(User.id).desc())
            .limit(limit)
        )
        return [(row.source, row.cnt) for row in result]

    # ── Экспорт ───────────────────────────────────────────

    async def get_all_for_export(self) -> list[User]:
        result = await self._s.execute(
            select(User).order_by(User.id)
        )
        return list(result.scalars().all())