# bot/handlers/admin/users.py
from __future__ import annotations

from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, UserStatus, ActionType
from bot.filters.admin import IsAdmin
from bot.keyboards.admin import admin_main_keyboard, cancel_keyboard
from bot.repositories.log_repo import LogRepository
from bot.repositories.user_repo import UserRepository
from bot.services.export_service import ExportService

router = Router(name="admin.users")


class UserMgmtFlow(StatesGroup):
    search     = State()
    ban_reason = State()


class DirectMessageFlow(StatesGroup):
    enter_text = State()


def user_card_keyboard(user: User) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if user.status == UserStatus.BANNED:
        rows.append([InlineKeyboardButton(
            text="✅ Разбанить",
            callback_data=f"usr_unban:{user.telegram_id}",
        )])
    else:
        rows.append([InlineKeyboardButton(
            text="🚫 Забанить",
            callback_data=f"usr_ban:{user.telegram_id}",
        )])

    rows.append([InlineKeyboardButton(
        text="✉️ Написать пользователю",
        callback_data=f"usr_msg:{user.telegram_id}",
    )])
    rows.append([InlineKeyboardButton(
        text="◀️ Поиск",
        callback_data="usr_search_again",
    )])

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Главное меню ──────────────────────────────────────────────

@router.message(F.text == "👥 Пользователи", IsAdmin())
async def users_main(message: Message, session: AsyncSession) -> None:
    repo   = UserRepository(session)
    total  = await repo.count_total()
    banned = await repo.count_banned()

    await message.answer(
        f"👥 <b>Пользователи</b>\n\n"
        f"Всего: <b>{total:,}</b>\n"
        f"Заблокировано: <b>{banned}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Поиск",       callback_data="usr_search")],
            [InlineKeyboardButton(text="📥 Экспорт CSV", callback_data="usr_export")],
        ]),
    )


# ── Поиск ─────────────────────────────────────────────────────

@router.callback_query(F.data.in_({"usr_search", "usr_search_again"}), IsAdmin())
async def usr_search_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer(
        "🔍 Введите <b>Telegram ID</b>, <b>@username</b> или <b>имя</b>:",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(UserMgmtFlow.search)
    await call.answer()


@router.message(UserMgmtFlow.search, IsAdmin())
async def usr_search_process(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    query = (message.text or "").strip()
    if not query:
        return

    repo  = UserRepository(session)
    users = await repo.search(query)
    await state.clear()

    if not users:
        await message.answer(
            "❌ Пользователи не найдены.",
            reply_markup=admin_main_keyboard(),
        )
        return

    if len(users) == 1:
        await _send_user_card(message, users[0])
        return

    # Несколько результатов — показываем список
    buttons = [
        [InlineKeyboardButton(
            text=f"@{u.username or u.first_name or u.telegram_id}",
            callback_data=f"usr_view:{u.telegram_id}",
        )]
        for u in users
    ]
    await message.answer(
        f"🔍 Найдено {len(users)} пользователей:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("usr_view:"), IsAdmin())
async def usr_view(call: CallbackQuery, session: AsyncSession) -> None:
    telegram_id = int(call.data.split(":")[1])
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    if user is None:
        await call.answer("❌ Не найден", show_alert=True)
        return
    await _send_user_card(call.message, user)
    await call.answer()


async def _send_user_card(message: Message, user: User) -> None:
    status_icon = {
        UserStatus.ACTIVE:  "🟢",
        UserStatus.BANNED:  "🚫",
        UserStatus.DELETED: "🗑",
    }.get(user.status, "❓")

    full_name = " ".join(filter(None, [user.first_name, user.last_name])) or "—"

    text = (
        f"👤 <b>Пользователь</b>\n"
        f"{'━' * 22}\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"Username: @{user.username or '—'}\n"
        f"Имя: {full_name}\n"
        f"Статус: {status_icon} {user.status}\n"
        f"Подписан: {'✅' if user.is_subscribed else '❌'}\n"
        f"Источник: {user.source or 'direct'}\n"
        f"Зарегистрирован: {user.registered_at.strftime('%d.%m.%Y %H:%M') if user.registered_at else '—'}\n"
        f"Последний вход: {user.last_seen_at.strftime('%d.%m.%Y %H:%M') if user.last_seen_at else '—'}"
    )
    if user.ban_reason:
        text += f"\n🚫 Причина бана: {user.ban_reason}"

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=user_card_keyboard(user),
    )


# ── Бан ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("usr_ban:"), IsAdmin())
async def usr_ban_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    telegram_id = int(call.data.split(":")[1])
    await state.update_data(ban_target=telegram_id)
    await call.message.answer(
        "🚫 Введите причину бана:",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(UserMgmtFlow.ban_reason)
    await call.answer()


@router.message(UserMgmtFlow.ban_reason, IsAdmin())
async def usr_ban_confirm(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    reason = (message.text or "").strip()
    if not reason:
        await message.answer(
            "❌ Причина не может быть пустой.",
            reply_markup=cancel_keyboard,
        )
        return

    data       = await state.get_data()
    ban_target = data.get("ban_target")

    if ban_target is None:
        await state.clear()
        await message.answer(
            "❌ Данные цепочки устарели. Откройте карточку пользователя заново.",
            reply_markup=admin_main_keyboard(),
        )
        return

    telegram_id = int(ban_target)
    repo        = UserRepository(session)
    log         = LogRepository(session)
    success     = await repo.ban(telegram_id, reason)
    await state.clear()

    if success:
        await log.log(
            ActionType.BANNED,
            telegram_id=message.from_user.id,
            meta={"target": telegram_id, "reason": reason},
        )
        await message.answer(
            f"🚫 Пользователь <code>{telegram_id}</code> заблокирован.\n"
            f"Причина: {reason}",
            parse_mode="HTML",
            reply_markup=admin_main_keyboard(),
        )
        try:
            await message.bot.send_message(
                telegram_id,
                f"🚫 Ваш аккаунт заблокирован.\n\nПричина: {reason}",
            )
        except Exception:
            pass
    else:
        await message.answer(
            "❌ Пользователь не найден.",
            reply_markup=admin_main_keyboard(),
        )


@router.callback_query(F.data.startswith("usr_unban:"), IsAdmin())
async def usr_unban(call: CallbackQuery, session: AsyncSession) -> None:
    telegram_id = int(call.data.split(":")[1])
    repo        = UserRepository(session)
    log         = LogRepository(session)
    success     = await repo.unban(telegram_id)

    if success:
        await log.log(
            ActionType.UNBANNED,
            telegram_id=call.from_user.id,
            meta={"target": telegram_id},
        )
        await call.message.edit_text(
            f"✅ Пользователь <code>{telegram_id}</code> разблокирован.",
            parse_mode="HTML",
        )
        try:
            await call.bot.send_message(
                telegram_id,
                "✅ Ваш аккаунт разблокирован. Добро пожаловать обратно!",
            )
        except Exception:
            pass
    else:
        await call.answer("❌ Пользователь не найден", show_alert=True)

    await call.answer()


# ── Экспорт CSV ───────────────────────────────────────────────

@router.callback_query(F.data == "usr_export", IsAdmin())
async def usr_export(call: CallbackQuery, session: AsyncSession) -> None:
    await call.answer("⏳ Готовлю файл...")

    repo      = UserRepository(session)
    users     = await repo.get_all_for_export()
    csv_bytes = ExportService.users_to_csv(users)
    filename  = f"users_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"

    await call.message.answer_document(
        document=BufferedInputFile(csv_bytes.read(), filename=filename),
        caption=f"📥 Экспорт пользователей\nВсего: {len(users):,}",
    )


# ── Написать пользователю ─────────────────────────────────────

@router.callback_query(F.data.startswith("usr_msg:"), IsAdmin())
async def usr_msg_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    telegram_id = int(call.data.split(":")[1])
    await state.update_data(msg_target=telegram_id)
    await call.message.answer(
        f"✏️ Введите сообщение для <code>{telegram_id}</code>:",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(DirectMessageFlow.enter_text)
    await call.answer()


@router.message(DirectMessageFlow.enter_text, IsAdmin())
async def usr_msg_send(message: Message, state: FSMContext) -> None:
    data       = await state.get_data()
    msg_target = data.get("msg_target")

    if msg_target is None:
        await state.clear()
        await message.answer(
            "❌ Данные цепочки устарели. Откройте карточку пользователя заново.",
            reply_markup=admin_main_keyboard(),
        )
        return

    telegram_id = int(msg_target)
    text        = message.text or ""
    await state.clear()

    try:
        await message.bot.send_message(telegram_id, text)
        await message.answer(
            f"✅ Сообщение отправлено пользователю <code>{telegram_id}</code>.",
            parse_mode="HTML",
            reply_markup=admin_main_keyboard(),
        )
    except Exception as e:
        await message.answer(
            f"❌ Не удалось отправить: {e}",
            reply_markup=admin_main_keyboard(),
        )
