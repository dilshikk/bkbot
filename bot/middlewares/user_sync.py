# bot/middlewares/user_sync.py
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.core.config import settings


class UserSyncMiddleware(BaseMiddleware):
    """
    Автоматически создаёт или обновляет пользователя при каждом апдейте.
    Кладёт объект User в data["db_user"] для хендлеров.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = self._extract_from_user(event)
        if from_user is None or from_user.is_bot:
            return await handler(event, data)

        session: AsyncSession = data["session"]
        bot: Bot              = data["bot"]

        db_user, is_new = await self._get_or_create(session, from_user)
        data["db_user"] = db_user

        if is_new:
            await _notify_admins_new_user(bot, db_user)

        return await handler(event, data)

    @staticmethod
    def _extract_from_user(event: TelegramObject):
        if isinstance(event, Update):
            if event.message:
                return event.message.from_user
            if event.callback_query:
                return event.callback_query.from_user
            if event.inline_query:
                return event.inline_query.from_user
        return getattr(event, "from_user", None)

    @staticmethod
    async def _get_or_create(session: AsyncSession, from_user) -> tuple[User, bool]:
        result = await session.execute(
            select(User).where(User.telegram_id == from_user.id)
        )
        user   = result.scalar_one_or_none()
        now    = datetime.utcnow()
        is_new = user is None

        if is_new:
            user = User(
                telegram_id=from_user.id,
                username=from_user.username,
                first_name=from_user.first_name,
                last_name=from_user.last_name,
                language=from_user.language_code or "ru",
                registered_at=now,
                last_seen_at=now,
            )
            session.add(user)
            await session.flush()
        else:
            changed = False
            for field, value in {
                "username":   from_user.username,
                "first_name": from_user.first_name,
                "last_name":  from_user.last_name,
            }.items():
                if getattr(user, field) != value:
                    setattr(user, field, value)
                    changed = True

            user.last_seen_at = now
            if changed:
                await session.flush()

        return user, is_new


async def _notify_admins_new_user(bot: Bot, user: User) -> None:
    name  = " ".join(filter(None, [user.first_name, user.last_name])) or "—"
    uname = f"@{user.username}" if user.username else "нет username"
    text  = (
        f"👤 <b>Новый пользователь!</b>\n"
        f"{'━' * 22}\n"
        f"Имя: {name}\n"
        f"Username: {uname}\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"Источник: {user.source or 'direct'}"
    )
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            pass
