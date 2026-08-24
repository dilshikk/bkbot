# bot/handlers/admin/app.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Document,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Settings, ActionType
from bot.filters.admin import IsAdmin
from bot.keyboards.admin import admin_main_keyboard, cancel_keyboard
from bot.repositories.log_repo import LogRepository
from bot.services.settings_service import get_settings

router = Router(name="admin.app")


# ── FSM ───────────────────────────────────────────────────────

class AppFlow(StatesGroup):
    upload_apk  = State()
    edit_caption = State()


# ── Клавиатура раздела ────────────────────────────────────────

def app_keyboard(s: Settings) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Скрыть кнопку у пользователей" if s.app_enabled else "🟢 Показать кнопку пользователям"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="app_toggle_enabled")],
        [InlineKeyboardButton(text="📤 Загрузить APK",    callback_data="app_upload_apk")],
        [InlineKeyboardButton(text="✏️ Изменить описание", callback_data="app_edit_caption")],
    ])


# ── Показать раздел ───────────────────────────────────────────

@router.message(F.text == "📱 Приложение", IsAdmin())
async def show_app_section(message: Message, session: AsyncSession) -> None:
    s = await get_settings(session)
    await message.answer(_build_status_text(s), parse_mode="HTML", reply_markup=app_keyboard(s))


def _build_status_text(s: Settings) -> str:
    status   = "🟢 Кнопка видна пользователям" if s.app_enabled else "⚪️ Кнопка скрыта"
    has_file = "✅ Загружен" if s.app_file_id else "❌ Не загружен"
    caption  = s.app_caption or "—"
    return (
        f"📱 <b>Управление приложением</b>\n\n"
        f"Статус: {status}\n"
        f"APK-файл: {has_file}\n\n"
        f"<b>Описание:</b>\n{caption}"
    )


# ── Вкл / Выкл кнопки у пользователей ────────────────────────

@router.callback_query(F.data == "app_toggle_enabled", IsAdmin())
async def app_toggle_enabled(call: CallbackQuery, session: AsyncSession) -> None:
    if call.message is None:
        await call.answer()
        return

    s = await _get_or_create(session)
    s.app_enabled = not s.app_enabled
    s.updated_by  = call.from_user.id
    await session.flush()

    await LogRepository(session).log(
        ActionType.ADMIN_ACTION,
        telegram_id=call.from_user.id,
        meta={"action": "app_toggle_enabled", "app_enabled": s.app_enabled},
    )

    await call.message.edit_text(_build_status_text(s), parse_mode="HTML", reply_markup=app_keyboard(s))
    status_text = "🟢 Кнопка показана пользователям" if s.app_enabled else "⚪️ Кнопка скрыта"
    await call.answer(status_text)


# ── Загрузить APK ─────────────────────────────────────────────

@router.callback_query(F.data == "app_upload_apk", IsAdmin())
async def app_upload_apk_start(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return

    await state.clear()
    await call.message.answer(
        "📤 Отправьте APK-файл.\n\n"
        "<i>Файл должен быть отправлен как документ (не сжатый).</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(AppFlow.upload_apk)
    await call.answer()


@router.message(AppFlow.upload_apk, F.document, IsAdmin())
async def app_upload_apk_done(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.from_user is None:
        await state.clear()
        return

    doc: Document | None = message.document
    if doc is None:
        await message.answer("❌ Файл не распознан. Отправьте APK как документ.", reply_markup=cancel_keyboard)
        return

    s = await _get_or_create(session)
    s.app_file_id = doc.file_id
    s.updated_by  = message.from_user.id
    await session.flush()

    await LogRepository(session).log(
        ActionType.ADMIN_ACTION,
        telegram_id=message.from_user.id,
        meta={"action": "app_apk_uploaded", "file_id": doc.file_id, "file_name": doc.file_name},
    )
    await state.clear()
    await message.answer(
        f"✅ APK сохранён.\nФайл: <code>{doc.file_name or doc.file_id}</code>",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


@router.message(AppFlow.upload_apk, IsAdmin())
async def app_upload_apk_wrong(message: Message) -> None:
    """Пользователь отправил не документ."""
    await message.answer(
        "❌ Нужен файл-документ (APK). Отправьте файл, а не фото или текст.",
        reply_markup=cancel_keyboard,
    )


# ── Изменить описание ─────────────────────────────────────────

@router.callback_query(F.data == "app_edit_caption", IsAdmin())
async def app_edit_caption_start(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return

    await state.clear()
    await call.message.answer(
        "✏️ Введите описание, которое бот отправит пользователю вместе с APK-файлом.\n\n"
        "Поддерживается HTML: <b>жирный</b>, <i>курсив</i>, <code>код</code>.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(AppFlow.edit_caption)
    await call.answer()


@router.message(AppFlow.edit_caption, IsAdmin())
async def app_edit_caption_done(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.from_user is None:
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Описание не может быть пустым.", reply_markup=cancel_keyboard)
        return

    s = await _get_or_create(session)
    s.app_caption = text
    s.updated_by  = message.from_user.id
    await session.flush()

    await LogRepository(session).log(
        ActionType.ADMIN_ACTION,
        telegram_id=message.from_user.id,
        meta={"action": "app_caption_updated"},
    )
    await state.clear()
    await message.answer("✅ Описание обновлено.", reply_markup=admin_main_keyboard())


# ── Helper ────────────────────────────────────────────────────

async def _get_or_create(session: AsyncSession) -> Settings:
    result = await session.execute(select(Settings).limit(1))
    s = result.scalar_one_or_none()
    if s is None:
        s = Settings()
        session.add(s)
        await session.flush()
    return s
