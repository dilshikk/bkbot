from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import default_state
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User
from bot.filters.admin import IsAdmin
from bot.handlers.admin import dashboard, links, channels, settings, broadcast, users, stats

router = Router(name="admin")


@router.message(
    F.text.in_({"❌ Отмена", "🏠 В меню"}),
    ~StateFilter(default_state),
    IsAdmin(),
)
async def cancel_fsm(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """Сброс FSM → стартовая страница бота."""
    await state.clear()
    from bot.handlers.user.start import _handle_subscription_check
    await _handle_subscription_check(message, session, db_user)


@router.message(
    F.text == "🏠 В меню",
    IsAdmin(),
)
async def go_to_menu(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    db_user: User,
) -> None:
    """🏠 В меню без активного FSM → стартовая страница бота."""
    await state.clear()
    from bot.handlers.user.start import _handle_subscription_check
    await _handle_subscription_check(message, session, db_user)


router.include_router(dashboard.router)
router.include_router(stats.router)
router.include_router(links.router)
router.include_router(channels.router)
router.include_router(settings.router)
router.include_router(broadcast.router)
router.include_router(users.router)