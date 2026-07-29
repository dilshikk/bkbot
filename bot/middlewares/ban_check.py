from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.core.config import settings
from bot.database.models import User, UserStatus


class BanCheckMiddleware(BaseMiddleware):
    """
    Блокирует забаненных пользователей до попадания в хендлер.
    Администраторы никогда не блокируются.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db_user: User | None = data.get("db_user")

        if db_user and db_user.status == UserStatus.BANNED:
            # Администраторы не могут быть заблокированы
            if db_user.telegram_id in settings.ADMIN_IDS:
                return await handler(event, data)

            if isinstance(event, Message):
                reason = db_user.ban_reason or "Нарушение правил."
                await event.answer(f"🚫 Ваш аккаунт заблокирован.\n\n{reason}")
            return None

        return await handler(event, data)
