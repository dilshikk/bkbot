from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.user import main_menu_keyboard
from bot.services.settings_service import get_settings

router = Router(name="user.menu")

# FIX: вынесено в константу — легко расширять без правки условия
MENU_TRIGGERS: frozenset[str] = frozenset({
    "🏠 Главное меню",
    "◀️ Назад",
})


# ── Главное меню ──────────────────────────────────────────────

@router.message(F.text.in_(MENU_TRIGGERS))
async def show_main_menu(message: Message) -> None:
    # FIX: убран неиспользуемый параметр db_user (не нужен здесь)
    # FIX: убран лишний f"..." — не содержал интерполяции
    await message.answer(
        "Выберите действие:",
        reply_markup=main_menu_keyboard(),
    )


# ── Помощь ────────────────────────────────────────────────────

@router.message(Command("help"))
@router.message(F.text == "📖 Как пользоваться")
async def how_to_use(message: Message) -> None:
    text = (
        "📖 <b>Как пользоваться</b>\n\n"
        "1️⃣ Нажмите <b>«🎯 Получить зеркало»</b>\n"
        "2️⃣ Перейдите по полученной ссылке\n"
        "3️⃣ Если ссылка не работает — нажмите снова\n\n"
        "Зеркала обновляются автоматически.\n"
        "Бот всегда покажет актуальную ссылку."
    )
    await message.answer(text, parse_mode="HTML")


# ── О сервисе ─────────────────────────────────────────────────

@router.message(F.text == "ℹ️ О сервисе")
async def about(message: Message, session: AsyncSession) -> None:
    settings = await get_settings(session)
    text = (
        "ℹ️ <b>О сервисе</b>\n\n"
        f"Версия: <code>{settings.version}</code>\n\n"
        "Бот автоматически выдаёт актуальные рабочие зеркала.\n"
        "Зеркала проверяются и обновляются регулярно."
    )
    await message.answer(text, parse_mode="HTML")


# ── Поддержка ─────────────────────────────────────────────────

@router.message(F.text == "🆘 Поддержка")
async def support(message: Message, session: AsyncSession) -> None:
    settings = await get_settings(session)

    # FIX: импорт InlineKeyboardMarkup/Button перенесён на верхний уровень —
    # lazy import внутри функции скрывает зависимость и замедляет первый вызов
    if settings.support_link:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="💬 Написать в поддержку",
                url=settings.support_link,
            ),
        ]])
        await message.answer("🆘 Свяжитесь с поддержкой:", reply_markup=kb)
    else:
        await message.answer("🆘 Поддержка временно недоступна.")