from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ActionLog, ActionType, Link, User, UserStatus


class StatsService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def mirror_requests(self, days: int = 1) -> int:
        since = datetime.utcnow() - timedelta(days=days)
        return await self._s.scalar(
            select(func.count(ActionLog.id)).where(
                ActionLog.action == ActionType.GET_MIRROR,
                ActionLog.created_at >= since,
            )
        ) or 0

    async def top_links(self, limit: int = 5) -> list[Link]:
        result = await self._s.execute(
            select(Link)
            .where(Link.is_deleted == False)
            .order_by(Link.click_count.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def registrations_by_day(self, days: int = 7) -> list[tuple[str, int]]:
        """Возвращает [(дата, кол-во), ...] за последние N дней."""
        since = datetime.utcnow() - timedelta(days=days)
        result = await self._s.execute(
            select(
                func.date(User.registered_at).label("day"),
                func.count(User.id).label("cnt"),
            )
            .where(User.registered_at >= since)
            .group_by("day")
            .order_by("day")
        )
        return [(str(row.day), row.cnt) for row in result]

    async def full_report(self) -> dict:
        """Полный отчёт для Dashboard."""
        from bot.repositories.user_repo import UserRepository
        user_repo = UserRepository(self._s)

        return {
            "users": {
                "total":      await user_repo.count_total(),
                "today":      await user_repo.count_today(),
                "week":       await user_repo.count_week(),
                "month":      await user_repo.count_month(),
                "banned":     await user_repo.count_banned(),
                "subscribed": await user_repo.count_subscribed(),
            },
            "mirrors": {
                "today": await self.mirror_requests(days=1),
                "week":  await self.mirror_requests(days=7),
                "month": await self.mirror_requests(days=30),
                "top":   await self.top_links(),
            },
            "sources": await user_repo.source_stats(),
        }