# bot/handlers/admin/links.py
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.filters.admin import IsAdmin
from bot.keyboards.admin import (
    links_list_keyboard,
    link_actions_keyboard,
    admin_main_keyboard,
    cancel_keyboard,
)
from bot.repositories.link_repo import LinkRepository
from bot.repositories.log_repo import LogRepository
from bot.database.models import ActionType

router = Router(name="admin.links")

# ── Константы ─────────────────────────────────────────────────

_TITLE_MIN = 2
_TITLE_MAX = 128
_DT_FMT = "%d.%m.%Y %H:%M"
_DT_EXAMPLE = "25.07.2026 09:00"


# ── FSM ───────────────────────────────────────────────────────

class LinkFlow(StatesGroup):
    add_url       = State()
    edit_url      = State()
    edit_title    = State()
    schedule_from = State()
    schedule_to   = State()


# ── Вспомогательные функции ───────────────────────────────────

def _is_valid_url(url: str) -> bool:
    """Проверяет, что строка является корректным HTTP/HTTPS URL."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


def _parse_dt(text: str) -> datetime | None:
    """Парсит дату из строки. Возвращает None при ошибке."""
    try:
        return datetime.strptime(text.strip(), _DT_FMT)
    except ValueError:
        return None


def _now_naive() -> datetime:
    """Текущее время без tzinfo (naive UTC) для сравнений с БД."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Список ────────────────────────────────────────────────────

@router.message(F.text == "🔗 Ссылки", IsAdmin())
async def links_list(message: Message, session: AsyncSession) -> None:
    repo = LinkRepository(session)
    links = await repo.get_all()
    await message.answer(
        f"🔗 <b>Зеркала</b> ({len(links)} шт.)",
        parse_mode="HTML",
        reply_markup=links_list_keyboard(links),
    )


@router.callback_query(F.data == "links_back", IsAdmin())
async def links_back(call: CallbackQuery, session: AsyncSession) -> None:
    if call.message is None:
        await call.answer()
        return

    repo = LinkRepository(session)
    links = await repo.get_all()
    await call.message.edit_text(
        f"🔗 <b>Зеркала</b> ({len(links)} шт.)",
        parse_mode="HTML",
        reply_markup=links_list_keyboard(links),
    )
    await call.answer()


# ── Просмотр ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("link_view:"), IsAdmin())
async def link_view(call: CallbackQuery, session: AsyncSession) -> None:
    if call.message is None:
        await call.answer()
        return

    link_id = int(call.data.split(":")[1])
    repo = LinkRepository(session)
    link = await repo.get_by_id(link_id)

    if link is None:
        await call.answer("❌ Ссылка не найдена", show_alert=True)
        return

    scheduled = ""
    if link.active_from:
        scheduled = f"\n📅 С: <code>{link.active_from:{_DT_FMT}}</code>"
        if link.active_to:
            scheduled += f"\n📅 До: <code>{link.active_to:{_DT_FMT}}</code>"

    text = (
        f"🔗 <b>{link.title}</b>\n\n"
        f"URL: <code>{link.url}</code>\n"
        f"Статус: {'🟢 Активна' if link.is_active else '⚪️ Неактивна'}\n"
        f"Здоровье: {'✅ Доступна' if link.is_healthy else '❌ Недоступна'}\n"
        f"Приоритет: <b>{link.priority}</b>\n"
        f"Переходов: <b>{link.click_count:,}</b>\n"
        f"Резервная: {'🛡 Да' if link.is_fallback else 'Нет'}"
        f"{scheduled}"
    )
    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=link_actions_keyboard(link),
    )
    await call.answer()


# ── Добавить ──────────────────────────────────────────────────

@router.callback_query(F.data == "link_add", IsAdmin())
async def link_add_start(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return

    await state.clear()
    await call.message.answer(
        "🔗 Введите <b>URL</b> зеркала (https://...):",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(LinkFlow.add_url)
    await call.answer()


@router.message(LinkFlow.add_url, IsAdmin())
async def link_add_url(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    url = (message.text or "").strip()
    if not _is_valid_url(url):
        await message.answer(
            "❌ Некорректный URL. Должен начинаться с http:// или https:// и содержать домен.",
            reply_markup=cancel_keyboard,
        )
        return

    if message.from_user is None:
        await state.clear()
        return

    repo = LinkRepository(session)
    log = LogRepository(session)

    # Создаём ссылку с временным названием, после flush получаем ID
    link = await repo.create(
        title="_tmp",
        url=url,
        created_by=message.from_user.id,
    )
    # Обновляем название на link_{id}
    auto_title = f"link_{link.id}"
    await repo.update_title(link.id, auto_title, message.from_user.id)
    link.title = auto_title

    # Сразу активируем: деактивируем все остальные и активируем новую
    await repo.activate(link.id, message.from_user.id)
    link.is_active = True

    await log.log(
        ActionType.ADMIN_ACTION,
        telegram_id=message.from_user.id,
        meta={"action": "link_created", "link_id": link.id, "url": url},
    )
    await log.log(
        ActionType.LINK_SWITCHED,
        telegram_id=message.from_user.id,
        meta={"link_id": link.id, "action": "activated"},
    )
    await state.clear()
    await message.answer(
        f"✅ Зеркало <b>{link.title}</b> добавлено и активировано!\n"
        f"ID: <code>{link.id}</code>",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


# ── Активировать / Деактивировать ─────────────────────────────

@router.callback_query(F.data.startswith("link_activate:"), IsAdmin())
async def link_activate(call: CallbackQuery, session: AsyncSession) -> None:
    if call.message is None:
        await call.answer()
        return

    link_id = int(call.data.split(":")[1])
    repo = LinkRepository(session)
    await repo.activate(link_id, call.from_user.id)
    await LogRepository(session).log(
        ActionType.LINK_SWITCHED,
        telegram_id=call.from_user.id,
        meta={"link_id": link_id, "action": "activated"},
    )
    link = await repo.get_by_id(link_id)
    await call.message.edit_reply_markup(reply_markup=link_actions_keyboard(link))
    await call.answer("✅ Ссылка активирована")


@router.callback_query(F.data.startswith("link_deact:"), IsAdmin())
async def link_deact(call: CallbackQuery, session: AsyncSession) -> None:
    if call.message is None:
        await call.answer()
        return

    link_id = int(call.data.split(":")[1])
    repo = LinkRepository(session)
    await repo.deactivate(link_id, call.from_user.id)
    await LogRepository(session).log(
        ActionType.LINK_SWITCHED,
        telegram_id=call.from_user.id,
        meta={"link_id": link_id, "action": "deactivated"},
    )
    link = await repo.get_by_id(link_id)
    await call.message.edit_reply_markup(reply_markup=link_actions_keyboard(link))
    await call.answer("⚪️ Деактивировано")


# ── Изменить URL ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("link_edit_url:"), IsAdmin())
async def link_edit_url_start(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return

    await state.clear()
    link_id = int(call.data.split(":")[1])
    await state.update_data(link_id=link_id)
    await call.message.answer(
        "🔗 Введите новый URL:",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(LinkFlow.edit_url)
    await call.answer()


@router.message(LinkFlow.edit_url, IsAdmin())
async def link_edit_url_done(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    url = (message.text or "").strip()
    if not _is_valid_url(url):
        await message.answer(
            "❌ Некорректный URL. Должен начинаться с http:// или https:// и содержать домен.",
            reply_markup=cancel_keyboard,
        )
        return

    if message.from_user is None:
        await state.clear()
        return

    data = await state.get_data()
    link_id: int | None = data.get("link_id")

    if link_id is None:
        await state.clear()
        await message.answer(
            "❌ Данные цепочки устарели. Откройте ссылку заново.",
            reply_markup=admin_main_keyboard(),
        )
        return

    await LinkRepository(session).update_url(link_id, url, message.from_user.id)
    await LogRepository(session).log(
        ActionType.ADMIN_ACTION,
        telegram_id=message.from_user.id,
        meta={"action": "link_url_updated", "link_id": link_id, "new_url": url},
    )
    await state.clear()
    await message.answer("✅ URL обновлён.", reply_markup=admin_main_keyboard())


# ── Изменить название ─────────────────────────────────────────

@router.callback_query(F.data.startswith("link_edit_title:"), IsAdmin())
async def link_edit_title_start(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return

    await state.clear()
    link_id = int(call.data.split(":")[1])
    await state.update_data(link_id=link_id)
    await call.message.answer(
        "✏️ Введите новое название:",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(LinkFlow.edit_title)
    await call.answer()


@router.message(LinkFlow.edit_title, IsAdmin())
async def link_edit_title_done(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    title = (message.text or "").strip()
    if not (_TITLE_MIN <= len(title) <= _TITLE_MAX):
        await message.answer(
            f"❌ Название: {_TITLE_MIN}–{_TITLE_MAX} символов.",
            reply_markup=cancel_keyboard,
        )
        return

    if message.from_user is None:
        await state.clear()
        return

    data = await state.get_data()
    link_id: int | None = data.get("link_id")

    if link_id is None:
        await state.clear()
        await message.answer(
            "❌ Данные цепочки устарели. Откройте ссылку заново.",
            reply_markup=admin_main_keyboard(),
        )
        return

    await LinkRepository(session).update_title(link_id, title, message.from_user.id)
    await LogRepository(session).log(
        ActionType.ADMIN_ACTION,
        telegram_id=message.from_user.id,
        meta={"action": "link_title_updated", "link_id": link_id, "new_title": title},
    )
    await state.clear()
    await message.answer("✅ Название обновлено.", reply_markup=admin_main_keyboard())


# ── Планировщик ───────────────────────────────────────────────

@router.callback_query(F.data.startswith("link_schedule:"), IsAdmin())
async def link_schedule_start(call: CallbackQuery, state: FSMContext) -> None:
    if call.message is None:
        await call.answer()
        return

    await state.clear()
    link_id = int(call.data.split(":")[1])
    await state.update_data(link_id=link_id)
    await call.message.answer(
        "📅 Введите дату и время <b>начала</b> в формате:\n"
        f"<code>{_DT_FMT.replace('%d', 'ДД').replace('%m', 'ММ').replace('%Y', 'ГГГГ').replace('%H', 'ЧЧ').replace('%M', 'ММ')}</code>\n\n"
        f"Например: <code>{_DT_EXAMPLE}</code>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(LinkFlow.schedule_from)
    await call.answer()


@router.message(LinkFlow.schedule_from, IsAdmin())
async def link_schedule_from(message: Message, state: FSMContext) -> None:
    dt = _parse_dt(message.text or "")
    if dt is None:
        await message.answer(
            f"❌ Неверный формат. Пример: <code>{_DT_EXAMPLE}</code>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard,
        )
        return

    if dt < _now_naive():
        await message.answer(
            "❌ Дата начала не может быть в прошлом.",
            reply_markup=cancel_keyboard,
        )
        return

    await state.update_data(active_from=dt)
    await message.answer(
        "📅 Введите дату <b>окончания</b> (или «-» чтобы без конца):",
        parse_mode="HTML",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(LinkFlow.schedule_to)


@router.message(LinkFlow.schedule_to, IsAdmin())
async def link_schedule_to(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if message.from_user is None:
        await state.clear()
        return

    text = (message.text or "").strip()
    active_to: datetime | None = None

    if text != "-":
        active_to = _parse_dt(text)
        if active_to is None:
            await message.answer(
                f"❌ Неверный формат. Пример: <code>25.07.2026 18:00</code>",
                parse_mode="HTML",
                reply_markup=cancel_keyboard,
            )
            return

    data = await state.get_data()
    link_id: int | None = data.get("link_id")
    active_from: datetime | None = data.get("active_from")

    if link_id is None or active_from is None:
        await state.clear()
        await message.answer(
            "❌ Данные цепочки устарели. Откройте ссылку заново.",
            reply_markup=admin_main_keyboard(),
        )
        return

    if active_to is not None and active_to <= active_from:
        await message.answer(
            "❌ Дата окончания должна быть позже даты начала.",
            reply_markup=cancel_keyboard,
        )
        return

    await LinkRepository(session).schedule(
        link_id, active_from, active_to, message.from_user.id
    )
    await LogRepository(session).log(
        ActionType.ADMIN_ACTION,
        telegram_id=message.from_user.id,
        meta={
            "action": "link_scheduled",
            "link_id": link_id,
            "active_from": active_from.isoformat(),
            "active_to": active_to.isoformat() if active_to else None,
        },
    )
    await state.clear()
    await message.answer("✅ Расписание сохранено.", reply_markup=admin_main_keyboard())


# ── Резервная ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("link_toggle_fallback:"), IsAdmin())
async def link_toggle_fallback(call: CallbackQuery, session: AsyncSession) -> None:
    if call.message is None:
        await call.answer()
        return

    link_id = int(call.data.split(":")[1])
    repo = LinkRepository(session)
    is_fallback = await repo.toggle_fallback(link_id, call.from_user.id)
    await LogRepository(session).log(
        ActionType.ADMIN_ACTION,
        telegram_id=call.from_user.id,
        meta={"action": "link_fallback_toggled", "link_id": link_id, "is_fallback": is_fallback},
    )
    link = await repo.get_by_id(link_id)
    await call.message.edit_reply_markup(reply_markup=link_actions_keyboard(link))
    await call.answer("🛡 Резервная" if is_fallback else "Снято резервирование")


# ── Удалить ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("link_delete:"), IsAdmin())
async def link_delete(call: CallbackQuery, session: AsyncSession) -> None:
    if call.message is None:
        await call.answer()
        return

    link_id = int(call.data.split(":")[1])
    await LinkRepository(session).soft_delete(link_id, call.from_user.id)
    await LogRepository(session).log(
        ActionType.ADMIN_ACTION,
        telegram_id=call.from_user.id,
        meta={"action": "link_deleted", "link_id": link_id},
    )
    repo = LinkRepository(session)
    links = await repo.get_all()
    await call.message.edit_text(
        f"🗑 Зеркало удалено.\n\n🔗 <b>Зеркала</b> ({len(links)} шт.)",
        parse_mode="HTML",
        reply_markup=links_list_keyboard(links),
    )
    await call.answer()
