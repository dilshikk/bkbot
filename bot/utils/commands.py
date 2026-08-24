"""
Устанавливает команды бота в Telegram по схеме:

Запуск бота
    │
    ▼
set_default_commands()
    │
    ├── Личные сообщения (AllPrivateChats)   → пользовательские команды
    ├── Группы (AllGroupChats)               → пустой список (скрыть)
    ├── Администраторы групп (AllChatAdmins) → пустой список (скрыть)
    └── ADMIN_IDS (BotCommandScopeChat)      → персональные команды
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
)

from bot.core.config import settings

logger = logging.getLogger(__name__)

# ── Наборы команд ─────────────────────────────────────────────

USER_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="🚀 Запустить бота"),
    BotCommand(command="menu",  description="🏠 Главное меню"),
    BotCommand(command="help",  description="❓ Помощь"),
]

ADMIN_COMMANDS: list[BotCommand] = USER_COMMANDS + [
    BotCommand(command="admin", description="🔐 Админ-панель"),
]

# Пустой список — Telegram скрывает меню команд полностью
_NO_COMMANDS: list[BotCommand] = []


# ── Установка ─────────────────────────────────────────────────

async def set_default_commands(bot: Bot) -> None:
    """
    Устанавливает команды при запуске бота.

    Порядок важен: более специфичные scopes перезаписывают общие.
    Telegram применяет наиболее специфичный подходящий scope.
    """
    # 1. Личные чаты — показываем пользовательские команды
    await bot.set_my_commands(
        commands=USER_COMMANDS,
        scope=BotCommandScopeAllPrivateChats(),
    )
    logger.debug("commands: set USER_COMMANDS for AllPrivateChats")

    # 2. Все группы — скрываем команды (пустой список)
    await bot.set_my_commands(
        commands=_NO_COMMANDS,
        scope=BotCommandScopeAllGroupChats(),
    )
    logger.debug("commands: cleared for AllGroupChats")

    # 3. Администраторы групп — тоже скрываем
    await bot.set_my_commands(
        commands=_NO_COMMANDS,
        scope=BotCommandScopeAllChatAdministrators(),
    )
    logger.debug("commands: cleared for AllChatAdministrators")

    # 4. Персональные команды для каждого админа бота
    for admin_id in settings.ADMIN_IDS:
        await _set_admin_commands(bot, admin_id)


async def _set_admin_commands(bot: Bot, admin_id: int) -> None:
    """Устанавливает персональные команды одному админу."""
    try:
        await bot.set_my_commands(
            commands=ADMIN_COMMANDS,
            scope=BotCommandScopeChat(chat_id=admin_id),
        )
        logger.debug("commands: set ADMIN_COMMANDS for admin_id=%s", admin_id)
    except TelegramBadRequest as e:
        logger.warning(
            "commands: could not set for admin_id=%s — %s "
            "(user may not have started the bot yet)",
            admin_id, e,
        )
    except Exception:
        logger.exception("commands: unexpected error for admin_id=%s", admin_id)


# ── Удаление ──────────────────────────────────────────────────

async def delete_default_commands(bot: Bot) -> None:
    """
    Сбрасывает все установленные команды при остановке бота.
    """
    for scope in (
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    ):
        try:
            await bot.delete_my_commands(scope=scope)
        except Exception:
            logger.exception("commands: error deleting scope=%s", scope)

    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.delete_my_commands(
                scope=BotCommandScopeChat(chat_id=admin_id)
            )
        except TelegramBadRequest:
            pass
        except Exception:
            logger.exception("commands: error deleting for admin_id=%s", admin_id)


# ── Обратная совместимость ────────────────────────────────────
set_commands = set_default_commands
delete_commands = delete_default_commands
