"""
Разбор и ограничение команд, доступных в группах.

Модуль не зависит от конфига и aiogram — легко тестируется.
"""
from __future__ import annotations

from typing import Final

from redis.asyncio import Redis

GROUP_CHAT_TYPES: Final[frozenset[str]] = frozenset({"group", "supergroup"})

# Команды, на которые бот отвечает в группах
GROUP_COMMANDS: Final[frozenset[str]] = frozenset({"app", "link"})

# Ключ в data aiogram: middleware отмечает разрешённую групповую команду
GROUP_COMMAND_KEY: Final[str] = "group_command"

_COOLDOWN_KEY: Final[str] = "group_cmd:cooldown:{chat_id}:{command}"


def parse_group_command(text: str | None, bot_username: str | None) -> str | None:
    """
    Возвращает имя команды ("app" / "link"), если сообщение — команда этому боту.

    "/app", "/app@MyBot", "/link что-то" → команда.
    "/app@OtherBot" → None: команда адресована другому боту.
    Регистр команды учитывается так же, как в aiogram Command.
    """
    if not text or not text.startswith("/"):
        return None

    token = text.split(maxsplit=1)[0][1:]
    command, has_mention, mention = token.partition("@")

    if has_mention:
        if not bot_username or mention.lower() != bot_username.lower():
            return None

    return command if command in GROUP_COMMANDS else None


async def acquire_cooldown(
    redis: Redis,
    chat_id: int,
    command: str,
    seconds: int,
) -> bool:
    """
    True — команду можно выполнить (кулдаун занят на `seconds` секунд).
    False — та же команда в этом чате уже выполнялась недавно.
    """
    if seconds <= 0:
        return True

    key = _COOLDOWN_KEY.format(chat_id=chat_id, command=command)
    return bool(await redis.set(key, "1", ex=seconds, nx=True))
