# bot/handlers/user/app.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, ActionType, Settings
from bot.repositories.log_repo import LogRepository
from bot.services.settings_service import get_settings

router = Router(name="user.app")


@router.message(F.text == "📱 Получить приложение")
async def get_app(message: Message, session: AsyncSession, db_user: User) -> None:
    settings = await get_settings(session)

    if not settings.app_enabled or not settings.app_file_id:
        await message.answer("⏳ Приложение пока недоступно. Попробуйте позже.")
        return

    # Логируем и увеличиваем счётчик скачиваний
    log_repo = LogRepository(session)
    await log_repo.log(
        ActionType.GET_APP,
        user_id=db_user.id,
        telegram_id=db_user.telegram_id,
    )

    result = await session.execute(select(Settings).limit(1))
    s = result.scalar_one_or_none()
    if s is not None:
        s.app_download_count = (s.app_download_count or 0) + 1
        await session.flush()

    caption = settings.app_caption or "📱 Актуальная версия приложения"
    if settings.app_file_name:
        caption += f"\n\n📄 <code>{settings.app_file_name}</code>"

    await message.answer_document(
        document=settings.app_file_id,
        caption=caption,
        parse_mode="HTML",
    )
