# bot/handlers/admin/settings.py
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.admin import IsAdmin
from bot.keyboards.admin import admin_main_keyboard, cancel_keyboard
from bot.database.models import Settings
from bot.services.settings_service import get_settings, SettingsData

router = Router(name="admin.settings")


class SettingsFlow(StatesGroup):
    edit_welcome          = State()
    edit_after_sub        = State()
    edit_maintenance_text = State()
    edit_support          = State()


def settings_keyboard(s: SettingsData) -> InlineKeyboardMarkup:
    app_toggle_text = "🔴 Скрыть кнопку приложения" if s.app_enabled else "🟢 Показать кнопку приложения"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔧 Выключить техработы" if s.maintenance else "🔧 Включить техработы",
            callback_data="settings_toggle_maintenance",
        )],
        [InlineKeyboardButton(
            text=app_toggle_text,
            callback_data="settings_toggle_app",
        )],
        [InlineKeyboardButton(text="✏️ Текст приветствия",    callback_data="settings_edit_welcome")],
        [InlineKeyboardButton(text="✏️ Текст после подписки", callback_data="settings_edit_after_sub")],
        [InlineKeyboardButton(text="✏️ Текст техработ",        callback_data="settings_edit_maintenance_text")],
        [InlineKeyboardButton(text="🆘 Ссылка поддержки",      callback_data="settings_edit_support")],
    ])


# ── Показать настройки ────────────────────────────────────────

@router.message(F.text == "⚙️ Настройки", IsAdmin())
async def show_settings(message: Message, session: AsyncSession) -> None:
    s = await get_settings(session)
    app_btn = "🟢 Видна пользователям" if s.app_enabled else "⚪️ Скрыта"
    text = (
        f"⚙️ <b>Настройки</b>\n\n"
        f"Бот: {'✅ Работает' if s.bot_enabled else '🔴 Выключен'}\n"
        f"Техработы: {'🔧 Да' if s.maintenance else '✅ Нет'}\n"
        f"Кнопка приложения: {app_btn}\n"
        f"Поддержка: {s.support_link or '—'}\n\n"
        f"<b>Приветствие:</b>\n{s.welcome_text}\n\n"
        f"<b>После подписки:</b>\n{s.after_sub_text}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=settings_keyboard(s))


# ── Техработы ─────────────────────────────────────────────────

@router.callback_query(F.data == "settings_toggle_maintenance", IsAdmin())
async def toggle_maintenance(call: CallbackQuery, session: AsyncSession) -> None:
    s             = await _get_or_create(session)
    s.maintenance = not s.maintenance
    s.updated_by  = call.from_user.id
    await session.flush()
    updated = await get_settings(session)
    await call.message.edit_reply_markup(reply_markup=settings_keyboard(updated))
    await call.answer("🔧 Включены" if s.maintenance else "✅ Выключены")


# ── Кнопка приложения ─────────────────────────────────────────

@router.callback_query(F.data == "settings_toggle_app", IsAdmin())
async def toggle_app(call: CallbackQuery, session: AsyncSession) -> None:
    s             = await _get_or_create(session)
    s.app_enabled = not s.app_enabled
    s.updated_by  = call.from_user.id
    await session.flush()
    updated = await get_settings(session)
    await call.message.edit_reply_markup(reply_markup=settings_keyboard(updated))
    status = "🟢 Кнопка показана пользователям" if s.app_enabled else "⚪️ Кнопка скрыта"
    await call.answer(status)


# ── Текст приветствия ─────────────────────────────────────────

@router.callback_query(F.data == "settings_edit_welcome", IsAdmin())
async def edit_welcome_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer(
        "✏️ Введите новый текст приветствия.\n"
        "Используйте <code>{name}</code> для имени пользователя.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(SettingsFlow.edit_welcome)
    await call.answer()


@router.message(SettingsFlow.edit_welcome, IsAdmin())
async def edit_welcome_done(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    s              = await _get_or_create(session)
    s.welcome_text = message.text or s.welcome_text
    s.updated_by   = message.from_user.id
    await state.clear()
    await message.answer("✅ Текст приветствия обновлён.", reply_markup=admin_main_keyboard())


# ── Текст после подписки ──────────────────────────────────────

@router.callback_query(F.data == "settings_edit_after_sub", IsAdmin())
async def edit_after_sub_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer(
        "✏️ Введите новый текст после подписки:",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(SettingsFlow.edit_after_sub)
    await call.answer()


@router.message(SettingsFlow.edit_after_sub, IsAdmin())
async def edit_after_sub_done(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    s                = await _get_or_create(session)
    s.after_sub_text = message.text or s.after_sub_text
    s.updated_by     = message.from_user.id
    await state.clear()
    await message.answer("✅ Текст после подписки обновлён.", reply_markup=admin_main_keyboard())


# ── Текст техработ ────────────────────────────────────────────

@router.callback_query(F.data == "settings_edit_maintenance_text", IsAdmin())
async def edit_maintenance_text_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer(
        "✏️ Введите текст технических работ:",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(SettingsFlow.edit_maintenance_text)
    await call.answer()


@router.message(SettingsFlow.edit_maintenance_text, IsAdmin())
async def edit_maintenance_text_done(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    s                   = await _get_or_create(session)
    s.maintenance_text  = message.text or s.maintenance_text
    s.updated_by        = message.from_user.id
    await state.clear()
    await message.answer("✅ Текст техработ обновлён.", reply_markup=admin_main_keyboard())


# ── Ссылка поддержки ──────────────────────────────────────────

@router.callback_query(F.data == "settings_edit_support", IsAdmin())
async def edit_support_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer(
        "🆘 Введите ссылку на поддержку (https://t.me/...):",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(SettingsFlow.edit_support)
    await call.answer()


@router.message(SettingsFlow.edit_support, IsAdmin())
async def edit_support_done(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    url = (message.text or "").strip()
    if not url.startswith("http"):
        await message.answer(
            "❌ Некорректная ссылка. Должна начинаться с https://",
            reply_markup=cancel_keyboard,
        )
        return
    s              = await _get_or_create(session)
    s.support_link = url
    s.updated_by   = message.from_user.id
    await state.clear()
    await message.answer("✅ Ссылка поддержки обновлена.", reply_markup=admin_main_keyboard())


# ── Helper ────────────────────────────────────────────────────

async def _get_or_create(session: AsyncSession) -> Settings:
    result = await session.execute(select(Settings).limit(1))
    s      = result.scalar_one_or_none()
    if s is None:
        s = Settings()
        session.add(s)
        await session.flush()
    return s
