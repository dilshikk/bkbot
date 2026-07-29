from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Link


class LinkService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_active(self) -> Link | None:
        """
        Приоритет:
        1. is_active=True + is_healthy=True → по приоритету (desc)
        2. is_fallback=True + is_healthy=True → резервная
        3. None → бот скажет "зеркало обновляется"
        """
        result = await self._s.execute(
            select(Link)
            .where(
                Link.is_active == True,
                Link.is_healthy == True,
                Link.is_deleted == False,
            )
            .order_by(Link.priority.desc())
            .limit(1)
        )
        link = result.scalar_one_or_none()

        if link is None:
            # Пробуем резервную
            result = await self._s.execute(
                select(Link)
                .where(
                    Link.is_fallback == True,
                    Link.is_healthy == True,
                    Link.is_deleted == False,
                )
                .order_by(Link.priority.desc())
                .limit(1)
            )
            link = result.scalar_one_or_none()

        if link is not None:
            link.click_count += 1
            await self._s.flush()

        return link

    async def get_all_mirrors(self) -> list[Link]:
        """Все активные зеркала — для показа списка пользователю."""
        result = await self._s.execute(
            select(Link)
            .where(
                Link.is_active == True,
                Link.is_deleted == False,
            )
            .order_by(Link.priority.desc())
        )
        return list(result.scalars().all())