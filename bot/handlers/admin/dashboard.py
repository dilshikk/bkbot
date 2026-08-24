#Файл: /www/wwwroot/bkbot/bot/handlers/admin/dashboard.py
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.admin import IsAdmin
from bot.keyboards.admin import admin_main_keyboard
from bot.repositories.link_repo import LinkRepository
from bot.repositories.user_repo import UserRepository
from bot.services.settings_service import get_settings

router = Router(name="admin.dashboard")


@router.message(Command("admin"), IsAdmin())
async def cmd_admin(message: Message) -> None:
    await message.answer(
        "🔑 <b>Админ-панель</b>",
        reply_markup=admin_main_keyboard(),
        parse_mode="HTML",
    )


@router.message(F.text == "📊 Dashboard", IsAdmin())
async def dashboard(message: Message, session: AsyncSession) -> None:
    user_repo = UserRepository(session)
    link_repo = LinkRepository(session)
    settings  = await get_settings(session)
    links     = await link_repo.get_all()

    active_link = next((l for l in links if l.is_active), None)
    total_links = len(links)
    healthy     = sum(1 for l in links if l.is_healthy)

    total_users = await user_repo.count_total()
    today_users = await user_repo.count_today()

    app_btn    = "🟢 Видна пользователям" if settings.app_enabled else "⚪️ Скрыта"
    app_file   = "✅ Загружен" if settings.app_file_id else "❌ Не загружен"

    text = (
        f"📊 <b>Dashboard</b>\n"
        f"{'━' * 25}\n\n"
        f"👥 <b>Пользователи</b>\n"
        f"   Всего: <b>{total_users:,}</b>\n"
        f"   Сегодня: <b>{today_users:,}</b>\n\n"
        f"🔗 <b>Зеркала</b>\n"
        f"   Всего: <b>{total_links}</b> | Здоровых: <b>{healthy}</b>\n"
        f"   Активное: <b>{active_link.title if active_link else '—'}</b>\n\n"
        f"📱 <b>Приложение</b>\n"
        f"   Кнопка: {app_btn}\n"
        f"   APK-файл: {app_file}\n\n"
        f"⚙️ <b>Настройки</b>\n"
        f"   Бот: {'✅ Работает' if settings.bot_enabled else '🔴 Выключен'}\n"
        f"   Техработы: {'🔧 Да' if settings.maintenance else '✅ Нет'}\n"
        f"   Версия: <code>{settings.version}</code>"
    )
    await message.answer(text, parse_mode="HTML")
