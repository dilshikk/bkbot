from __future__ import annotations

from sqlalchemy import select, update
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

        FIX: убрано накопление click_count отсюда — нарушало CQS.
        Инкремент вызывается явно через increment_click() после отправки.
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

        return link

    async def increment_click(self, link_id: int) -> None:
        """
        Атомарно инкрементирует счётчик переходов.
        Используем UPDATE вместо read-modify-write чтобы избежать race condition.
        """
        await self._s.execute(
            update(Link)
            .where(Link.id == link_id)
            .values(click_count=Link.click_count + 1)
        )

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
