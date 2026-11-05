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
from bot.services.group_replies import cleanup_expired_replies

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

    # ── Удаление просроченных ответов на /link и /app в группах — каждые 30 сек.
    # Дёшево: одно чтение из Redis, без обращения к БД
    scheduler.add_job(
        _wrap_bot_only(cleanup_expired_replies, bot),
        trigger=IntervalTrigger(seconds=30),
        id="group_reply_cleanup",
        name="Delete expired group replies",
        replace_existing=True,
        misfire_grace_time=30,
        coalesce=True,
        max_instances=1,
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


def _wrap_bot_only(
    coro_func: Callable[[Bot], Coroutine[Any, Any, None]],
    bot: Bot,
) -> Callable[[], Coroutine[Any, Any, None]]:
    """То же, что _wrap, для задач без сессии БД."""
    async def job() -> None:
        try:
            await coro_func(bot)
        except Exception:
            logger.exception("Unhandled error in scheduler job: %s", coro_func.__name__)

    job.__name__ = coro_func.__name__
    return job
