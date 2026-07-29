from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Settings


@dataclass(frozen=True)
class SettingsData:
    """
    Иммутабельный DTO настроек.

    FIX: ранее возвращался модульный экземпляр Settings (ORM-объект без сессии).
    Это приводило к DetachedInstanceError при обращении к lazy-атрибутам и
    к общему изменяемому состоянию между запросами.
    Теперь возвращается plain dataclass — безопасен вне сессии.
    """
    bot_enabled: bool
    maintenance: bool
    maintenance_text: str
    welcome_text: str
    after_sub_text: str
    support_link: str | None
    version: str


_DEFAULTS = SettingsData(
    bot_enabled=True,
    maintenance=False,
    maintenance_text="🛠 Технические работы. Скоро вернёмся.",
    welcome_text="👋 Привет, {name}!",
    after_sub_text="✅ Отлично! Теперь у вас есть доступ.",
    support_link=None,
    version="1.0.0",
)


async def get_settings(session: AsyncSession) -> SettingsData:
    """Возвращает настройки или дефолт если таблица пустая."""
    result = await session.execute(select(Settings).limit(1))
    row: Settings | None = result.scalar_one_or_none()

    if row is None:
        return _DEFAULTS

    return SettingsData(
        bot_enabled=row.bot_enabled,
        maintenance=row.maintenance,
        maintenance_text=row.maintenance_text,
        welcome_text=row.welcome_text,
        after_sub_text=row.after_sub_text,
        support_link=row.support_link,
        version=row.version,
    )
