"""
Фильтр сообщений из групп.

Регистрируется на dp.update сразу после ServiceMessageCleanerMiddleware
и ДО DbSessionMiddleware: всё лишнее из групп отбрасывается без обращения к БД.

В группах пропускаются только /app и /link, если:
  - функция включена (GROUP_COMMANDS_ENABLED)
  - чат разрешён (GROUP_COMMANDS_CHAT_IDS, пусто — все группы)
  - команда адресована этому боту (/app или /app@этот_бот)
  - отправитель не бот (анонимные админы группы разрешены)
  - в этом чате не сработал кулдаун (GROUP_COMMANDS_COOLDOWN)

Команда, отброшенная кулдауном, сразу удаляется — иначе она останется
в чате без ответа (свежий ответ на неё и так уже есть выше).

Разрешённая команда отмечается в data[GROUP_COMMAND_KEY] — по этой метке
остальные middleware понимают, что это групповая команда.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import Message, TelegramObject, Update
from redis.exceptions import RedisError

from bot.core.config import settings
from bot.core.redis_client import get_redis
from bot.services.group_replies import delete_messages
from bot.utils.group_commands import (
    GROUP_CHAT_TYPES,
    GROUP_COMMAND_KEY,
    acquire_cooldown,
    parse_group_command,
)

logger = logging.getLogger(__name__)


class GroupCommandGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        message = event.message if isinstance(event, Update) else None
        if message is None or message.chat.type not in GROUP_CHAT_TYPES:
            return await handler(event, data)

        bot: Bot = data["bot"]
        command = await _resolve_command(message, bot)
        if command is None:
            # Всё остальное в группах бот молча игнорирует
            return None

        if not await _try_cooldown(message.chat.id, command):
            logger.debug("group command on cooldown chat=%s cmd=%s", message.chat.id, command)
            await delete_messages(bot, message.chat.id, [message.message_id])
            return None

        data[GROUP_COMMAND_KEY] = command
        return await handler(event, data)


async def _resolve_command(message: Message, bot: Bot) -> str | None:
    """Команда для этого бота или None, если сообщение нас не касается."""
    if not settings.GROUP_COMMANDS_ENABLED:
        return None

    allowed_chats = settings.GROUP_COMMANDS_CHAT_IDS
    if allowed_chats and message.chat.id not in allowed_chats:
        return None

    # Не отвечаем другим ботам (защита от петель).
    # У анонимного админа from_user — служебный бот, но есть sender_chat.
    sender = message.from_user
    if sender is not None and sender.is_bot and message.sender_chat is None:
        return None

    me = await bot.me()
    return parse_group_command(message.text, me.username)


async def _try_cooldown(chat_id: int, command: str) -> bool:
    try:
        redis = await get_redis()
        return await acquire_cooldown(
            redis, chat_id, command, settings.GROUP_COMMANDS_COOLDOWN
        )
    except RedisError:
        # Redis недоступен — не ломаем команду, просто без кулдауна
        logger.warning("group cooldown: redis error, skipping", exc_info=True)
        return True
