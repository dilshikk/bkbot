import time

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import TelegramObject, Message


class PrivateOnlyMiddleware(BaseMiddleware):
    def __init__(self, cooldown: int = 300):
        self.cooldown = cooldown
        self._last_notified: dict[int, float] = {}

    async def __call__(self, handler, event: TelegramObject, data):
        if not isinstance(event, Message) or event.chat.type == "private":
            return await handler(event, data)

        user = event.from_user
        if user is None:
            return  # сообщение от канала/анонима — нечего слать в ЛС

        # антиспам: не долбим в группу/ЛС слишком часто на одного юзера
        now = time.monotonic()
        last = self._last_notified.get(user.id, 0)
        if now - last < self.cooldown:
            return
        self._last_notified[user.id] = now

        try:
            # Пытаемся написать пользователю в ЛС напрямую
            await event.bot.send_message(
                chat_id=user.id,
                text="Привет! Я заметил, что вы обратились ко мне в группе. "
                     "Пожалуйста, используйте личные сообщения для работы со мной.",
            )
        except TelegramForbiddenError:
            # Пользователь ещё не запускал бота в ЛС / заблокировал его —
            # пишем призыв прямо в группу
            try:
                await event.answer(
                    f"{user.mention_html()}, пожалуйста, перейдите в личные "
                    f"сообщения со мной, чтобы начать работу!",
                    parse_mode="HTML",
                )
            except Exception:
                pass

        return