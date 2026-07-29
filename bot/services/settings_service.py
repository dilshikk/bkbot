from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Settings


_DEFAULT_SETTINGS = Settings(
    bot_enabled=True,
    maintenance=False,
    maintenance_text="🛠 Технические работы. Скоро вернёмся.",
    welcome_text="👋 Привет, {name}!",
    after_sub_text="✅ Отлично! Теперь у вас есть доступ.",
    support_link=None,
    version="1.0.0",
)


async def get_settings(session: AsyncSession) -> Settings:
    """Возвращает настройки или дефолт если таблица пустая."""
    result = await session.execute(select(Settings).limit(1))
    settings = result.scalar_one_or_none()
    return settings or _DEFAULT_SETTINGS