"""
Сервис рассылки.

Батчинг: по 30 пользователей с задержкой 0.05 сек между сообщениями.
Это ~600 сообщений/мин — в пределах лимита Telegram (30/сек на бота).
"""
from __future__ import annotations

import asyncio
import enum
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.core.background_tasks import create_background_task
from bot.database.session import AsyncSessionFactory
from bot.database.models import Broadcast, BroadcastStatus, User, UserStatus

logger = logging.getLogger(__name__)

_BATCH_SIZE = 30    # сообщений за одну итерацию
_SEND_DELAY = 0.05  # секунд между отправками
# Проверяем статус рассылки раз в N пользователей, а не каждый раз
_CANCEL_CHECK_INTERVAL = 50
# Максимум попыток при 429 Too Many Requests
_MAX_RETRIES = 3


class SendResult(enum.Enum):
    OK = "ok"
    BLOCKED = "blocked"   # пользователь заблокировал бота
    FAILED = "failed"


def _utcnow() -> datetime:
    """Текущее UTC время без tzinfo (naive) для совместимости с БД."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BroadcastService:
    def __init__(self, session: AsyncSession, bot: Bot) -> None:
        self._s = session
        self._bot = bot

    # ── Подготовка ──────────────────────────────────────────

    async def prepare(
        self,
        broadcast: Broadcast,
        text: str | None = None,
        photo_file_id: str | None = None,
        buttons: list[dict[str, str]] | None = None,
    ) -> None:
        """Заполняет черновик перед отправкой."""
        if text:
            broadcast.text = text
        if photo_file_id:
            broadcast.photo_file_id = photo_file_id
        if buttons is not None:
            broadcast.buttons = buttons
        await self._s.flush()

    # ── Предпросмотр ────────────────────────────────────────

    async def send_preview(self, broadcast: Broadcast, admin_id: int) -> None:
        """Отправляет превью рассылки конкретному админу."""
        kb = _build_keyboard(broadcast.buttons)
        await _send_one(self._bot, admin_id, broadcast, kb)

    # ── Запуск ──────────────────────────────────────────────

    async def start(self, broadcast: Broadcast) -> None:
        """
        Запускает рассылку немедленно.
        Выполняется в фоне через управляемую task registry.
        """
        total = await self._s.scalar(
            select(func.count(User.id)).where(
                User.status == UserStatus.ACTIVE
            )
        ) or 0

        broadcast.status = BroadcastStatus.RUNNING
        broadcast.started_at = _utcnow()
        broadcast.total = total
        await self._s.commit()

        create_background_task(
            run_broadcast_task(
                session_factory=AsyncSessionFactory,
                bot=self._bot,
                broadcast_id=broadcast.id,
            ),
            name=f"broadcast:{broadcast.id}",
        )

    async def cancel(self, broadcast: Broadcast) -> None:
        broadcast.status = BroadcastStatus.CANCELLED
        await self._s.flush()


# ── Фоновая задача ──────────────────────────────────────────

async def run_broadcast_task(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    broadcast_id: int,
) -> None:
    """
    Выполняется вне основного запроса. Использует собственную сессию БД.

    FIX: выборка по последнему id (keyset) вместо OFFSET — список не «съезжает»,
    если кто-то выбыл из активных во время рассылки.
    FIX: заблокировавшие бота помечаются status=DELETED и больше не получают рассылки.
    """
    async with session_factory() as session:
        broadcast = await session.get(Broadcast, broadcast_id)
        if broadcast is None:
            logger.error("broadcast_id=%s not found", broadcast_id)
            return
        if broadcast.status != BroadcastStatus.RUNNING:
            return

        kb = _build_keyboard(broadcast.buttons)
        last_id = 0
        sent = failed = processed = 0
        blocked_ids: list[int] = []

        async def save_progress() -> None:
            if blocked_ids:
                await session.execute(
                    update(User)
                    .where(User.id.in_(blocked_ids))
                    .values(status=UserStatus.DELETED)
                )
                blocked_ids.clear()
            broadcast.sent = sent
            broadcast.failed = failed
            await session.commit()

        try:
            while True:
                rows = (await session.execute(
                    select(User.id, User.telegram_id)
                    .where(User.status == UserStatus.ACTIVE, User.id > last_id)
                    .order_by(User.id)
                    .limit(_BATCH_SIZE)
                )).all()
                if not rows:
                    break
                last_id = rows[-1].id

                for row in rows:
                    processed += 1
                    if processed % _CANCEL_CHECK_INTERVAL == 0:
                        await session.refresh(broadcast)
                        if broadcast.status == BroadcastStatus.CANCELLED:
                            await save_progress()
                            logger.info("broadcast_id=%s cancelled mid-flight", broadcast_id)
                            return

                    result = await _send_one(bot, row.telegram_id, broadcast, kb)
                    if result is SendResult.OK:
                        sent += 1
                    else:
                        failed += 1
                        if result is SendResult.BLOCKED:
                            blocked_ids.append(row.id)

                    await asyncio.sleep(_SEND_DELAY)

                # Прогресс сохраняем после каждого батча
                await save_progress()

            broadcast.status = BroadcastStatus.DONE
            broadcast.finished_at = _utcnow()
            await save_progress()

            logger.info(
                "broadcast_id=%s done | sent=%s failed=%s",
                broadcast_id, sent, failed,
            )

        except Exception:
            logger.exception("broadcast_id=%s crashed", broadcast_id)
            await session.rollback()
            broadcast.status = BroadcastStatus.FAILED
            await session.commit()


# ── Helpers ─────────────────────────────────────────────────

async def _send_one(
    bot: Bot,
    telegram_id: int,
    broadcast: Broadcast,
    kb: InlineKeyboardMarkup | None,
    attempt: int = 1,
) -> SendResult:
    try:
        if broadcast.photo_file_id:
            await bot.send_photo(
                chat_id=telegram_id,
                photo=broadcast.photo_file_id,
                caption=broadcast.text,
                parse_mode="HTML",
                reply_markup=kb,
            )
        elif broadcast.text:
            await bot.send_message(
                chat_id=telegram_id,
                text=broadcast.text,
                parse_mode="HTML",
                reply_markup=kb,
                link_preview_options={"is_disabled": True},
            )
        return SendResult.OK

    except TelegramRetryAfter as e:
        # FIX: ограничиваем число повторов — раньше рекурсия была бесконечной
        if attempt >= _MAX_RETRIES:
            logger.error("telegram_id=%s: retry limit reached", telegram_id)
            return SendResult.FAILED
        logger.warning("rate limited, sleeping %ss (attempt %s)", e.retry_after, attempt)
        await asyncio.sleep(e.retry_after + 1)
        return await _send_one(bot, telegram_id, broadcast, kb, attempt=attempt + 1)

    except TelegramForbiddenError:
        return SendResult.BLOCKED
    except TelegramBadRequest as e:
        logger.warning("send failed telegram_id=%s: %s", telegram_id, e)
        return SendResult.FAILED
    except Exception as e:
        logger.error("send error telegram_id=%s: %s", telegram_id, e)
        return SendResult.FAILED


def _build_keyboard(
    buttons: list[dict[str, str]] | None,
) -> InlineKeyboardMarkup | None:
    """
    buttons format: [{"text": "Открыть", "url": "https://..."}]
    """
    if not buttons:
        return None
    rows = [
        [InlineKeyboardButton(text=b["text"], url=b["url"])]
        for b in buttons
        if b.get("text") and b.get("url")
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
