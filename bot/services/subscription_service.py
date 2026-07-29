"""
Сервис проверки подписки на каналы.

ОПТИМИЗАЦИЯ: результат кэшируется в Redis на SUB_CACHE_TTL секунд.
Без кэша каждый апдейт делал N HTTP-запросов к Telegram (get_chat_member),
где N = количество каналов. Это основная причина медленной реакции бота.

Кэш инвалидируется явно через invalidate_subscription_cache() когда
пользователь нажимает кнопку "✅ Я подписался".
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.redis_client import get_redis
from bot.database.models import Channel

logger = logging.getLogger(__name__)

# Кэш статуса подписки: 60 секунд
# Достаточно чтобы не спамить Telegram API, но и не задерживать реакцию
# при реальной подписке (пользователь нажимает кнопку → кэш сбрасывается)
_SUB_CACHE_TTL = 60
_SUB_CACHE_KEY = "sub_status:{telegram_id}"


async def check_all_subscriptions(
    bot: Bot,
    session: AsyncSession,
    telegram_id: int,
    *,
    use_cache: bool = True,
) -> bool:
    """
    Возвращает True только если пользователь подписан
    на ВСЕ обязательные активные каналы.

    При use_cache=True проверяет Redis перед обращением к Telegram API.
    При use_cache=False (кнопка "Я подписался") всегда обращается к API.
    """
    redis = await get_redis()
    cache_key = _SUB_CACHE_KEY.format(telegram_id=telegram_id)

    if use_cache:
        cached = await redis.get(cache_key)
        if cached is not None:
            result = cached == b"1" or cached == "1"
            logger.debug("sub_cache hit telegram_id=%s → %s", telegram_id, result)
            return result

    channels = list(await session.scalars(
        select(Channel).where(
            Channel.is_required == True,
            Channel.is_active == True,
        )
    ))

    if not channels:
        # Нет обязательных каналов — кэшируем True
        await redis.setex(cache_key, _SUB_CACHE_TTL, "1")
        return True

    is_subscribed = True
    for channel in channels:
        try:
            member = await bot.get_chat_member(channel.telegram_id, telegram_id)
            if member.status in ("left", "kicked", "banned"):
                is_subscribed = False
                break
        except (TelegramBadRequest, TelegramForbiddenError):
            # Бот не в канале или нет прав — пропускаем этот канал
            logger.warning(
                "sub_check: cannot check channel %s for user %s",
                channel.telegram_id, telegram_id,
            )
            continue

    # Кэшируем результат
    await redis.setex(cache_key, _SUB_CACHE_TTL, "1" if is_subscribed else "0")
    logger.debug(
        "sub_check telegram_id=%s channels=%d → %s (cached %ds)",
        telegram_id, len(channels), is_subscribed, _SUB_CACHE_TTL,
    )
    return is_subscribed


async def invalidate_subscription_cache(telegram_id: int) -> None:
    """
    Сбрасывает кэш подписки для пользователя.
    Вызывается когда пользователь нажимает "✅ Я подписался",
    чтобы следующая проверка шла напрямую к Telegram API.
    """
    redis = await get_redis()
    await redis.delete(_SUB_CACHE_KEY.format(telegram_id=telegram_id))
    logger.debug("sub_cache invalidated for telegram_id=%s", telegram_id)
