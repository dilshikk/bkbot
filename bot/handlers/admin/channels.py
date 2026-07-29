# bot/handlers/admin/channels.py
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.admin import IsAdmin
from bot.keyboards.admin import (
    channels_list_keyboard, channel_actions_keyboard,
    admin_main_keyboard, cancel_keyboard,
)
from bot.repositories.channel_repo import ChannelRepository

router = Router(name="admin.channels")


class ChannelFlow(StatesGroup):
    enter_chat_id = State()


# ── Список ────────────────────────────────────────────────────

@router.message(F.text == "📢 Каналы", IsAdmin())
async def channels_list(message: Message, session: AsyncSession) -> None:
    channels = await ChannelRepository(session).get_all()
    await message.answer(
        f"📢 <b>Каналы</b> ({len(channels)} шт.)",
        parse_mode="HTML",
        reply_markup=channels_list_keyboard(channels),
    )


@router.callback_query(F.data == "channels_back", IsAdmin())
async def channels_back(call: CallbackQuery, session: AsyncSession) -> None:
    channels = await ChannelRepository(session).get_all()
    await call.message.edit_text(
        f"📢 <b>Каналы</b> ({len(channels)} шт.)",
        parse_mode="HTML",
        reply_markup=channels_list_keyboard(channels),
    )
    await call.answer()


# ── Просмотр ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ch_view:"), IsAdmin())
async def ch_view(call: CallbackQuery, session: AsyncSession) -> None:
    ch_id = int(call.data.split(":")[1])
    ch    = await ChannelRepository(session).get_by_id(ch_id)

    if ch is None:
        await call.answer("❌ Канал не найден", show_alert=True)
        return

    username_str = f"@{ch.username}" if ch.username else f"ID: {ch.telegram_id}"
    text = (
        f"📢 <b>{ch.title}</b>\n\n"
        f"Telegram: {username_str}\n"
        f"Обязательный: {'🔒 Да' if ch.is_required else '🔓 Нет'}\n"
        f"Активный: {'🟢 Да' if ch.is_active else '🔴 Нет'}"
    )
    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=channel_actions_keyboard(ch),
    )
    await call.answer()


# ── Добавить ──────────────────────────────────────────────────

@router.callback_query(F.data == "ch_add", IsAdmin())
async def ch_add_start(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer(
        "📢 Перешлите любое сообщение из канала\n"
        "или введите <b>chat_id</b> (например: <code>-1001234567890</code>)\n\n"
        "⚠️ Бот должен быть администратором канала.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(ChannelFlow.enter_chat_id)
    await call.answer()


@router.message(ChannelFlow.enter_chat_id, IsAdmin())
async def ch_add_process(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    # Поддерживаем forward из канала
    if message.forward_from_chat:
        chat_id = message.forward_from_chat.id
    else:
        try:
            chat_id = int((message.text or "").strip())
        except ValueError:
            await message.answer(
                "❌ Введите числовой chat_id или перешлите сообщение из канала.",
                reply_markup=cancel_keyboard,
            )
            return

    # Получаем данные канала
    try:
        chat = await bot.get_chat(chat_id)
    except Exception as e:
        await message.answer(
            f"❌ Не удалось получить данные канала: {e}",
            reply_markup=cancel_keyboard,
        )
        return

    # Проверяем права бота
    try:
        me     = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        if member.status not in ("administrator", "creator"):
            await message.answer(
                "❌ Бот не является администратором этого канала.",
                reply_markup=admin_main_keyboard(),
            )
            await state.clear()
            return
    except Exception as e:
        await message.answer(
            f"❌ Ошибка проверки прав: {e}",
            reply_markup=admin_main_keyboard(),
        )
        await state.clear()
        return

    repo = ChannelRepository(session)
    ch   = await repo.create(
        telegram_id=chat_id,
        title=chat.title or f"Channel {chat_id}",
        username=chat.username,
        invite_link=chat.invite_link,
    )
    await state.clear()
    await message.answer(
        f"✅ Канал <b>{ch.title}</b> добавлен!\n"
        f"Обязательная подписка: 🔒 Да",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


# ── Переключатели ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ch_toggle_required:"), IsAdmin())
async def ch_toggle_required(call: CallbackQuery, session: AsyncSession) -> None:
    ch_id = int(call.data.split(":")[1])
    repo  = ChannelRepository(session)
    await repo.toggle_required(ch_id)
    ch = await repo.get_by_id(ch_id)
    await call.message.edit_reply_markup(reply_markup=channel_actions_keyboard(ch))
    await call.answer("Обновлено")


@router.callback_query(F.data.startswith("ch_toggle_active:"), IsAdmin())
async def ch_toggle_active(call: CallbackQuery, session: AsyncSession) -> None:
    ch_id = int(call.data.split(":")[1])
    repo  = ChannelRepository(session)
    await repo.toggle_active(ch_id)
    ch = await repo.get_by_id(ch_id)
    await call.message.edit_reply_markup(reply_markup=channel_actions_keyboard(ch))
    await call.answer("Обновлено")


# ── Проверка прав бота ────────────────────────────────────────

@router.callback_query(F.data.startswith("ch_check:"), IsAdmin())
async def ch_check_bot_rights(
    call: CallbackQuery,
    session: AsyncSession,
    bot: Bot,
) -> None:
    ch_id = int(call.data.split(":")[1])
    ch    = await ChannelRepository(session).get_by_id(ch_id)

    if ch is None:
        await call.answer("❌ Не найден", show_alert=True)
        return

    try:
        me         = await bot.get_me()
        member     = await bot.get_chat_member(ch.telegram_id, me.id)
        status     = member.status
        can_invite = getattr(member, "can_invite_users", False)
        text = (
            f"🔍 Права бота в <b>{ch.title}</b>\n\n"
            f"Статус: <b>{status}</b>\n"
            f"Может приглашать: {'✅' if can_invite else '❌'}"
        )
    except Exception as e:
        text = f"❌ Ошибка: {e}"

    await call.message.answer(text, parse_mode="HTML")
    await call.answer()


# ── Удалить ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("ch_delete:"), IsAdmin())
async def ch_delete(call: CallbackQuery, session: AsyncSession) -> None:
    ch_id = int(call.data.split(":")[1])
    await ChannelRepository(session).delete(ch_id)
    await call.message.edit_text("🗑 Канал удалён.")
    await call.answer()
