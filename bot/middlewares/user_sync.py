from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, Update, User as TgUser
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.background_tasks import create_background_task
from bot.core.config import settings
from bot.core.redis_client import get_redis
from bot.database.models import User, UserStatus


# Обновляем last_seen_at не чаще чем раз в 5 минут.
_LAST_SEEN_TTL = 300  # секунд
_LAST_SEEN_KEY = "last_seen:{user_id}"


def _utcnow() -> datetime:
    """Текущее UTC время без tzinfo (naive) для совместимости с БД."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        bot: Bot = data["bot"]

        db_user, is_new = await self._get_or_create(session, from_user)
        data["db_user"] = db_user

        if is_new and settings.NOTIFY_NEW_USERS:
            # Текст собираем сразу: после закрытия сессии объект db_user читать нельзя.
            # Отправка в фоне — не задерживает ответ пользователю.
            text = _new_user_text(db_user)
            create_background_task(
                _notify_admins_new_user(bot, text),
                name=f"notify_new_user:{db_user.telegram_id}",
            )

        return await handler(event, data)

    @staticmethod
    def _extract_from_user(event: TelegramObject) -> TgUser | None:
        if isinstance(event, Update):
            if event.message:
                return event.message.from_user
            if event.callback_query:
                return event.callback_query.from_user
            if event.inline_query:
                return event.inline_query.from_user
        return getattr(event, "from_user", None)

    @staticmethod
    async def _get_or_create(
        session: AsyncSession,
        from_user: TgUser,
    ) -> tuple[User, bool]:
        result = await session.execute(
            select(User).where(User.telegram_id == from_user.id)
        )
        user = result.scalar_one_or_none()
        now = _utcnow()
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
            try:
                # FIX: точка сохранения — при гонке двух апдейтов откатится
                # только эта вставка, а не вся сессия
                async with session.begin_nested():
                    session.add(user)
            except IntegrityError:
                # Параллельный апдейт уже создал пользователя
                user = (await session.execute(
                    select(User).where(User.telegram_id == from_user.id)
                )).scalar_one()
                is_new = False
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

            # Пользователь снова пишет боту после блокировки — возвращаем в активные
            if user.status == UserStatus.DELETED:
                user.status = UserStatus.ACTIVE
                changed = True

            should_update_seen = await _should_update_last_seen(from_user.id)
            if should_update_seen or changed:
                user.last_seen_at = now
                await session.flush()

        return user, is_new


async def _should_update_last_seen(telegram_id: int) -> bool:
    """
    Возвращает True (и устанавливает TTL-ключ), если прошло достаточно времени
    с прошлого обновления last_seen_at.
    """
    redis = await get_redis()
    key = _LAST_SEEN_KEY.format(user_id=telegram_id)
    result = await redis.set(key, "1", ex=_LAST_SEEN_TTL, nx=True)
    return result is True


def _new_user_text(user: User) -> str:
    name = " ".join(filter(None, [user.first_name, user.last_name])) or "—"
    uname = f"@{user.username}" if user.username else "нет username"
    return (
        f"👤 <b>Новый пользователь!</b>\n"
        f"{'━' * 22}\n"
        f"Имя: {name}\n"
        f"Username: {uname}\n"
        f"ID: <code>{user.telegram_id}</code>"
    )


async def _notify_admins_new_user(bot: Bot, text: str) -> None:
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            pass
