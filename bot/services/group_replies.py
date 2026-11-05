"""
Чистка ответов бота на /link и /app в группах:
  - новый ответ на команду удаляет прошлый ответ на ту же команду в чате;
  - ответы удаляются по таймеру (GROUP_LINK_REPLY_TTL / GROUP_APP_REPLY_TTL).

Ошибки Redis и Telegram логируются и не ломают ответ на команду.
Для удаления бот должен быть администратором группы.
"""
from __future__ import annotations

import logging
import time

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from redis.exceptions import RedisError

from bot.core.config import settings
from bot.core.redis_client import get_redis
from bot.utils.reply_cleanup import claim_expired, remember_reply

logger = logging.getLogger(__name__)


def reply_ttl(command: str) -> int:
    """Через сколько секунд удалить ответ на команду (0 — не удалять по таймеру)."""
    if command == "link":
        return settings.GROUP_LINK_REPLY_TTL
    if command == "app":
        return settings.GROUP_APP_REPLY_TTL
    return 0


async def track_reply(bot: Bot, chat_id: int, command: str, message_id: int) -> None:
    """Запоминает новый ответ и удаляет предыдущий ответ на ту же команду."""
    try:
        redis = await get_redis()
        previous = await remember_reply(
            redis,
            chat_id,
            command,
            message_id,
            ttl=reply_ttl(command),
            now=time.time(),
        )
    except RedisError:
        logger.warning("group replies: redis error, reply not tracked", exc_info=True)
        return

    if previous is not None:
        await delete_messages(bot, chat_id, [previous])


async def cleanup_expired_replies(bot: Bot) -> None:
    """Фоновая задача: удаляет ответы, у которых вышло время."""
    try:
        redis = await get_redis()
        expired = await claim_expired(redis, time.time())
    except RedisError:
        logger.warning("group replies cleanup: redis error", exc_info=True)
        return

    for chat_id, message_ids in expired.items():
        await delete_messages(bot, chat_id, message_ids)


async def delete_messages(bot: Bot, chat_id: int, message_ids: list[int]) -> None:
    # deleteMessages молча пропускает уже удалённые сообщения (до 100 за раз)
    try:
        await bot.delete_messages(chat_id=chat_id, message_ids=message_ids)
    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as exc:
        # Нет прав на удаление, бота убрали из группы или флуд-лимит
        logger.debug(
            "group replies: cannot delete chat=%s ids=%s: %s", chat_id, message_ids, exc,
        )
