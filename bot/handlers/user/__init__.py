from aiogram import Router

from bot.handlers.user import start, menu, mirror, app

router = Router(name="user")
router.include_router(start.router)
router.include_router(menu.router)
router.include_router(mirror.router)
router.include_router(app.router)
