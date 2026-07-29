"""
Middleware технического обслуживания.

Когда settings.maintenance = True:
  - Обычные пользователи получают сообщение и не могут пользоваться ботом
  - Администраторы (settings.ADMIN_IDS) работают в обычном режиме

Middleware встаёт после DbSessionMiddleware и UserSyncMiddleware
(нужна сессия для get_settings), но до всех остальных.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from bot.core.config import settings as app_settings
from bot.services.settings_service import get_settings


class MaintenanceMiddleware(BaseMiddleware):
    """
    Блокирует все апдейты от обычных пользователей во время тех. работ.
    Для Message — отвечает текстом.
    Для CallbackQuery — показывает alert.
    Остальные апдейты — молча игнорируются.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Администраторы всегда проходят
        user_id = _extract_user_id(event)
        if user_id in app_settings.ADMIN_IDS:
            return await handler(event, data)

        # Проверяем флаг maintenance в БД
        session = data.get("session")
        if session is None:
            return await handler(event, data)

        bot_settings = await get_settings(session)
        if not bot_settings.maintenance:
            return await handler(event, data)

        # Режим обслуживания включён — блокируем
        text = bot_settings.maintenance_text

        if isinstance(event, Message):
            await event.answer(text)
            return None

        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
            return None

        return None


def _extract_user_id(event: TelegramObject) -> int:
    """Извлекает telegram_id из любого типа апдейта."""
    from_user = getattr(event, "from_user", None)
    if from_user is not None:
        return from_user.id
    if hasattr(event, "message") and event.message and event.message.from_user:
        return event.message.from_user.id
    if hasattr(event, "callback_query") and event.callback_query and event.callback_query.from_user:
        return event.callback_query.from_user.id
    return 0
