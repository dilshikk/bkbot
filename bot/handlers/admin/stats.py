#Файл: /www/wwwroot/bkbot/bot/handlers/admin/stats.py
from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.admin import IsAdmin
from bot.services.stats_service import StatsService

router = Router(name="admin.stats")


@router.message(F.text == "📊 Dashboard", IsAdmin())
async def dashboard(message: Message, session: AsyncSession) -> None:
    svc    = StatsService(session)
    report = await svc.full_report()

    u = report["users"]
    m = report["mirrors"]

    # ── Источники трафика
    source_lines = "\n".join(
        f"   {src}: <b>{cnt:,}</b>"
        for src, cnt in report["sources"][:5]
    ) or "   —"

    # ── Топ зеркал
    top_links_lines = "\n".join(
        f"   {'🟢' if l.is_active else '⚪️'} {l.title}: <b>{l.click_count:,}</b>"
        for l in m["top"]
    ) or "   —"

    text = (
        f"📊 <b>Dashboard</b>\n"
        f"{'━' * 26}\n\n"

        f"👥 <b>Пользователи</b>\n"
        f"   Всего: <b>{u['total']:,}</b>\n"
        f"   Сегодня: <b>{u['today']:,}</b>\n"
        f"   За неделю: <b>{u['week']:,}</b>\n"
        f"   За месяц: <b>{u['month']:,}</b>\n"
        f"   Подписаны: <b>{u['subscribed']:,}</b>\n"
        f"   Заблокировано: <b>{u['banned']}</b>\n\n"

        f"🎯 <b>Запросы зеркала</b>\n"
        f"   Сегодня: <b>{m['today']:,}</b>\n"
        f"   За неделю: <b>{m['week']:,}</b>\n"
        f"   За месяц: <b>{m['month']:,}</b>\n\n"

        f"🔗 <b>Топ зеркал</b>\n"
        f"{top_links_lines}\n\n"

        f"📢 <b>Источники трафика</b>\n"
        f"{source_lines}"
    )

    await message.answer(text, parse_mode="HTML")