"""
Сервис проверки подписки на каналы.

ОПТИМИЗАЦИЯ: результат кэшируется в Redis на SUB_CACHE_TTL секунд.
Кэш инвалидируется явно через invalidate_subscription_cache() когда
пользователь нажимает кнопку "✅ Я подписался".

FIX (#13):
  - restricted с is_member=False больше не считается подпиской;
  - если бот не может проверить канал (нет прав / убрали из канала),
    админы получают предупреждение (не чаще раза в час на канал).
"""
from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.background_tasks import create_background_task
from bot.core.redis_client import get_redis
from bot.database.models import Channel
from bot.services.admin_notify import notify_admins
from bot.utils.subscription import is_channel_member

logger = logging.getLogger(__name__)

_SUB_CACHE_TTL = 60
_SUB_CACHE_KEY = "sub_status:{telegram_id}"

# Предупреждение админам о недоступном канале — не чаще раза в час
_CHANNEL_ALERT_TTL = 3600
_CHANNEL_ALERT_KEY = "sub_check_alert:{channel_id}"


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
            Channel.is_required == True,  # noqa: E712
            Channel.is_active == True,  # noqa: E712
        )
    ))

    if not channels:
        await redis.setex(cache_key, _SUB_CACHE_TTL, "1")
        return True

    is_subscribed = True
    for channel in channels:
        try:
            member = await bot.get_chat_member(channel.telegram_id, telegram_id)
        except (TelegramBadRequest, TelegramForbiddenError) as exc:
            # Бот не в канале или нет прав — канал пропускаем, но сообщаем админам
            logger.warning(
                "sub_check: cannot check channel %s for user %s: %s",
                channel.telegram_id, telegram_id, exc,
            )
            await _alert_unavailable_channel(bot, channel, str(exc))
            continue

        if not is_channel_member(member.status, getattr(member, "is_member", None)):
            is_subscribed = False
            break

    await redis.setex(cache_key, _SUB_CACHE_TTL, "1" if is_subscribed else "0")
    logger.debug(
        "sub_check telegram_id=%s channels=%d → %s (cached %ds)",
        telegram_id, len(channels), is_subscribed, _SUB_CACHE_TTL,
    )
    return is_subscribed


async def _alert_unavailable_channel(bot: Bot, channel: Channel, error: str) -> None:
    redis = await get_redis()
    key = _CHANNEL_ALERT_KEY.format(channel_id=channel.telegram_id)
    # SET NX: первый за час получает право отправить предупреждение
    if not await redis.set(key, "1", ex=_CHANNEL_ALERT_TTL, nx=True):
        return

    text = (
        "⚠️ <b>Не удаётся проверить подписку</b>\n\n"
        f"Канал: <b>{html.escape(channel.title)}</b> "
        f"(<code>{channel.telegram_id}</code>)\n"
        f"Ошибка: <i>{html.escape(error)}</i>\n\n"
        "Пока это не исправлено, подписка на этот канал не проверяется. "
        "Убедитесь, что бот — администратор канала."
    )
    # В фоне — не задерживаем ответ пользователю
    create_background_task(
        notify_admins(bot, text),
        name=f"channel_alert:{channel.telegram_id}",
    )


async def invalidate_subscription_cache(telegram_id: int) -> None:
    """Сбрасывает кэш подписки для пользователя."""
    redis = await get_redis()
    await redis.delete(_SUB_CACHE_KEY.format(telegram_id=telegram_id))
    logger.debug("sub_cache invalidated for telegram_id=%s", telegram_id)
