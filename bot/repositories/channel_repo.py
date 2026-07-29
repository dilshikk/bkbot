from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Channel


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_all(self) -> list[Channel]:
        result = await self._s.execute(select(Channel).order_by(Channel.id))
        return list(result.scalars().all())

    async def get_by_id(self, ch_id: int) -> Channel | None:
        return await self._s.get(Channel, ch_id)

    async def create(
        self,
        telegram_id: int,
        title: str,
        username: str | None,
        invite_link: str | None,
        is_required: bool = True,
    ) -> Channel:
        ch = Channel(
            telegram_id=telegram_id,
            title=title,
            username=username,
            invite_link=invite_link,
            is_required=is_required,
            is_active=True,
        )
        self._s.add(ch)
        await self._s.flush()
        return ch

    async def toggle_required(self, ch_id: int) -> bool:
        ch = await self.get_by_id(ch_id)
        if ch is None:
            return False
        ch.is_required = not ch.is_required
        return ch.is_required

    async def toggle_active(self, ch_id: int) -> bool:
        ch = await self.get_by_id(ch_id)
        if ch is None:
            return False
        ch.is_active = not ch.is_active
        return ch.is_active

    async def delete(self, ch_id: int) -> None:
        ch = await self.get_by_id(ch_id)
        if ch:
            await self._s.delete(ch)
