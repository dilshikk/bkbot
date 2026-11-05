from __future__ import annotations

import logging

from aiogram import Bot

from bot.core.config import settings

logger = logging.getLogger(__name__)


async def notify_admins(bot: Bot, text: str) -> None:
    """Рассылает уведомление всем ADMIN_IDS. Ошибки не бросает."""
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as e:
            logger.warning("cannot notify admin=%s: %s", admin_id, e)
