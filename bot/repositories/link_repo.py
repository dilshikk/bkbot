from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Link


class LinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_all(self) -> list[Link]:
        result = await self._s.execute(
            select(Link)
            .where(Link.is_deleted == False)
            .order_by(Link.priority.desc(), Link.id.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, link_id: int) -> Link | None:
        return await self._s.get(Link, link_id)

    async def create(
        self,
        title: str,
        url: str,
        created_by: int,
        priority: int = 0,
    ) -> Link:
        link = Link(
            title=title,
            url=url,
            priority=priority,
            created_by=created_by,
            is_active=False,
            is_healthy=True,
            is_deleted=False,
        )
        self._s.add(link)
        await self._s.flush()
        return link

    async def activate(self, link_id: int, admin_id: int) -> None:
        """Деактивировать все → активировать выбранную."""
        await self._s.execute(
            update(Link)
            .where(Link.is_deleted == False)
            .values(is_active=False)
        )
        await self._s.execute(
            update(Link)
            .where(Link.id == link_id)
            .values(is_active=True, updated_by=admin_id)
        )

    async def deactivate(self, link_id: int, admin_id: int) -> None:
        await self._s.execute(
            update(Link)
            .where(Link.id == link_id)
            .values(is_active=False, updated_by=admin_id)
        )

    async def toggle_fallback(self, link_id: int, admin_id: int) -> bool:
        link = await self.get_by_id(link_id)
        if link is None:
            return False
        link.is_fallback = not link.is_fallback
        link.updated_by = admin_id
        await self._s.flush()
        return link.is_fallback

    async def update_url(self, link_id: int, url: str, admin_id: int) -> None:
        await self._s.execute(
            update(Link)
            .where(Link.id == link_id)
            .values(url=url, updated_by=admin_id)
        )

    async def update_title(self, link_id: int, title: str, admin_id: int) -> None:
        await self._s.execute(
            update(Link)
            .where(Link.id == link_id)
            .values(title=title, updated_by=admin_id)
        )

    async def schedule(
        self,
        link_id: int,
        active_from: datetime,
        active_to: datetime | None,
        admin_id: int,
    ) -> None:
        await self._s.execute(
            update(Link)
            .where(Link.id == link_id)
            .values(active_from=active_from, active_to=active_to, updated_by=admin_id)
        )

    async def soft_delete(self, link_id: int, admin_id: int) -> None:
        await self._s.execute(
            update(Link)
            .where(Link.id == link_id)
            .values(is_deleted=True, is_active=False, updated_by=admin_id)
        )