from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InaccessibleMessage
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, ActionType
from bot.keyboards.user import main_menu_keyboard, subscription_keyboard
from bot.repositories.log_repo import LogRepository
from bot.repositories.user_repo import UserRepository
from bot.services.settings_service import get_settings
from bot.services.subscription_service import (
    check_all_subscriptions,
    invalidate_subscription_cache,
)

router = Router(name="user.start")
logger = logging.getLogger(__name__)


# ── /start ────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(
    message: Message,
    session: AsyncSession,
    db_user: User,
) -> None:
    raw_text = message.text or ""
    parts = raw_text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else "direct"

    if message.from_user is None:
        return

    user_repo = UserRepository(session)
    log_repo = LogRepository(session)

    await user_repo.set_source(db_user.id, payload)
    await log_repo.log(
        ActionType.START,
        user_id=db_user.id,
        telegram_id=message.from_user.id,
        meta={"source": payload},
    )

    # Проверку maintenance убрали — она теперь в MaintenanceMiddleware
    # и блокирует весь бот до того как запросы дойдут до хендлеров
    bot_settings = await get_settings(session)

    await message.answer(
        bot_settings.welcome_text.format(name=db_user.full_name),
    )

    await _handle_subscription_check(message, session, db_user, bot_settings=bot_settings)


# ── Проверка подписки (callback-кнопка) ───────────────────────

@router.callback_query(F.data == "check_subscription")
async def on_check_subscription(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
) -> None:
    if call.message is None or isinstance(call.message, InaccessibleMessage):
        await call.answer("❌ Не удалось обработать запрос", show_alert=True)
        return

    await call.answer()

    await invalidate_subscription_cache(db_user.telegram_id)

    log_repo = LogRepository(session)
    user_repo = UserRepository(session)
    is_subscribed = await check_all_subscriptions(
        call.bot, session, db_user.telegram_id, use_cache=False
    )

    if not is_subscribed:
        await log_repo.log(
            ActionType.SUB_FAILED,
            user_id=db_user.id,
            telegram_id=db_user.telegram_id,
        )
        try:
            await call.message.edit_text(
                "❌ Вы ещё не подписались на все каналы.",
                reply_markup=await subscription_keyboard(session),
            )
        except TelegramBadRequest:
            pass
        return

    await user_repo.set_subscribed(db_user.id, True)
    await log_repo.log(
        ActionType.SUB_PASSED,
        user_id=db_user.id,
        telegram_id=db_user.telegram_id,
    )

    await _delete_safe(call.message)

    bot_settings = await get_settings(session)
    await call.message.answer(
        bot_settings.after_sub_text,
        reply_markup=main_menu_keyboard(),
    )


# ── Проверка подписки (кнопка Reply-клавиатуры) ───────────────

@router.message(F.text == "🔄 Проверить подписку")
async def on_check_subscription_text(
    message: Message,
    session: AsyncSession,
    db_user: User,
) -> None:
    await _confirm_subscription(message, session, db_user)


# ── Внутренняя логика ─────────────────────────────────────────

async def _handle_subscription_check(
    message: Message,
    session: AsyncSession,
    db_user: User,
    *,
    bot_settings=None,
) -> None:
    log_repo = LogRepository(session)
    user_repo = UserRepository(session)

    was_subscribed = db_user.is_subscribed
    is_subscribed = await check_all_subscriptions(
        message.bot, session, db_user.telegram_id
    )

    if not is_subscribed:
        await user_repo.set_subscribed(db_user.id, False)
        await log_repo.log(
            ActionType.SUB_FAILED,
            user_id=db_user.id,
            telegram_id=db_user.telegram_id,
        )
        await message.answer(
            "📢 Для доступа подпишитесь на наши каналы:",
            reply_markup=await subscription_keyboard(session),
        )
        return

    await user_repo.set_subscribed(db_user.id, True)
    await log_repo.log(
        ActionType.SUB_PASSED,
        user_id=db_user.id,
        telegram_id=db_user.telegram_id,
    )

    if bot_settings is None:
        bot_settings = await get_settings(session)

    if not was_subscribed:
        await message.answer(
            bot_settings.after_sub_text,
            reply_markup=main_menu_keyboard(),
        )
    else:
        await message.answer("🏠 Главное меню", reply_markup=main_menu_keyboard())


async def _confirm_subscription(
    message: Message,
    session: AsyncSession,
    db_user: User,
) -> None:
    await invalidate_subscription_cache(db_user.telegram_id)

    log_repo = LogRepository(session)
    user_repo = UserRepository(session)

    is_subscribed = await check_all_subscriptions(
        message.bot, session, db_user.telegram_id, use_cache=False
    )

    if not is_subscribed:
        await message.answer(
            "❌ Вы ещё не подписались на все каналы.",
            reply_markup=await subscription_keyboard(session),
        )
        return

    await user_repo.set_subscribed(db_user.id, True)
    await log_repo.log(
        ActionType.SUB_PASSED,
        user_id=db_user.id,
        telegram_id=db_user.telegram_id,
    )

    bot_settings = await get_settings(session)
    await message.answer(
        bot_settings.after_sub_text,
        reply_markup=main_menu_keyboard(),
    )


async def _delete_safe(message: Message) -> None:
    try:
        await message.delete()
    except (TelegramBadRequest, Exception) as e:
        logger.debug("could not delete message %s: %s", message.message_id, e)
