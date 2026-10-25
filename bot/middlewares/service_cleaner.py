"""
Чистка системных сообщений в группах.

Удаляет «вошёл / вышел / удалён», смену названия и фото группы, закрепы,
видеочаты, темы форума и прочие служебные сообщения во всех группах,
где бот — администратор с правом «Удаление сообщений».

Регистрируется ПЕРВЫМ на dp.update: служебное сообщение удаляется и дальше
не идёт — без сессии БД, без создания пользователей и без ответов в группу.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import Message, TelegramObject, Update

from bot.core.config import settings

logger = logging.getLogger(__name__)

_GROUP_TYPES = frozenset({"group", "supergroup"})

# Строки, а не ContentType.*: так код не сломается на версии aiogram без какого-то типа
_SERVICE_TYPES: frozenset[str] = frozenset({
    # Участники
    "new_chat_members",          # вошёл / добавили
    "left_chat_member",          # вышел / удалили
    # Оформление группы
    "new_chat_title",
    "new_chat_photo",
    "delete_chat_photo",
    "chat_background_set",
    "message_auto_delete_timer_changed",
    "pinned_message",
    # Создание / миграция
    "group_chat_created",
    "supergroup_chat_created",
    "migrate_to_chat_id",
    "migrate_from_chat_id",
    # Видеочаты
    "video_chat_scheduled",
    "video_chat_started",
    "video_chat_ended",
    "video_chat_participants_invited",
    # Темы форума
    "forum_topic_created",
    "forum_topic_edited",
    "forum_topic_closed",
    "forum_topic_reopened",
    "general_forum_topic_hidden",
    "general_forum_topic_unhidden",
    # Прочее
    "boost_added",
    "proximity_alert_triggered",
    "write_access_allowed",
    "users_shared",
    "chat_shared",
})


class ServiceMessageCleanerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        message = _extract_message(event)
        if message is None or not _is_group_service_message(message):
            return await handler(event, data)

        await _delete(message)
        # Дальше не передаём: служебное сообщение боту больше не нужно
        return None


def _extract_message(event: TelegramObject) -> Message | None:
    if isinstance(event, Update):
        return event.message
    return event if isinstance(event, Message) else None


def _is_group_service_message(message: Message) -> bool:
    return (
        settings.CLEAN_SERVICE_MESSAGES
        and message.chat.type in _GROUP_TYPES
        and message.content_type in _SERVICE_TYPES
    )


async def _delete(message: Message, attempt: int = 1) -> None:
    try:
        await message.delete()
    except TelegramRetryAfter as e:
        # При массовом наплыве вступивших Telegram может попросить подождать
        if attempt < 2:
            await asyncio.sleep(e.retry_after + 1)
            await _delete(message, attempt + 1)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        # Бот не админ, нет права на удаление или сообщение уже удалено
        logger.debug(
            "cannot delete service msg chat=%s type=%s: %s",
            message.chat.id, message.content_type, e,
        )
