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
from bot.middlewares.maintenance import MaintenanceMiddleware
from bot.middlewares.ban_check import BanCheckMiddleware
from bot.middlewares.throttle import ThrottleMiddleware
from bot.middlewares.subscription_guard import SubscriptionGuardMiddleware
from bot.middlewares.private_only import PrivateOnlyMiddleware
from bot.middlewares.service_cleaner import ServiceMessageCleanerMiddleware
from bot.middlewares.group_gate import GroupCommandGateMiddleware
from bot.core.background_tasks import shutdown_background_tasks
from bot.core.redis_client import close_redis
from bot.handlers.admin import router as admin_router
from bot.handlers.group import router as group_router
from bot.handlers.user import router as user_router
from bot.scheduler.setup import create_scheduler
from bot.services.admin_notify import notify_admins
from bot.services.broadcast_service import resume_running_broadcasts
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

    # ── Middlewares (порядок критически важен) ───────────────
    #
    # dp.update:
    # 0. ServiceMessageCleanerMiddleware — удалить системные сообщения в группах
    # 1. GroupCommandGateMiddleware — в группах пропустить только /app и /link
    #                                 (остальное отбрасывается без обращения к БД)
    # 2. DbSessionMiddleware      — открыть сессию (нужна всем остальным)
    # 3. UserSyncMiddleware       — получить/создать db_user (в группах — только найти)
    #
    # dp.message / dp.callback_query:
    # 4. MaintenanceMiddleware    — тех. работы: блокировать всех кроме админов
    # 5. PrivateOnlyMiddleware    — только личные сообщения + команды групп
    # 6. BanCheckMiddleware       — проверить бан (только Message)
    # 7. ThrottleMiddleware       — антиспам (только личные Message)
    # 8. SubscriptionGuardMiddleware — проверить подписку (только личные чаты)

    dp.update.outer_middleware(ServiceMessageCleanerMiddleware())
    dp.update.outer_middleware(GroupCommandGateMiddleware())
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.update.outer_middleware(UserSyncMiddleware())

    # FIX (#9): на dp.update middleware получал Update вместо Message/CallbackQuery
    # и не отвечал пользователям текстом техработ
    maintenance = MaintenanceMiddleware()
    dp.message.outer_middleware(maintenance)
    dp.callback_query.outer_middleware(maintenance)

    dp.message.outer_middleware(PrivateOnlyMiddleware())
    dp.message.outer_middleware(BanCheckMiddleware())
    dp.message.outer_middleware(ThrottleMiddleware())

    subscription_guard = SubscriptionGuardMiddleware()
    dp.message.outer_middleware(subscription_guard)
    dp.callback_query.outer_middleware(subscription_guard)

    # ── Routers ──────────────────────────────────────────────
    # Групповой роутер первым: он принимает только сообщения из групп
    dp.include_router(group_router)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    # ── Scheduler ────────────────────────────────────────────
    scheduler = create_scheduler(bot, AsyncSessionFactory)
    scheduler.start()
    logger.info(
        "Scheduler started | jobs: %s",
        [job.id for job in scheduler.get_jobs()],
    )

    # FIX (#10): продолжаем рассылки, прерванные прошлым перезапуском
    resumed = await resume_running_broadcasts(AsyncSessionFactory, bot)

    startup_text = "✅ <b>Бот запущен</b>"
    if resumed:
        ids = ", ".join(f"#{i}" for i in resumed)
        startup_text += f"\n\n🔄 Продолжены рассылки: {ids}"
    await notify_admins(bot, startup_text)

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


if __name__ == "__main__":
    asyncio.run(main())
