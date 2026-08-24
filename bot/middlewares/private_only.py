import time

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import TelegramObject, Message


class PrivateOnlyMiddleware(BaseMiddleware):
    """
    Блокирует обработку сообщений вне личных чатов.
    В группах бот полностью молчит — не отвечает ни в группу, ни в ЛС.
    """

    def __init__(self, cooldown: int = 300):
        self.cooldown = cooldown
        self._last_notified: dict[int, float] = {}

    async def __call__(self, handler, event: TelegramObject, data):
        if not isinstance(event, Message) or event.chat.type == "private":
            return await handler(event, data)

        # Сообщение из группы/супергруппы/канала — просто игнорируем, не отвечаем
        return
