"""
Все периодические задачи бота.

Запускаются через APScheduler при старте в main.py.
Каждая задача — независимая, имеет свою сессию БД.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiohttp
from aiogram import Bot
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.core.config import settings
from bot.core.background_tasks import create_background_task
from bot.core.redis_client import get_redis
from bot.database.models import (
    ActionLog, ActionType, Broadcast, BroadcastStatus, Link, User, UserStatus,
)

logger = logging.getLogger(__name__)

# Таймаут HTTP-пинга зеркала
_PING_TIMEOUT = aiohttp.ClientTimeout(total=8, connect=4)

# 2xx/3xx — сайт работает. 403 оставлен рабочим: защита Cloudflare часто
# отвечает так ботам при живом сайте. Если ваши заблокированные зеркала
# отвечают именно 403 — уберите его из набора.
_EXTRA_OK_CODES = frozenset({403})
# Зеркало считается упавшим только после N неудачных проверок подряд
_FAILS_BEFORE_DOWN = 2
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _utcnow() -> datetime:
    """Текущее UTC время без tzinfo (naive) для совместимости с БД."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ────────────────────────────────────────────────────────
# Task 1 — Автопереключение по расписанию
# ────────────────────────────────────────────────────────

async def switch_scheduled_links(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> None:
    """
    Запускается каждые 5 минут.

    1. Активируем ссылки, у которых наступило active_from и расписание
       ещё не применялось (schedule_applied=False).
    2. Деактивируем ссылки, у которых истекло active_to.
    3. Уведомляем админов — только после успешного commit.

    FIX: раньше выборка шла по is_active=False — после включения лучшей ссылки
    на следующем запуске включалась следующая, и зеркала крутились по кругу.
    """
    notifications: list[str] = []

    async with session_factory() as session:
        try:
            now = _utcnow()

            to_activate = list((await session.scalars(
                select(Link).where(
                    Link.active_from <= now,
                    Link.schedule_applied == False,
                    Link.is_deleted == False,
                    (Link.active_to > now) | (Link.active_to.is_(None)),
                )
            )).all())

            to_deactivate = list((await session.scalars(
                select(Link).where(
                    Link.active_to <= now,
                    Link.is_active == True,
                    Link.is_deleted == False,
                )
            )).all())

            if not to_activate and not to_deactivate:
                return

            for link in to_deactivate:
                link.is_active = False
                logger.info("scheduler: deactivated link_id=%s '%s' (expired)", link.id, link.title)

            if to_activate:
                best = max(to_activate, key=lambda l: l.priority)
                await session.execute(
                    update(Link)
                    .where(Link.is_deleted == False, Link.id != best.id)
                    .values(is_active=False)
                )
                best.is_active = True
                # Помечаем ВСЕ кандидаты, иначе через 5 минут включится следующий
                for link in to_activate:
                    link.schedule_applied = True
                logger.info("scheduler: activated link_id=%s '%s'", best.id, best.title)

                notifications.append(
                    f"🔄 <b>Автопереключение зеркала</b>\n\n"
                    f"Активировано: <b>{best.title}</b>\n"
                    f"URL: <code>{best.url}</code>"
                )

            if to_deactivate:
                titles = ", ".join(l.title for l in to_deactivate)
                notifications.append(f"⏳ <b>Срок зеркал истёк</b>\n\nДеактивированы: {titles}")

            await session.commit()

        except Exception:
            logger.exception("scheduler: switch_scheduled_links failed")
            await session.rollback()
            return

    for text in notifications:
        await _notify_admins(bot, text)


# ────────────────────────────────────────────────────────
# Task 2 — Health Check
# ────────────────────────────────────────────────────────

async def health_check_links(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> None:
    """
    Запускается каждые 10 минут.

    Пингует каждое не удалённое зеркало.
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
            for link, raw_ok in results:
                is_healthy = await _with_fail_threshold(link, raw_ok)
                if link.is_healthy != is_healthy:
                    changed.append((link, is_healthy))
                    link.is_healthy = is_healthy

            if changed:
                await session.commit()
                await _notify_health_changes(bot, changed)
            else:
                await session.rollback()

        except Exception:
            logger.exception("scheduler: health_check_links failed")
            await session.rollback()


async def _ping_all(links: list[Link]) -> list[tuple[Link, bool]]:
    """Пингуем все ссылки параллельно."""
    async with aiohttp.ClientSession(timeout=_PING_TIMEOUT) as http:
        tasks = [_ping_one(http, link) for link in links]
        return await asyncio.gather(*tasks)


def _status_ok(code: int) -> bool:
    return 200 <= code < 400 or code in _EXTRA_OK_CODES


async def _ping_one(http: aiohttp.ClientSession, link: Link) -> tuple[Link, bool]:
    try:
        async with http.get(
            link.url,
            allow_redirects=True,
            headers=_HEADERS,
            # Прокси в нужной стране — проверка «глазами» пользователя
            proxy=settings.HEALTHCHECK_PROXY or None,
        ) as resp:
            healthy = _status_ok(resp.status)
            logger.debug("ping link_id=%s status=%s healthy=%s", link.id, resp.status, healthy)
            return link, healthy
    except Exception as e:
        logger.debug("ping link_id=%s error=%s", link.id, e)
        return link, False


async def _with_fail_threshold(link: Link, ok: bool) -> bool:
    """Зеркало «падает» только после _FAILS_BEFORE_DOWN неудач подряд."""
    redis = await get_redis()
    key = f"health:fails:{link.id}"
    if ok:
        await redis.delete(key)
        return True
    fails = await redis.incr(key)
    await redis.expire(key, 3600)
    # Пока порог не достигнут — оставляем текущее состояние
    return link.is_healthy if fails < _FAILS_BEFORE_DOWN else False


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
# Task 3 — Дейли статистика
# ────────────────────────────────────────────────────────

async def daily_stats(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> None:
    """
    Запускается каждый день в 09:00 UTC.
    Отправляет краткую статистику за вчера всем админам.
    """
    async with session_factory() as session:
        try:
            today     = _utcnow().date()
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
    Запускаем те, у которых наступило scheduled_at.
    """
    from bot.services.broadcast_service import run_broadcast_task
    async with session_factory() as session:
        try:
            now = _utcnow()

            result = await session.execute(
                update(Broadcast)
                .where(
                    Broadcast.status == BroadcastStatus.PENDING,
                    Broadcast.scheduled_at <= now,
                )
                .values(status=BroadcastStatus.RUNNING, started_at=now)
                .returning(Broadcast.id)
            )
            broadcast_ids = list(result.scalars().all())

            if not broadcast_ids:
                await session.rollback()
                return

            # Считаем получателей только если есть что запускать
            total = await session.scalar(
                select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)
            ) or 0
            await session.execute(
                update(Broadcast)
                .where(Broadcast.id.in_(broadcast_ids))
                .values(total=total)
            )
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
