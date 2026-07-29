from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.repositories.user_repo import UserRepository
from bot.services.subscription_service import check_all_subscriptions
from bot.keyboards.user import subscription_keyboard

# Тексты/команды которые всегда пропускаем без проверки подписки
_PASS_THROUGH_TEXTS: frozenset[str] = frozenset({"/start"})
# Callback data которые пропускаем (кнопка "Проверить подписку")
_PASS_THROUGH_CALLBACKS: frozenset[str] = frozenset({"check_subscription"})


class SubscriptionGuardMiddleware(BaseMiddleware):
    """
    Перехватывает каждый апдейт.
    Если пользователь отписался — показывает экран подписки.

    FIX: ранее middleware перехватывала только Message, callback_query
    полностью обходил проверку подписки — пользователь мог использовать
    inline-кнопки без подписки на каналы.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Обрабатываем только Message и CallbackQuery
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
        if text in _PASS_THROUGH_TEXTS:
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
        # Кнопку "check_subscription" всегда пропускаем
        if (event.data or "") in _PASS_THROUGH_CALLBACKS:
            return await handler(event, data)

        if not await self._is_subscribed(event, data):
            # FIX: для callback отвечаем через answer(), а не через message.answer()
            # чтобы убрать "часики" у кнопки
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
        """
        Проверяет подписку и при необходимости обновляет флаг в БД.
        Возвращает True если подписан, False — если нет.
        """
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

            # Только для Message показываем клавиатуру с каналами
            if isinstance(event, Message):
                await event.answer(
                    "📢 Вы отписались от одного из каналов.\n"
                    "Подпишитесь снова для продолжения:",
                    reply_markup=await subscription_keyboard(session),
                )
            return False

        return True
