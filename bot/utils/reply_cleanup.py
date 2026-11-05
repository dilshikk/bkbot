"""
Учёт ответов бота на /link и /app в группах для последующего удаления.

Telegram не даёт боту читать историю чата, поэтому бот сам запоминает
свои ответы в Redis (это переживает перезапуск бота):

  group_reply:last:{chat_id}:{command}
      id последнего ответа на команду в чате. Новый ответ заменяет старый,
      старый нужно удалить — в чате остаётся одна свежая ссылка.

  group_reply:expire  (sorted set)
      "chat_id:message_id" со временем удаления (unix-время).
      Фоновая задача забирает просроченные записи и удаляет сообщения.

Используются только команды, доступные в старых версиях Redis (< 6.2):
без SET ... GET, вместо него GETSET + EXPIRE в одной транзакции.

Модуль не зависит от конфига и aiogram — легко тестируется.
"""
from __future__ import annotations

from typing import Final

from redis.asyncio import Redis

EXPIRE_KEY: Final[str] = "group_reply:expire"
_LAST_KEY: Final[str] = "group_reply:last:{chat_id}:{command}"

# Бот может удалить своё сообщение только в течение 48 часов —
# дольше помнить последний ответ бессмысленно
_LAST_KEY_TTL: Final[int] = 48 * 3600


def _member(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _parse_member(member: str) -> tuple[int, int] | None:
    chat_id, _, message_id = member.rpartition(":")
    try:
        return int(chat_id), int(message_id)
    except ValueError:
        return None


async def _swap_last_reply(redis: Redis, key: str, message_id: int) -> str | None:
    """Сохраняет новый id и возвращает прежний. Атомарно, работает на любом Redis."""
    async with redis.pipeline(transaction=True) as pipe:
        pipe.getset(key, str(message_id))
        pipe.expire(key, _LAST_KEY_TTL)
        previous, _ = await pipe.execute()
    return previous


async def remember_reply(
    redis: Redis,
    chat_id: int,
    command: str,
    message_id: int,
    *,
    ttl: int,
    now: float,
) -> int | None:
    """
    Запоминает новый ответ бота и ставит его на удаление через `ttl` секунд
    (ttl <= 0 — по таймеру не удалять).

    Возвращает id предыдущего ответа на эту же команду в этом чате —
    его нужно удалить. None — удалять нечего.
    """
    key = _LAST_KEY.format(chat_id=chat_id, command=command)
    previous = await _swap_last_reply(redis, key, message_id)

    if ttl > 0:
        await redis.zadd(EXPIRE_KEY, {_member(chat_id, message_id): now + ttl})

    if previous is None:
        return None
    try:
        previous_id = int(previous)
    except ValueError:
        return None
    if previous_id == message_id:
        return None

    # Старый ответ удаляется прямо сейчас — таймер для него больше не нужен
    await redis.zrem(EXPIRE_KEY, _member(chat_id, previous_id))
    return previous_id


async def claim_expired(
    redis: Redis,
    now: float,
    limit: int = 100,
) -> dict[int, list[int]]:
    """
    Забирает просроченные ответы: {chat_id: [message_id, ...]}.
    Забранные записи удаляются из очереди, поэтому каждый ответ
    достаётся только одному вызову.
    """
    members = await redis.zrangebyscore(EXPIRE_KEY, "-inf", now, start=0, num=limit)

    claimed: dict[int, list[int]] = {}
    for member in members:
        # zrem вернёт 0, если запись уже забрал другой вызов
        if not await redis.zrem(EXPIRE_KEY, member):
            continue
        parsed = _parse_member(member)
        if parsed is None:
            continue
        chat_id, message_id = parsed
        claimed.setdefault(chat_id, []).append(message_id)
    return claimed
