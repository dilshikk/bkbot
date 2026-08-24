from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Settings


@dataclass(frozen=True)
class SettingsData:
    """
    Иммутабельный DTO настроек.
    Возвращается из get_settings — безопасен вне сессии (нет DetachedInstanceError).
    """
    bot_enabled: bool
    maintenance: bool
    maintenance_text: str
    welcome_text: str
    after_sub_text: str
    support_link: str | None
    version: str
    # ── Приложение (APK) ──
    app_enabled: bool
    app_file_id: str | None
    app_caption: str | None


_DEFAULTS = SettingsData(
    bot_enabled=True,
    maintenance=False,
    maintenance_text="🛠 Технические работы. Скоро вернёмся.",
    welcome_text="👋 Привет, {name}!",
    after_sub_text="✅ Отлично! Теперь у вас есть доступ.",
    support_link=None,
    version="1.0.0",
    app_enabled=False,
    app_file_id=None,
    app_caption=None,
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
        app_enabled=row.app_enabled,
        app_file_id=row.app_file_id,
        app_caption=row.app_caption,
    )
