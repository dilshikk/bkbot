"""
Все периодические задачи бота.

Запускаются через APScheduler при старте в main.py.
Каждая задача — независимая, имеет свою сессию БД.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import aiohttp
from aiogram import Bot
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.core.config import settings
from bot.core.background_tasks import create_background_task
from bot.database.models import Link, Broadcast, BroadcastStatus, User, UserStatus

logger = logging.getLogger(__name__)

# Таймаут HTTP-пинга зеркала
_PING_TIMEOUT = aiohttp.ClientTimeout(total=8, connect=4)

# Коды которые считаем "живыми"
_HEALTHY_CODES = frozenset(range(200, 500))  # всё кроме 5xx и сетевых ошибок


# ────────────────────────────────────────────────────────
# Task 1 — Автопереключение по расписанию
# ────────────────────────────────────────────────────────

async def switch_scheduled_links(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> None:
    """
    Запускается каждые 5 минут.

    Логика:
    1. Активируем ссылки у которых наступило active_from
    2. Деактивируем ссылки у которых истекло active_to
    3. Уведомляем админов если что-то переключилось
    """
    async with session_factory() as session:
        try:
            now = datetime.utcnow()

            # Ссылки которые надо активировать
            to_activate_result = await session.execute(
                select(Link).where(
                    Link.active_from <= now,
                    Link.is_active == False,
                    Link.is_deleted == False,
                    # active_to ещё не наступило (или не задано)
                    (Link.active_to > now) | (Link.active_to.is_(None)),
                )
            )
            to_activate = list(to_activate_result.scalars().all())

            # Ссылки у которых истёк срок
            to_deactivate_result = await session.execute(
                select(Link).where(
                    Link.active_to <= now,
                    Link.is_active == True,
                    Link.is_deleted == False,
                )
            )
            to_deactivate = list(to_deactivate_result.scalars().all())

            if not to_activate and not to_deactivate:
                return

            # Сначала деактивируем истёкшие
            for link in to_deactivate:
                link.is_active = False
                logger.info("scheduler: deactivated link_id=%s '%s' (expired)", link.id, link.title)

            # Активируем запланированные — деактивируем все остальные
            if to_activate:
                await session.execute(
                    update(Link)
                    .where(Link.is_deleted == False)
                    .values(is_active=False)
                )
                # Активируем с наибольшим приоритетом из запланированных
                best = max(to_activate, key=lambda l: l.priority)
                best.is_active = True
                logger.info("scheduler: activated link_id=%s '%s'", best.id, best.title)

                await _notify_admins(
                    bot,
                    f"🔄 <b>Автопереключение зеркала</b>\n\n"
                    f"Активировано: <b>{best.title}</b>\n"
                    f"URL: <code>{best.url}</code>",
                )

            if to_deactivate:
                titles = ", ".join(l.title for l in to_deactivate)
                await _notify_admins(
                    bot,
                    f"⏳ <b>Срок зеркал истёк</b>\n\nДеактивированы: {titles}",
                )

            await session.commit()

        except Exception:
            logger.exception("scheduler: switch_scheduled_links failed")
            await session.rollback()


# ────────────────────────────────────────────────────────
# Task 2 — Health Check
# ────────────────────────────────────────────────────────

async def health_check_links(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> None:
    """
    Запускается каждые 10 минут.

    Пиингует каждое не удалённое зеркало.
    Если статус is_healthy изменился — обновляет БД и уведомляет админов.
    """
    async with session_factory() as session:
        try:
            result = await session.execute(
                select(Link).where(Link.is_deleted == False)
            )
            links = list(result.scalars().all())

            if not links:
                return

            results = await _ping_all(links)

            changed: list[tuple[Link, bool]] = []
            for link, is_healthy in results:
                if link.is_healthy != is_healthy:
                    changed.append((link, is_healthy))
                    link.is_healthy = is_healthy

            if changed:
                await session.commit()
                await _notify_health_changes(bot, changed)
            else:
                # Нет изменений — роллбэчим пустую транзакцию
                await session.rollback()

        except Exception:
            logger.exception("scheduler: health_check_links failed")
            await session.rollback()


async def _ping_all(links: list[Link]) -> list[tuple[Link, bool]]:
    """Пиингуем все ссылки параллельно."""
    async with aiohttp.ClientSession(timeout=_PING_TIMEOUT) as http:
        tasks = [_ping_one(http, link) for link in links]
        return await asyncio.gather(*tasks)


async def _ping_one(http: aiohttp.ClientSession, link: Link) -> tuple[Link, bool]:
    try:
        async with http.get(link.url, allow_redirects=True) as resp:
            healthy = resp.status in _HEALTHY_CODES
            logger.debug("ping link_id=%s status=%s healthy=%s", link.id, resp.status, healthy)
            return link, healthy
    except Exception as e:
        logger.debug("ping link_id=%s error=%s", link.id, e)
        return link, False


async def _notify_health_changes(
    bot: Bot,
    changed: list[tuple[Link, bool]],
) -> None:
    went_down = [l for l, h in changed if not h]
    came_up   = [l for l, h in changed if h]

    parts: list[str] = []

    if went_down:
        titles = "\n".join(f"  • {l.title} — <code>{l.url}</code>" for l in went_down)
        parts.append(f"❌ <b>Зеркала упали:</b>\n{titles}")

    if came_up:
        titles = "\n".join(f"  • {l.title} — <code>{l.url}</code>" for l in came_up)
        parts.append(f"✅ <b>Зеркала восстановились:</b>\n{titles}")

    if parts:
        await _notify_admins(bot, "\n\n".join(parts))


# ────────────────────────────────────────────────────────
# Task 3 — Дейли статистика (опционально)
# ────────────────────────────────────────────────────────

async def daily_stats(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> None:
    """
    Запускается каждый день в 09:00 UTC.
    Отправляет краткую статистику за вчера всем админам.
    """
    from sqlalchemy import func
    from bot.database.models import User, ActionLog, ActionType
    from datetime import timedelta

    async with session_factory() as session:
        try:
            today     = datetime.utcnow().date()
            yesterday = today - timedelta(days=1)

            new_users = await session.scalar(
                select(func.count(User.id)).where(
                    func.date(User.registered_at) == yesterday
                )
            ) or 0

            mirror_requests = await session.scalar(
                select(func.count(ActionLog.id)).where(
                    ActionLog.action == ActionType.GET_MIRROR,
                    func.date(ActionLog.created_at) == yesterday,
                )
            ) or 0

            await _notify_admins(
                bot,
                f"📊 <b>Статистика за {yesterday:%d.%m.%Y}</b>\n\n"
                f"👥 Новых пользователей: <b>{new_users}</b>\n"
                f"🎯 Запросов зеркала: <b>{mirror_requests}</b>",
            )
        except Exception:
            logger.exception("scheduler: daily_stats failed")

# ────────────────────────────────────────────────────────
# Task 4 — запуск отложенных рассылок
# ────────────────────────────────────────────────────────

async def run_pending_broadcasts(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> None:
    """
    Каждую минуту проверяем запланированные рассылки.
    Запускаем те у которых наступило scheduled_at.
    """
    from bot.services.broadcast_service import run_broadcast_task
    async with session_factory() as session:
        try:
            now = datetime.utcnow()
            total = await session.scalar(
                select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)
            ) or 0

            result = await session.execute(
                update(Broadcast)
                .where(
                    Broadcast.status == BroadcastStatus.PENDING,
                    Broadcast.scheduled_at <= now,
                )
                .values(
                    status=BroadcastStatus.RUNNING,
                    started_at=now,
                    total=total,
                )
                .returning(Broadcast.id)
            )
            broadcast_ids = list(result.scalars().all())

            await session.commit()

            for broadcast_id in broadcast_ids:
                create_background_task(
                    run_broadcast_task(session_factory, bot, broadcast_id),
                    name=f"broadcast:{broadcast_id}",
                )
                logger.info("pending broadcast_id=%s launched", broadcast_id)

        except Exception:
            logger.exception("run_pending_broadcasts failed")
            await session.rollback()

# ────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────

async def _notify_admins(bot: Bot, text: str) -> None:
    """Рассылает уведомление всем ADMIN_IDS. Ошибки не бросает."""
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as e:
            logger.warning("cannot notify admin=%s: %s", admin_id, e)