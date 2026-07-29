"""
Антиспам на Redis.

Алгоритм — sliding window (скользящее окно):
  - Храним список меток времени в Redis sorted set
  - При каждом сообщении удаляем старые метки (вне окна)
  - Считаем оставшиеся
  - Если count >= THROTTLE_RATE → нарушение

При превышении THROTTLE_BAN_COUNT нарушений подряд
пользователь получает временный бан на THROTTLE_BAN_TTL секунд.

Администраторы (settings.ADMIN_IDS) полностью освобождены от лимитов.
"""
from __future__ import annotations

import time
from uuid import uuid4
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.core.config import settings
from bot.core.redis_client import get_redis

_KEY_WINDOW = "throttle:window:{user_id}"
_KEY_VIOLATIONS = "throttle:violations:{user_id}"
_KEY_BANNED = "throttle:banned:{user_id}"


class ThrottleMiddleware(BaseMiddleware):
    """
    Redis sliding-window антиспам.
    Работает корректно при нескольких инстансах бота.
    Администраторы пропускаются без проверки.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        user_id = event.from_user.id

        # Всегда пропускаем /start
        if (event.text or "").startswith("/start"):
            return await handler(event, data)

        # Администраторы освобождены от всех throttle-ограничений
        if user_id in settings.ADMIN_IDS:
            return await handler(event, data)

        redis = await get_redis()

        # Проверяем временный бан
        if await _is_banned(redis, user_id):
            ttl = await redis.ttl(_KEY_BANNED.format(user_id=user_id))
            await event.answer(
                f"⏳ Вы отправляете слишком много сообщений.\n"
                f"Попробуйте через {ttl} сек."
            )
            return None

        # Проверяем лимит
        is_throttled = await _check_rate(redis, user_id)

        if is_throttled:
            violations = await _increment_violations(redis, user_id)

            if violations >= settings.THROTTLE_BAN_COUNT:
                await _set_banned(redis, user_id)
                await _reset_violations(redis, user_id)
                await event.answer(
                    f"🚫 Превышен лимит сообщений. "
                    f"Вы заблокированы на {settings.THROTTLE_BAN_TTL // 60} мин."
                )
            # Молча игнорируем — не отвечаем
            return None

        # Сбрасываем счётчик нарушений при нормальном поведении
        await _reset_violations(redis, user_id)
        return await handler(event, data)


# ── Helpers ───────────────────────────────────────────────────────────────

async def _check_rate(redis, user_id: int) -> bool:
    """
    Sliding window: True если лимит превышен.
    Использует sorted set: score = timestamp.
    """
    now    = time.time()
    window = settings.THROTTLE_PERIOD
    key    = _KEY_WINDOW.format(user_id=user_id)

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)    # удалить старые
    pipe.zadd(key, {str(uuid4()): now})            # добавить текущую
    pipe.zcard(key)                                # считаем кол-во
    pipe.expire(key, window * 2)                   # TTL чуть больше окна
    results = await pipe.execute()

    count: int = results[2]
    return count > settings.THROTTLE_RATE


async def _is_banned(redis, user_id: int) -> bool:
    return await redis.exists(_KEY_BANNED.format(user_id=user_id)) == 1


async def _set_banned(redis, user_id: int) -> None:
    await redis.setex(
        _KEY_BANNED.format(user_id=user_id),
        settings.THROTTLE_BAN_TTL,
        "1",
    )


async def _increment_violations(redis, user_id: int) -> int:
    key = _KEY_VIOLATIONS.format(user_id=user_id)
    count = await redis.incr(key)
    await redis.expire(key, 60)    # счётчик нарушений живёт 60 сек
    return count


async def _reset_violations(redis, user_id: int) -> None:
    await redis.delete(_KEY_VIOLATIONS.format(user_id=user_id))
