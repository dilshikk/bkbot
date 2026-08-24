# bot/handlers/admin/broadcast.py
from __future__ import annotations

import asyncio
from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Broadcast, BroadcastStatus, User, UserStatus
from bot.database.session import AsyncSessionFactory
from bot.filters.admin import IsAdmin
from bot.keyboards.admin import admin_main_keyboard, cancel_keyboard
from bot.repositories.broadcast_repo import BroadcastRepository
from bot.services.broadcast_service import BroadcastService, run_broadcast_task

router = Router(name="admin.broadcast")


class BroadcastFlow(StatesGroup):
    enter_text    = State()
    enter_photo   = State()
    enter_buttons = State()


# ── Клавиатура меню рассылки ──────────────────────────────────

def broadcast_menu_keyboard(broadcast_id: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if broadcast_id:
        rows += [
            [InlineKeyboardButton(text="👀 Предпросмотр",    callback_data=f"bc_preview:{broadcast_id}")],
            [InlineKeyboardButton(text="🚀 Запустить",       callback_data=f"bc_start:{broadcast_id}")],
            [InlineKeyboardButton(text="🗑 Удалить черновик", callback_data=f"bc_discard:{broadcast_id}")],
        ]
    rows += [
        [InlineKeyboardButton(text="📋 История",         callback_data="bc_history")],
        [InlineKeyboardButton(text="➕ Новая рассылка",  callback_data="bc_new")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Главное меню ──────────────────────────────────────────────

@router.message(F.text == "📢 Рассылка", IsAdmin())
async def broadcast_main(message: Message, session: AsyncSession) -> None:
    repo   = BroadcastRepository(session)
    result = await session.execute(
        select(Broadcast)
        .where(
            Broadcast.status == BroadcastStatus.DRAFT,
            Broadcast.created_by == message.from_user.id,
        )
        .order_by(Broadcast.id.desc())
        .limit(1)
    )
    draft = result.scalar_one_or_none()

    if draft:
        text = (
            f"📢 <b>Рассылка</b>\n\n"
            f"У вас есть черновик #{draft.id}.\n"
            f"Текст: {(draft.text or '—')[:80]}"
        )
    else:
        text = "📢 <b>Рассылка</b>\n\nСоздайте новую рассылку:"

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=broadcast_menu_keyboard(draft.id if draft else None),
    )


# ── Создать новую ─────────────────────────────────────────────

@router.callback_query(F.data == "bc_new", IsAdmin())
async def bc_new(call: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    repo      = BroadcastRepository(session)
    broadcast = await repo.create(created_by=call.from_user.id)
    await state.update_data(broadcast_id=broadcast.id)

    await call.message.answer(
        "✏️ <b>Шаг 1 из 3 — Текст</b>\n\n"
        "Введите текст рассылки. Поддерживается HTML-разметка:\n"
        "<code>&lt;b&gt;жирный&lt;/b&gt;</code>, "
        "<code>&lt;i&gt;курсив&lt;/i&gt;</code>, "
        "<code>&lt;a href='...'&gt;ссылка&lt;/a&gt;</code>\n\n"
        "Или отправьте <code>-</code> чтобы пропустить (если будет только фото).",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BroadcastFlow.enter_text)
    await call.answer()


# ── Шаг 1: Текст ─────────────────────────────────────────────

@router.message(BroadcastFlow.enter_text, IsAdmin())
async def bc_enter_text(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data         = await state.get_data()
    broadcast_id = data.get("broadcast_id")

    if broadcast_id is None:
        await state.clear()
        await message.answer(
            "❌ Сценарий рассылки устарел. Начните заново.",
            reply_markup=admin_main_keyboard(),
        )
        return

    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        await state.clear()
        await message.answer("❌ Черновик не найден.", reply_markup=admin_main_keyboard())
        return

    text = (message.text or "").strip()
    if text != "-":
        if len(text) > 4096:
            await message.answer(
                "❌ Текст слишком длинный (макс. 4096 символов).",
                reply_markup=cancel_keyboard,
            )
            return
        broadcast.text = text
        await session.flush()

    await message.answer(
        "📸 <b>Шаг 2 из 3 — Фото</b>\n\n"
        "Отправьте фото для рассылки (будет показано над текстом).\n\n"
        "Или отправьте <code>-</code> чтобы пропустить.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BroadcastFlow.enter_photo)


# ── Шаг 2: Фото ──────────────────────────────────────────────

@router.message(BroadcastFlow.enter_photo, F.photo, IsAdmin())
async def bc_enter_photo(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data         = await state.get_data()
    broadcast_id = data.get("broadcast_id")

    if broadcast_id is None:
        await state.clear()
        await message.answer(
            "❌ Сценарий рассылки устарел. Начните заново.",
            reply_markup=admin_main_keyboard(),
        )
        return

    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        await state.clear()
        return

    broadcast.photo_file_id = message.photo[-1].file_id
    await session.flush()
    await _ask_buttons(message, state)


@router.message(BroadcastFlow.enter_photo, F.text, IsAdmin())
async def bc_skip_photo(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    broadcast_id = (await state.get_data()).get("broadcast_id")
    broadcast    = await session.get(Broadcast, broadcast_id)

    if broadcast and not broadcast.text:
        await message.answer(
            "❌ Нужен хотя бы текст или фото.",
            reply_markup=cancel_keyboard,
        )
        return

    await _ask_buttons(message, state)


async def _ask_buttons(message: Message, state: FSMContext) -> None:
    await message.answer(
        "🔗 <b>Шаг 3 из 3 — Кнопки</b>\n\n"
        "Добавьте inline-кнопки. Формат — каждая кнопка с новой строки:\n"
        "<code>Текст кнопки | https://url.com</code>\n\n"
        "Или отправьте <code>-</code> чтобы без кнопок.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(BroadcastFlow.enter_buttons)


# ── Шаг 3: Кнопки ────────────────────────────────────────────

@router.message(BroadcastFlow.enter_buttons, IsAdmin())
async def bc_enter_buttons(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data         = await state.get_data()
    broadcast_id = data.get("broadcast_id")

    if broadcast_id is None:
        await state.clear()
        await message.answer(
            "❌ Сценарий рассылки устарел. Начните заново.",
            reply_markup=admin_main_keyboard(),
        )
        return

    broadcast = await session.get(Broadcast, broadcast_id)
    if broadcast is None:
        await state.clear()
        return

    text    = (message.text or "").strip()
    buttons: list[dict[str, str]] = []

    if text != "-":
        for line in text.splitlines():
            line = line.strip()
            if "|" not in line:
                await message.answer(
                    f"❌ Неверный формат строки:\n<code>{line}</code>\n\n"
                    f"Формат: <code>Текст | https://url</code>",
                    parse_mode="HTML",
                    reply_markup=cancel_keyboard,
                )
                return
            btn_text, _, btn_url = line.partition("|")
            btn_text = btn_text.strip()
            btn_url  = btn_url.strip()
            if not btn_url.startswith("http"):
                await message.answer(
                    f"❌ Некорректный URL: <code>{btn_url}</code>",
                    parse_mode="HTML",
                    reply_markup=cancel_keyboard,
                )
                return
            buttons.append({"text": btn_text, "url": btn_url})

    broadcast.buttons = buttons or None
    await session.flush()
    await state.clear()

    await message.answer(
        f"✅ <b>Черновик готов!</b>\n\n"
        f"📄 Текст: {(broadcast.text or '—')[:100]}\n"
        f"📸 Фото: {'✅ Да' if broadcast.photo_file_id else '❌ Нет'}\n"
        f"🔗 Кнопок: {len(buttons)}\n\n"
        f"Нажмите «👀 Предпросмотр» чтобы проверить,\n"
        f"затем «🚀 Запустить».",
        parse_mode="HTML",
        reply_markup=broadcast_menu_keyboard(broadcast.id),
    )


# ── Предпросмотр ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("bc_preview:"), IsAdmin())
async def bc_preview(call: CallbackQuery, session: AsyncSession) -> None:
    broadcast_id = int(call.data.split(":")[1])
    broadcast    = await session.get(Broadcast, broadcast_id)

    if broadcast is None:
        await call.answer("❌ Черновик не найден", show_alert=True)
        return

    svc = BroadcastService(session, call.bot)
    await svc.send_preview(broadcast, call.from_user.id)
    await call.answer("👀 Предпросмотр отправлен")


# ── Запустить ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("bc_start:"), IsAdmin())
async def bc_start(call: CallbackQuery, session: AsyncSession) -> None:
    broadcast_id = int(call.data.split(":")[1])
    broadcast    = await session.get(Broadcast, broadcast_id)

    if broadcast is None:
        await call.answer("❌ Не найдено", show_alert=True)
        return

    if not broadcast.text and not broadcast.photo_file_id:
        await call.answer("❌ Нет текста или фото", show_alert=True)
        return

    total = await session.scalar(
        select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)
    ) or 0

    broadcast.status     = BroadcastStatus.RUNNING
    broadcast.started_at = datetime.utcnow()
    broadcast.total      = total
    await session.commit()

    asyncio.create_task(
        run_broadcast_task(AsyncSessionFactory, call.bot, broadcast_id),
        name=f"broadcast:{broadcast_id}",
    )

    await call.message.edit_text(
        f"🚀 <b>Рассылка запущена!</b>\n\n"
        f"Получателей: <b>{total:,}</b>\n"
        f"ID рассылки: <code>{broadcast_id}</code>\n\n"
        f"Прогресс обновляется в истории.",
        parse_mode="HTML",
    )
    await call.answer()


# ── Удалить черновик ──────────────────────────────────────────

@router.callback_query(F.data.startswith("bc_discard:"), IsAdmin())
async def bc_discard(call: CallbackQuery, session: AsyncSession) -> None:
    broadcast_id = int(call.data.split(":")[1])
    broadcast    = await session.get(Broadcast, broadcast_id)
    if broadcast:
        broadcast.status = BroadcastStatus.CANCELLED
        await session.flush()
    await call.message.edit_text("🗑 Черновик удалён.")
    await call.answer()


# ── История ───────────────────────────────────────────────────

STATUS_ICONS = {
    BroadcastStatus.DONE:      "✅",
    BroadcastStatus.RUNNING:   "🔄",
    BroadcastStatus.CANCELLED: "🚫",
    BroadcastStatus.FAILED:    "❌",
    BroadcastStatus.PENDING:   "⏳",
    BroadcastStatus.DRAFT:     "📄",
}


@router.callback_query(F.data == "bc_history", IsAdmin())
async def bc_history(call: CallbackQuery, session: AsyncSession) -> None:
    repo    = BroadcastRepository(session)
    history = await repo.get_history(limit=10)

    if not history:
        await call.answer("📋 История пуста", show_alert=True)
        return

    lines = ["📋 <b>История рассылок</b>\n"]
    for bc in history:
        icon     = STATUS_ICONS.get(bc.status, "❓")
        date_str = bc.started_at.strftime("%d.%m %H:%M") if bc.started_at else "—"
        lines.append(
            f"{icon} #{bc.id} | {date_str} | "
            f"✉️ {bc.sent}/{bc.total} | ❌ {bc.failed}"
        )

    await call.message.answer("\n".join(lines), parse_mode="HTML")
    await call.answer()
