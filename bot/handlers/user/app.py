# bot/handlers/user/app.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, ActionType
from bot.repositories.log_repo import LogRepository
from bot.services.settings_service import get_settings

router = Router(name="user.app")


@router.message(F.text == "📱 Получить приложение")
async def get_app(message: Message, session: AsyncSession, db_user: User) -> None:
    settings = await get_settings(session)

    if not settings.app_enabled:
        await message.answer("⏳ Приложение пока недоступно. Попробуйте позже.")
        return

    log_repo = LogRepository(session)
    await log_repo.log(
        ActionType.GET_APP,
        user_id=db_user.id,
        telegram_id=db_user.telegram_id,
    )

    caption = settings.app_caption or "📱 Актуальная версия приложения"

    if settings.app_file_id:
        # Отправляем сохранённый APK по file_id
        await message.answer_document(
            document=settings.app_file_id,
            caption=caption,
            parse_mode="HTML",
        )
    else:
        # Файл ещё не загружен администратором
        await message.answer(
            "⏳ Приложение пока недоступно. Попробуйте позже."
        )
