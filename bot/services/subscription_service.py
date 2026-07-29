from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Channel


async def check_all_subscriptions(
    bot: Bot,
    session: AsyncSession,
    telegram_id: int,
) -> bool:
    """
    Возвращает True только если пользователь подписан
    на ВСЕ обязательные активные каналы.
    """
    channels = await session.scalars(
        select(Channel).where(
            Channel.is_required == True,
            Channel.is_active == True,
        )
    )
    channels = list(channels)

    if not channels:
        return True  # нет обязательных каналов — пропускаем

    for channel in channels:
        try:
            member = await bot.get_chat_member(channel.telegram_id, telegram_id)
            if member.status in ("left", "kicked", "banned"):
                return False
        except (TelegramBadRequest, TelegramForbiddenError):
            # Бот не в канале или нет прав — пропускаем этот канал
            continue

    return True