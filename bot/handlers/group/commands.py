"""
Команды в группах:
  /link — активное зеркало
  /app  — APK-файл приложения

Сюда доходят только команды, пропущенные GroupCommandGateMiddleware
(включено, чат разрешён, адресовано этому боту, нет кулдауна).
Бот отвечает реплаем на команду, в той же теме форума.

Чтобы не засорять чат, команда участника и ответ бота учитываются
(bot/services/group_replies.py): новый вызов удаляет прошлый вызов той же
команды, а сам удаляется по таймеру.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, Message, ReplyParameters
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ActionType, User
from bot.repositories.log_repo import LogRepository
from bot.services.delivery import (
    app_caption,
    available_app_file_id,
    increment_app_downloads,
    mirror_keyboard,
    mirror_text,
)
from bot.services.group_replies import track_reply
from bot.services.link_service import LinkService
from bot.services.settings_service import get_settings
from bot.utils.group_commands import GROUP_CHAT_TYPES

router = Router(name="group.commands")
router.message.filter(F.chat.type.in_(GROUP_CHAT_TYPES))

logger = logging.getLogger(__name__)

_NO_LINK_TEXT = (
    "⏳ <b>Зеркало временно обновляется.</b>\n\n"
    "Попробуйте через несколько минут."
)
_NO_APP_TEXT = "⏳ Приложение пока недоступно. Попробуйте позже."


# ── /link ─────────────────────────────────────────────────────

@router.message(Command("link"))
async def group_link(
    message: Message,
    session: AsyncSession,
    db_user: User | None = None,
) -> None:
    link_service = LinkService(session)
    log_repo = LogRepository(session)
    link = await link_service.get_active()

    if link is None:
        await _send(message, "link", text=_NO_LINK_TEXT)
        await log_repo.log(
            ActionType.GET_MIRROR,
            **_identity(message, db_user),
            meta=_meta(message, result="no_active_link"),
        )
        return

    me = await message.bot.me()
    bot_tag = f"@{me.username}"

    # Без кнопки «Обновить»: в группе её мог бы нажать любой участник
    sent = await _send(
        message,
        "link",
        text=mirror_text(link.url, bot_tag),
        reply_markup=mirror_keyboard(link.url, bot_tag, with_refresh=False),
        photo_id=link.photo_file_id,
    )
    if not sent:
        return

    await link_service.increment_click(link.id)
    await log_repo.log(
        ActionType.GET_MIRROR,
        **_identity(message, db_user),
        meta=_meta(message, link_id=link.id, url=link.url),
    )


# ── /app ──────────────────────────────────────────────────────

@router.message(Command("app"))
async def group_app(
    message: Message,
    session: AsyncSession,
    db_user: User | None = None,
) -> None:
    bot_settings = await get_settings(session)
    file_id = available_app_file_id(bot_settings)

    if file_id is None:
        await _send(message, "app", text=_NO_APP_TEXT)
        return

    sent = await _send(message, "app", text=app_caption(bot_settings), document_id=file_id)
    if not sent:
        return

    await increment_app_downloads(session)
    await LogRepository(session).log(
        ActionType.GET_APP,
        **_identity(message, db_user),
        meta=_meta(message),
    )


# ── Отправка ──────────────────────────────────────────────────

async def _send(
    message: Message,
    command: str,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    photo_id: str | None = None,
    document_id: str | None = None,
) -> bool:
    """
    Отвечает на команду и ставит команду и ответ на учёт для чистки.
    Ошибки Telegram (нет прав писать или слать файлы, флуд-лимит,
    битый file_id) логируются и не роняют обработку апдейта.
    """
    # Если команду успели удалить — сообщение всё равно уйдёт, без реплая
    reply = ReplyParameters(
        message_id=message.message_id,
        allow_sending_without_reply=True,
    )
    try:
        if document_id:
            sent = await message.answer_document(
                document=document_id,
                caption=text,
                parse_mode="HTML",
                reply_parameters=reply,
            )
        elif photo_id:
            sent = await message.answer_photo(
                photo=photo_id,
                caption=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                reply_parameters=reply,
            )
        else:
            sent = await message.answer(
                text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                reply_parameters=reply,
            )
    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter) as exc:
        logger.warning(
            "group command: cannot send to chat=%s: %s", message.chat.id, exc,
        )
        # Ответа нет, но саму команду всё равно убираем по таймеру
        await track_reply(message.bot, message.chat.id, command, [message.message_id])
        return False

    await track_reply(
        message.bot,
        message.chat.id,
        command,
        [message.message_id, sent.message_id],
    )
    return True


def _identity(message: Message, db_user: User | None) -> dict[str, Any]:
    return {
        "user_id": db_user.id if db_user else None,
        "telegram_id": message.from_user.id if message.from_user else None,
    }


def _meta(message: Message, **extra: Any) -> dict[str, Any]:
    return {"source": "group", "chat_id": message.chat.id, **extra}
