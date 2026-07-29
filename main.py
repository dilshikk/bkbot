import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from bot.core.config import settings
from bot.core.logging import setup_logging
from bot.database.session import AsyncSessionFactory
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.user_sync import UserSyncMiddleware
from bot.middlewares.ban_check import BanCheckMiddleware
from bot.middlewares.throttle import ThrottleMiddleware
from bot.middlewares.subscription_guard import SubscriptionGuardMiddleware
from bot.middlewares.private_only import PrivateOnlyMiddleware
from bot.core.background_tasks import shutdown_background_tasks
from bot.core.redis_client import close_redis
from bot.handlers.admin import router as admin_router
from bot.handlers.user import router as user_router
from bot.scheduler.setup import create_scheduler
from bot.utils.commands import set_commands, delete_commands

logger = logging.getLogger(__name__)


async def main() -> None:
    setup_logging(
        level="INFO",
        log_file="logs/bot.log",
    )
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # ── Middlewares ──────────────────────────────────────────
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(UserSyncMiddleware())
    dp.message.outer_middleware(PrivateOnlyMiddleware(cooldown=300))
    dp.message.outer_middleware(BanCheckMiddleware())
    dp.message.outer_middleware(ThrottleMiddleware())
    dp.message.outer_middleware(SubscriptionGuardMiddleware())

    # ── Routers ──────────────────────────────────────────────
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # ── Scheduler ────────────────────────────────────────────
    scheduler = create_scheduler(bot, AsyncSessionFactory)
    scheduler.start()
    logger.info(
        "Scheduler started | jobs: %s",
        [job.id for job in scheduler.get_jobs()],
    )

    # ── Startup уведомление ──────────────────────────────────
    await _notify_startup(bot)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await set_commands(bot)
        logger.info("Bot started | admins: %s", settings.ADMIN_IDS)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await delete_commands(bot)
        await shutdown_background_tasks()
        await close_redis()
        await bot.session.close()
        logger.info("Bot stopped")


async def _notify_startup(bot: Bot) -> None:
    """Уведомляем всех админов что бот запустился."""
    from bot.scheduler.tasks import _notify_admins
    await _notify_admins(bot, "✅ <b>Бот запущен</b>")


if __name__ == "__main__":
    asyncio.run(main())