from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.config import settings
from bot.database.models import User
from bot.repositories.user_repo import UserRepository
from bot.services.subscription_service import check_all_subscriptions
from bot.keyboards.user import subscription_keyboard

# Тексты которые всегда пропускаем без проверки подписки.
# /start (с любой меткой источника) обрабатывается отдельно через startswith.
_PASS_THROUGH_TEXTS: frozenset[str] = frozenset({"🔄 Проверить подписку"})
# Callback data которые пропускаем (кнопка "Проверить подписку")
_PASS_THROUGH_CALLBACKS: frozenset[str] = frozenset({"check_subscription"})


class SubscriptionGuardMiddleware(BaseMiddleware):
    """
    Регистрируется на dp.message и dp.callback_query (НЕ на dp.update).
    Если пользователь отписался — показывает экран подписки.
    Администраторы (settings.ADMIN_IDS) полностью освобождены от проверки.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = _extract_user_id(event)
        if user_id in settings.ADMIN_IDS:
            return await handler(event, data)

        if isinstance(event, Message):
            return await self._handle_message(handler, event, data)
        if isinstance(event, CallbackQuery):
            return await self._handle_callback(handler, event, data)
        return await handler(event, data)

    async def _handle_message(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        text = event.text or ""
        # /start пропускаем с любой меткой: "/start", "/start ref123"
        if text.startswith("/start") or text in _PASS_THROUGH_TEXTS:
            return await handler(event, data)

        if not await self._is_subscribed(event, data):
            return None
        return await handler(event, data)

    async def _handle_callback(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        if (event.data or "") in _PASS_THROUGH_CALLBACKS:
            return await handler(event, data)

        if not await self._is_subscribed(event, data):
            await event.answer(
                "📢 Вы отписались от одного из каналов. Подпишитесь снова.",
                show_alert=True,
            )
            return None
        return await handler(event, data)

    @staticmethod
    async def _is_subscribed(
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> bool:
        db_user: User | None = data.get("db_user")
        if db_user is None:
            return True

        session: AsyncSession = data["session"]
        is_subscribed = await check_all_subscriptions(
            event.bot, session, db_user.telegram_id
        )

        if not is_subscribed:
            user_repo = UserRepository(session)
            await user_repo.set_subscribed(db_user.id, False)

            if isinstance(event, Message):
                await event.answer(
                    "📢 Вы отписались от одного из каналов.\n"
                    "Подпишитесь снова для продолжения:",
                    reply_markup=await subscription_keyboard(session),
                )
            return False

        return True


def _extract_user_id(event: TelegramObject) -> int:
    from_user = getattr(event, "from_user", None)
    return from_user.id if from_user is not None else 0
