from aiogram import Router

from bot.handlers.group import commands

router = Router(name="group")
router.include_router(commands.router)
