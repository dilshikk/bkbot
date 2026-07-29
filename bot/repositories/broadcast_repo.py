from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Broadcast, BroadcastStatus


class BroadcastRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, created_by: int) -> Broadcast:
        broadcast = Broadcast(
            status=BroadcastStatus.DRAFT,
            created_by=created_by,
        )
        self._s.add(broadcast)
        await self._s.flush()
        return broadcast

    async def get_by_id(self, broadcast_id: int) -> Broadcast | None:
        return await self._s.get(Broadcast, broadcast_id)

    async def get_history(self, limit: int = 10) -> list[Broadcast]:
        result = await self._s.execute(
            select(Broadcast)
            .where(Broadcast.status.in_([
                BroadcastStatus.DONE,
                BroadcastStatus.CANCELLED,
                BroadcastStatus.FAILED,
            ]))
            .order_by(Broadcast.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_pending(self) -> list[Broadcast]:
        """Запланированные рассылки у которых наступило время."""
        now = datetime.utcnow()
        result = await self._s.execute(
            select(Broadcast).where(
                Broadcast.status == BroadcastStatus.PENDING,
                Broadcast.scheduled_at <= now,
            )
        )
        return list(result.scalars().all())