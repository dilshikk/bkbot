from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.database.models import Channel, Settings


async def main_menu_keyboard(session: AsyncSession) -> ReplyKeyboardMarkup:
    """
    Главное меню пользователя.
    Кнопка «📱 Получить приложение» отображается только если app_enabled=True.
    """
    result = await session.execute(select(Settings).limit(1))
    settings = result.scalar_one_or_none()
    app_enabled = settings.app_enabled if settings else False

    first_row = [KeyboardButton(text="🎯 Получить зеркало")]
    if app_enabled:
        first_row.append(KeyboardButton(text="📱 Получить приложение"))

    return ReplyKeyboardMarkup(
        keyboard=[
            first_row,
            [KeyboardButton(text="📖 Как пользоваться"), KeyboardButton(text="🆘 Поддержка")],
            [KeyboardButton(text="ℹ️ О сервисе")],
        ],
        resize_keyboard=True,
    )


async def subscription_keyboard(session: AsyncSession) -> InlineKeyboardMarkup:
    """Кнопки для каждого обязательного канала + кнопка проверки."""
    channels = await session.scalars(
        select(Channel).where(
            Channel.is_required == True,
            Channel.is_active == True,
        )
    )
    buttons: list[list[InlineKeyboardButton]] = []

    for ch in channels:
        link = ch.invite_link or (f"https://t.me/{ch.username}" if ch.username else None)
        if link:
            buttons.append([
                InlineKeyboardButton(text=f"📢 {ch.title}", url=link)
            ])

    buttons.append([
        InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)
