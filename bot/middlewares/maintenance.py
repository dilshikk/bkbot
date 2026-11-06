"""
Middleware технического обслуживания.

Когда settings.maintenance = True:
  - Обычные пользователи получают сообщение и не могут пользоваться ботом
  - Администраторы (settings.ADMIN_IDS) работают в обычном режиме
  - В группах бот молчит, чтобы не засорять общий чат

FIX (#9): регистрируется на dp.message и dp.callback_query, а НЕ на dp.update.
На dp.update приходил Update, isinstance(Message) не срабатывал, и
пользователи не получали текст техработ — бот просто молчал.

Сессия БД и db_user уже есть: DbSessionMiddleware и UserSyncMiddleware
стоят на dp.update и выполняются раньше.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.core.config import settings as app_settings
from bot.services.settings_service import get_settings


class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        if from_user is None or from_user.id in app_settings.ADMIN_IDS:
            return await handler(event, data)

        session = data.get("session")
        if session is None:
            return await handler(event, data)

        bot_settings = await get_settings(session)
        if not bot_settings.maintenance:
            return await handler(event, data)

        text = bot_settings.maintenance_text

        if isinstance(event, Message):
            if event.chat.type == "private":
                await event.answer(text)
            return None

        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
            return None

        return None
