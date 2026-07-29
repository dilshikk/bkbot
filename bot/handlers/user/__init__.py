from aiogram import Router

from bot.handlers.user import start, menu, mirror

router = Router(name="user")
router.include_router(start.router)
router.include_router(menu.router)
router.include_router(mirror.router)
