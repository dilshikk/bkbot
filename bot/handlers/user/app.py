# bot/handlers/user/app.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, ActionType
from bot.repositories.log_repo import LogRepository
from bot.services.delivery import (
    app_caption,
    available_app_file_id,
    increment_app_downloads,
)
from bot.services.settings_service import get_settings

router = Router(name="user.app")


@router.message(F.text == "📱 Получить приложение")
async def get_app(message: Message, session: AsyncSession, db_user: User) -> None:
    settings = await get_settings(session)
    file_id = available_app_file_id(settings)

    if file_id is None:
        await message.answer("⏳ Приложение пока недоступно. Попробуйте позже.")
        return

    # Логируем и увеличиваем счётчик скачиваний
    await LogRepository(session).log(
        ActionType.GET_APP,
        user_id=db_user.id,
        telegram_id=db_user.telegram_id,
    )
    await increment_app_downloads(session)

    await message.answer_document(
        document=file_id,
        caption=app_caption(settings),
        parse_mode="HTML",
    )
