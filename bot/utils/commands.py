"""
Устанавливает команды бота в Telegram.

Пользователи видят: /start, /help, /menu
Админы видят дополнительно: /admin
"""
from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)

from bot.core.config import settings

# Команды для всех пользователей
USER_COMMANDS = [
    BotCommand(command="start",  description="🚀 Запустить бота"),
    BotCommand(command="help",   description="❓ Помощь"),
]

# Дополнительные команды для админов
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand(command="admin",  description="🔐 Админ-панель"),
]


async def set_commands(bot: Bot) -> None:
    """Вызывать при старте бота в main.py."""

    # Команды для всех пользователей
    await bot.set_my_commands(
        commands=USER_COMMANDS,
        scope=BotCommandScopeAllPrivateChats(),
    )

    # Персональные команды для каждого админа
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.set_my_commands(
                commands=ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            pass  # Админ мог не запустить бота ещё


async def delete_commands(bot: Bot) -> None:
    """Вызывать при остановке бота."""
    await bot.delete_my_commands(
        scope=BotCommandScopeAllPrivateChats()
    )
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.delete_my_commands(
                scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception:
            pass
