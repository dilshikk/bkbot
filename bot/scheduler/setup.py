import logging
from typing import Callable, Coroutine, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from bot.scheduler.tasks import (
    switch_scheduled_links,
    health_check_links,
    daily_stats,
    run_pending_broadcasts,
)

logger = logging.getLogger(__name__)


def create_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    # ── Переключение ссылок по расписанию — каждые 5 минут
    scheduler.add_job(
        _wrap(switch_scheduled_links, session_factory, bot),
        trigger=IntervalTrigger(minutes=5),
        id="switch_links",
        name="Switch scheduled links",
        replace_existing=True,
        misfire_grace_time=60,
    )

    # ── Health check — каждые 10 минут
    scheduler.add_job(
        _wrap(health_check_links, session_factory, bot),
        trigger=IntervalTrigger(minutes=10),
        id="health_check",
        name="Health check links",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # ── Дейли статистика — каждый день в 09:00 UTC
    scheduler.add_job(
        _wrap(daily_stats, session_factory, bot),
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_stats",
        name="Daily statistics",
        replace_existing=True,
    )
    
    scheduler.add_job(
        _wrap(run_pending_broadcasts, session_factory, bot),
        trigger=IntervalTrigger(minutes=1),
        id="pending_broadcasts",
        name="Run pending broadcasts",
        replace_existing=True,
        misfire_grace_time=30,
    )

    return scheduler


def _wrap(
    coro_func,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
) -> Callable[[], Coroutine[Any, Any, None]]:
    """
    APScheduler вызывает job как обычную функцию без аргументов.
    Оборачиваем корутину с замыканием на нужные зависимости.
    """
    async def job() -> None:
        try:
            await coro_func(session_factory, bot)
        except Exception:
            logger.exception("Unhandled error in scheduler job: %s", coro_func.__name__)

    job.__name__ = coro_func.__name__
    return job