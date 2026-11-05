"""
Общая логика выдачи зеркала и приложения.

Используется и в личных сообщениях, и в группах, чтобы тексты,
кнопки и счётчики везде были одинаковыми.
"""
from __future__ import annotations

import html
from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Settings
from bot.services.settings_service import SettingsData

REFRESH_MIRROR_CALLBACK = "refresh_mirror"
DEFAULT_APP_CAPTION = "📱 Актуальная версия приложения"


# ── Зеркало ───────────────────────────────────────────────────

def mirror_text(url: str, bot_tag: str) -> str:
    # Экранируем URL — кавычка или < в адресе ломали HTML сообщения
    return (
        "🎯 <b>Актуальное рабочее зеркало</b>\n\n"
        f'👉 <a href="{html.escape(url, quote=True)}">Перейти на сайт</a>\n\n'
        f"🤖 <b>Отправлено ботом:</b> {bot_tag}"
    )


def mirror_keyboard(
    url: str,
    bot_tag: str,
    *,
    with_refresh: bool = True,
) -> InlineKeyboardMarkup:
    share_url = (
        "https://t.me/share/url"
        f"?url={quote(url)}"
        f"&text={quote(f'🎯 Актуальное рабочее зеркало {bot_tag}')}"
    )
    rows = [
        [InlineKeyboardButton(text="🚀 Перейти", url=url)],
        [InlineKeyboardButton(text="📤 Поделиться", url=share_url)],
    ]
    if with_refresh:
        rows.append([
            InlineKeyboardButton(text="🔄 Обновить", callback_data=REFRESH_MIRROR_CALLBACK),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Приложение ────────────────────────────────────────────────

def available_app_file_id(s: SettingsData) -> str | None:
    """file_id APK, если приложение включено и загружено, иначе None."""
    if not s.app_enabled:
        return None
    return s.app_file_id or None


def app_caption(s: SettingsData) -> str:
    caption = s.app_caption or DEFAULT_APP_CAPTION
    if s.app_file_name:
        caption += f"\n\n📄 <code>{html.escape(s.app_file_name)}</code>"
    return caption


async def increment_app_downloads(session: AsyncSession) -> None:
    """Атомарный инкремент — без гонки при одновременных скачиваниях."""
    settings_id = select(Settings.id).limit(1).scalar_subquery()
    await session.execute(
        update(Settings)
        .where(Settings.id == settings_id)
        .values(app_download_count=Settings.app_download_count + 1)
    )
