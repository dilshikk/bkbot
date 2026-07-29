from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.database.models import Channel


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎯 Получить зеркало")],
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