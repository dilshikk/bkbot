from __future__ import annotations

import html
from urllib.parse import quote

from aiogram import Router, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    InputMediaPhoto,
    InaccessibleMessage,
)
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, ActionType
from bot.repositories.log_repo import LogRepository
from bot.services.link_service import LinkService

router = Router(name="user.mirror")

_MSG_NOT_MODIFIED = "message is not modified"


# ── Публичные хендлеры ────────────────────────────────────────

@router.message(F.text == "🎯 Получить зеркало")
async def get_mirror(message: Message, session: AsyncSession, db_user: User) -> None:
    await _send_mirror(message, session, db_user, edit=False)


@router.callback_query(F.data == "refresh_mirror")
async def refresh_mirror(
    call: CallbackQuery,
    session: AsyncSession,
    db_user: User,
) -> None:
    if call.message is None or isinstance(call.message, InaccessibleMessage):
        await call.answer("❌ Не удалось обновить сообщение", show_alert=True)
        return

    await call.answer("🔄 Обновляю...")
    await _send_mirror(call.message, session, db_user, edit=True)


# ── Внутренняя логика ─────────────────────────────────────────

async def _send_mirror(
    message: Message,
    session: AsyncSession,
    db_user: User,
    edit: bool = False,
) -> None:
    link_service = LinkService(session)
    log_repo = LogRepository(session)
    link = await link_service.get_active()

    if link is None:
        await _handle_no_link(message, edit)
        await log_repo.log(
            ActionType.GET_MIRROR,
            user_id=db_user.id,
            telegram_id=db_user.telegram_id,
            meta={"result": "no_active_link"},
        )
        return

    # Имя бота берём из Telegram (aiogram кэширует ответ) — не хардкодим
    me = await message.bot.me()
    bot_tag = f"@{me.username}"

    # FIX: экранируем URL — кавычка или < в адресе ломали HTML сообщения
    text = (
        "🎯 <b>Актуальное рабочее зеркало</b>\n\n"
        f'👉 <a href="{html.escape(link.url, quote=True)}">Перейти на сайт</a>\n\n'
        f"🤖 <b>Отправлено ботом:</b> {bot_tag}"
    )
    kb = _build_keyboard(link.url, bot_tag)

    photo_id: str | None = getattr(link, "photo_file_id", None)

    await _dispatch_message(message, text, kb, photo_id, edit)

    await link_service.increment_click(link.id)

    await log_repo.log(
        ActionType.GET_MIRROR,
        user_id=db_user.id,
        telegram_id=db_user.telegram_id,
        meta={"link_id": link.id, "url": link.url},
    )


async def _handle_no_link(message: Message, edit: bool) -> None:
    text = (
        "⏳ <b>Зеркало временно обновляется.</b>\n\n"
        "Попробуйте через несколько минут."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="refresh_mirror"),
    ]])

    if edit:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except TelegramBadRequest as exc:
            if _MSG_NOT_MODIFIED not in str(exc):
                raise
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


async def _dispatch_message(
    message: Message,
    text: str,
    kb: InlineKeyboardMarkup,
    photo_id: str | None,
    edit: bool,
) -> None:
    if photo_id:
        await _dispatch_photo(message, text, kb, photo_id, edit)
    else:
        await _dispatch_text(message, text, kb, edit)


async def _dispatch_photo(
    message: Message,
    text: str,
    kb: InlineKeyboardMarkup,
    photo_id: str,
    edit: bool,
) -> None:
    if not edit:
        await message.answer_photo(
            photo=photo_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    try:
        await message.edit_media(
            media=InputMediaPhoto(media=photo_id, caption=text, parse_mode="HTML"),
            reply_markup=kb,
        )
    except TelegramBadRequest as exc:
        if _MSG_NOT_MODIFIED in str(exc):
            return
        await _delete_safe(message)
        await message.answer_photo(
            photo=photo_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=kb,
        )


async def _dispatch_text(
    message: Message,
    text: str,
    kb: InlineKeyboardMarkup,
    edit: bool,
) -> None:
    if not edit:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
        return

    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest as exc:
        if _MSG_NOT_MODIFIED in str(exc):
            return
        await _delete_safe(message)
        await message.answer(text, parse_mode="HTML", reply_markup=kb)


async def _delete_safe(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


def _build_keyboard(url: str, bot_tag: str) -> InlineKeyboardMarkup:
    share_url = (
        "https://t.me/share/url"
        f"?url={quote(url)}"
        f"&text={quote(f'🎯 Актуальное рабочее зеркало {bot_tag}')}"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Перейти", url=url)],
        [InlineKeyboardButton(text="📤 Поделиться", url=share_url)],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_mirror")],
    ])
