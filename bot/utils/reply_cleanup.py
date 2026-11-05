"""
Учёт сообщений по /link и /app в группах для последующего удаления.

Telegram не даёт боту читать историю чата, поэтому бот сам запоминает
сообщения в Redis (это переживает перезапуск бота). На каждый вызов
команды запоминаются два сообщения: сама команда участника и ответ бота.

  group_reply:last:{chat_id}:{command}
      id сообщений последнего вызова команды в чате через запятую
      ("команда,ответ"). Новый вызов заменяет старый, старые сообщения
      нужно удалить — в чате остаётся одна свежая пара.

  group_reply:expire  (sorted set)
      "chat_id:message_id" со временем удаления (unix-время).
      Фоновая задача забирает просроченные записи и удаляет сообщения.

Используются только команды, доступные в старых версиях Redis (< 6.2):
без SET ... GET, вместо него GETSET + EXPIRE в одной транзакции.

Модуль не зависит от конфига и aiogram — легко тестируется.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from redis.asyncio import Redis

EXPIRE_KEY: Final[str] = "group_reply:expire"
_LAST_KEY: Final[str] = "group_reply:last:{chat_id}:{command}"

# Бот может удалить сообщение только в течение 48 часов —
# дольше помнить последний вызов бессмысленно
_LAST_KEY_TTL: Final[int] = 48 * 3600


def _member(chat_id: int, message_id: int) -> str:
    return f"{chat_id}:{message_id}"


def _parse_member(member: str) -> tuple[int, int] | None:
    chat_id, _, message_id = member.rpartition(":")
    try:
        return int(chat_id), int(message_id)
    except ValueError:
        return None


def _parse_ids(raw: str | None) -> list[int]:
    """"10,11" -> [10, 11]. Старый формат (один id) тоже читается."""
    if not raw:
        return []
    ids: list[int] = []
    for part in raw.split(","):
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return ids


async def _swap_last(redis: Redis, key: str, value: str) -> str | None:
    """Сохраняет новое значение и возвращает прежнее. Атомарно, работает на любом Redis."""
    async with redis.pipeline(transaction=True) as pipe:
        pipe.getset(key, value)
        pipe.expire(key, _LAST_KEY_TTL)
        previous, _ = await pipe.execute()
    return previous


async def remember_reply(
    redis: Redis,
    chat_id: int,
    command: str,
    message_ids: Sequence[int],
    *,
    ttl: int,
    now: float,
) -> list[int]:
    """
    Запоминает сообщения нового вызова команды (команда участника и ответ бота)
    и ставит их на удаление через `ttl` секунд (ttl <= 0 — по таймеру не удалять).

    Возвращает id сообщений предыдущего вызова этой же команды в этом чате —
    их нужно удалить. Пустой список — удалять нечего.
    """
    current = list(dict.fromkeys(message_ids))
    if not current:
        return []

    key = _LAST_KEY.format(chat_id=chat_id, command=command)
    previous = await _swap_last(redis, key, ",".join(map(str, current)))

    if ttl > 0:
        await redis.zadd(
            EXPIRE_KEY, {_member(chat_id, mid): now + ttl for mid in current}
        )

    to_delete = [mid for mid in _parse_ids(previous) if mid not in current]
    if to_delete:
        # Старые сообщения удаляются прямо сейчас — таймер для них больше не нужен
        await redis.zrem(EXPIRE_KEY, *(_member(chat_id, mid) for mid in to_delete))
    return to_delete


async def claim_expired(
    redis: Redis,
    now: float,
    limit: int = 100,
) -> dict[int, list[int]]:
    """
    Забирает просроченные сообщения: {chat_id: [message_id, ...]}.
    Забранные записи удаляются из очереди, поэтому каждое сообщение
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
