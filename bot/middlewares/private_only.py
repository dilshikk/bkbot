from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.utils.group_commands import GROUP_COMMAND_KEY


class PrivateOnlyMiddleware(BaseMiddleware):
    """
    Пропускает личные сообщения и разрешённые команды групп
    (/app, /link — их отмечает GroupCommandGateMiddleware).
    Всё остальное вне личных чатов молча игнорируется.
    """

    def __init__(self, cooldown: int = 300):
        # Параметр оставлен для обратной совместимости вызова в main.py
        self.cooldown = cooldown

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.chat.type == "private":
            return await handler(event, data)

        if data.get(GROUP_COMMAND_KEY):
            return await handler(event, data)

        return None
