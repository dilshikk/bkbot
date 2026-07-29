from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.repositories.user_repo import UserRepository
from bot.services.subscription_service import check_all_subscriptions
from bot.keyboards.user import subscription_keyboard

# Тексты которые всегда пропускаем без проверки подписки
_PASS_THROUGH = {"/start"}


class SubscriptionGuardMiddleware(BaseMiddleware):
    """
    Перехватывает каждое сообщение.
    Если пользователь отписался — показывает экран подписки.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        text = event.text or ""
        if text in _PASS_THROUGH:
            return await handler(event, data)

        db_user: User | None = data.get("db_user")
        if db_user is None:
            return await handler(event, data)

        session: AsyncSession = data["session"]

        # Кешируем в рамках апдейта — не ходим в Telegram повторно
        is_subscribed = await check_all_subscriptions(
            event.bot, session, db_user.telegram_id
        )

        if not is_subscribed:
            user_repo = UserRepository(session)
            await user_repo.set_subscribed(db_user.id, False)

            await event.answer(
                "📢 Вы отписались от одного из каналов.\n"
                "Подпишитесь снова для продолжения:",
                reply_markup=await subscription_keyboard(session),
            )
            return None  # Прерываем — хендлер не вызывается

        return await handler(event, data)