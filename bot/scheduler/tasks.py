"""
Все периодические задачи бота.

Запускаются через APScheduler при старте в main.py.
Каждая задача — независимая, имеет свою сессию БД.
"""
from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
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
from bot.repositories.link_repo import LinkRepository
from bot.services.admin_notify import notify_admins
from bot.utils.mirrors import (
    needs_switch, pick_replacement, same_site, site_host, status_ok,
)

logger = logging.getLogger(__name__)

# Таймаут HTTP-пинга зеркала
_PING_TIMEOUT = aiohttp.ClientTimeout(total=8, connect=4)

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
    """
    notifications: list[str] = []

    async with session_factory() as session:
        try:
            now = _utcnow()

            to_activate = list((await session.scalars(
                select(Link).where(
                    Link.active_from <= now,
                    Link.schedule_applied == False,  # noqa: E712
                    Link.is_deleted == False,  # noqa: E712
                    (Link.active_to > now) | (Link.active_to.is_(None)),
                )
            )).all())

            to_deactivate = list((await session.scalars(
                select(Link).where(
                    Link.active_to <= now,
                    Link.is_active == True,  # noqa: E712
                    Link.is_deleted == False,  # noqa: E712
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
                    .where(Link.is_deleted == False, Link.id != best.id)  # noqa: E712
                    .values(is_active=False)
                )
                best.is_active = True
                # Помечаем ВСЕ кандидаты, иначе через 5 минут включится следующий
                for link in to_activate:
                    link.schedule_applied = True
                logger.info("scheduler: activated link_id=%s '%s'", best.id, best.title)

                notifications.append(
                    f"🔄 <b>Автопереключение зеркала</b>\n\n"
                    f"Активировано: <b>{html.escape(best.title)}</b>\n"
                    f"URL: <code>{html.escape(best.url)}</code>"
                )

            if to_deactivate:
                titles = ", ".join(html.escape(l.title) for l in to_deactivate)
                notifications.append(f"⏳ <b>Срок зеркал истёк</b>\n\nДеактивированы: {titles}")

            await session.commit()

        except Exception:
            logger.exception("scheduler: switch_scheduled_links failed")
            await session.rollback()
            return

    for text in notifications:
        await notify_admins(bot, text)


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
    FIX (#11): если все активные зеркала упали — включает следующее
    рабочее по приоритету (AUTO_SWITCH_ON_DOWN).
    """
    notifications: list[str] = []

    async with session_factory() as session:
        try:
            links = list((await session.scalars(
                select(Link).where(Link.is_deleted == False)  # noqa: E712
            )).all())

            if not links:
                return

            results = await _ping_all(links)

            changed: list[tuple[Link, bool, str]] = []
            for link, check in zip(links, results):
                is_healthy = await _with_fail_threshold(link, check.ok)
                if link.is_healthy != is_healthy:
                    changed.append((link, is_healthy, check.reason))
                    link.is_healthy = is_healthy

            switch_text = None
            if settings.AUTO_SWITCH_ON_DOWN and needs_switch(links):
                switch_text = await _switch_to_replacement(session, links)

            if not changed and switch_text is None:
                await session.rollback()
                return

            await session.commit()
            if changed:
                notifications.append(_health_changes_text(changed))
            if switch_text:
                notifications.append(switch_text)

        except Exception:
            logger.exception("scheduler: health_check_links failed")
            await session.rollback()
            return

    for text in notifications:
        await notify_admins(bot, text)


async def _switch_to_replacement(session: AsyncSession, links: list[Link]) -> str | None:
    """Выключает упавшие активные зеркала и включает лучшее рабочее."""
    down = [l for l in links if l.is_active and not l.is_deleted]
    replacement = pick_replacement(links)

    if replacement is None:
        logger.warning("scheduler: all mirrors are down, nothing to switch to")
        # Не спамим каждые 10 минут — одно предупреждение в час
        redis = await get_redis()
        if not await redis.set("health:all_down_alert", "1", ex=3600, nx=True):
            return None
        return (
            "🚨 <b>Все зеркала недоступны</b>\n\n"
            "Активное зеркало упало, а рабочих замен нет. "
            "Добавьте новое зеркало в админке."
        )

    await LinkRepository(session).activate(replacement.id, admin_id=None)
    for link in links:
        link.is_active = link.id == replacement.id

    session.add(ActionLog(
        action=ActionType.LINK_SWITCHED,
        meta={
            "action": "auto_switch",
            "reason": "health",
            "from": [l.id for l in down],
            "to": replacement.id,
        },
    ))
    logger.info(
        "scheduler: auto-switched from %s to link_id=%s",
        [l.id for l in down], replacement.id,
    )
    down_titles = ", ".join(html.escape(l.title) for l in down)
    return (
        f"🔄 <b>Автопереключение зеркала</b>\n\n"
        f"Упало: {down_titles}\n"
        f"Включено: <b>{html.escape(replacement.title)}</b>\n"
        f"URL: <code>{html.escape(replacement.url)}</code>"
    )


@dataclass(frozen=True)
class PingResult:
    ok: bool
    reason: str = ""


async def _ping_all(links: list[Link]) -> list[PingResult]:
    """Пингуем все ссылки параллельно. Порядок результатов = порядок links."""
    async with aiohttp.ClientSession(timeout=_PING_TIMEOUT) as http:
        return list(await asyncio.gather(*(_ping_one(http, link.url) for link in links)))


async def _ping_one(http: aiohttp.ClientSession, url: str) -> PingResult:
    """
    FIX (#12): кроме кода ответа проверяем, что после редиректов мы
    остались на своём домене. Заглушки провайдеров о блокировке
    часто отвечают 200, но с другого домена.
    """
    try:
        async with http.get(
            url,
            allow_redirects=True,
            headers=_HEADERS,
            # Прокси в нужной стране — проверка «глазами» пользователя
            proxy=settings.HEALTHCHECK_PROXY or None,
        ) as resp:
            final_url = str(resp.url)
            if not same_site(url, final_url):
                return PingResult(False, f"редирект на {site_host(final_url) or final_url}")
            if not status_ok(resp.status, allow_403=settings.HEALTHCHECK_OK_403):
                return PingResult(False, f"код {resp.status}")
            return PingResult(True)
    except asyncio.TimeoutError:
        return PingResult(False, "таймаут")
    except Exception as e:
        logger.debug("ping url=%s error=%s", url, e)
        return PingResult(False, type(e).__name__)


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


def _health_changes_text(changed: list[tuple[Link, bool, str]]) -> str:
    parts: list[str] = []

    went_down = [(l, r) for l, h, r in changed if not h]
    came_up = [l for l, h, _ in changed if h]

    if went_down:
        lines = "\n".join(
            f"  • {html.escape(l.title)} — <code>{html.escape(l.url)}</code>"
            + (f" ({html.escape(r)})" if r else "")
            for l, r in went_down
        )
        parts.append(f"❌ <b>Зеркала упали:</b>\n{lines}")

    if came_up:
        lines = "\n".join(
            f"  • {html.escape(l.title)} — <code>{html.escape(l.url)}</code>" for l in came_up
        )
        parts.append(f"✅ <b>Зеркала восстановились:</b>\n{lines}")

    return "\n\n".join(parts)


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

            await notify_admins(
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


# Совместимость: раньше функция жила здесь и импортировалась из других модулей
_notify_admins = notify_admins
