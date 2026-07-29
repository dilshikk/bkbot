from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.database.models import User, UserStatus


class BanCheckMiddleware(BaseMiddleware):
    """Блокирует забаненных пользователей до попадания в хендлер."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db_user: User | None = data.get("db_user")

        if db_user and db_user.status == UserStatus.BANNED:
            if isinstance(event, Message):
                reason = db_user.ban_reason or "Нарушение правил."
                await event.answer(f"🚫 Ваш аккаунт заблокирован.\n\n{reason}")
            return None  # Прерываем цепочку

        return await handler(event, data)