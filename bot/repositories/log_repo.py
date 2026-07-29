from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ActionLog


class LogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def log(
        self,
        action: str,
        *,
        user_id: int | None = None,
        telegram_id: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._s.add(ActionLog(
            user_id=user_id,
            telegram_id=telegram_id,
            action=action,
            meta=meta,
            created_at=datetime.utcnow(),
        ))
        # Не флешим — закоммитится вместе с основной транзакцией