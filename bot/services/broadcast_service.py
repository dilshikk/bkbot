"""
Сервис рассылки.

Батчинг: по 30 пользователей с задержкой 0.05 сек между сообщениями.
Это ~600 сообщений/мин — в пределах лимита Telegram (30/сек на бота).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.core.background_tasks import create_background_task
from bot.database.session import AsyncSessionFactory
from bot.database.models import Broadcast, BroadcastStatus, User, UserStatus

logger = logging.getLogger(__name__)

_BATCH_SIZE = 30    # сообщений за одну итерацию
_SEND_DELAY = 0.05  # секунд между отправками
# Проверяем статус рассылки раз в N пользователей, а не каждый раз
_CANCEL_CHECK_INTERVAL = 50


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
        # FIX: заменён deprecated datetime.utcnow()
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
    Выполняется вне основного запроса.
    Использует собственную сессию БД.
    """
    async with session_factory() as session:
        broadcast = await session.get(Broadcast, broadcast_id)
        if broadcast is None:
            logger.error("broadcast_id=%s not found", broadcast_id)
            return

        if broadcast.status != BroadcastStatus.RUNNING:
            return

        kb = _build_keyboard(broadcast.buttons)
        offset = 0
        sent = failed = processed = 0

        try:
            while True:
                # Получаем батч активных пользователей
                result = await session.execute(
                    select(User.telegram_id)
                    .where(User.status == UserStatus.ACTIVE)
                    .order_by(User.id)
                    .offset(offset)
                    .limit(_BATCH_SIZE)
                )
                batch = list(result.scalars().all())
                if not batch:
                    break

                for telegram_id in batch:
                    # FIX: проверяем отмену раз в N пользователей, а не каждый раз.
                    # Ранее session.refresh(broadcast) вызывался для КАЖДОГО
                    # пользователя — при 10к юзеров это 10к лишних запросов к БД.
                    processed += 1
                    if processed % _CANCEL_CHECK_INTERVAL == 0:
                        await session.refresh(broadcast)
                        if broadcast.status == BroadcastStatus.CANCELLED:
                            broadcast.sent = sent
                            broadcast.failed = failed
                            await session.commit()
                            logger.info("broadcast_id=%s cancelled mid-flight", broadcast_id)
                            return

                    success = await _send_one(bot, telegram_id, broadcast, kb)
                    if success:
                        sent += 1
                    else:
                        failed += 1

                    await asyncio.sleep(_SEND_DELAY)

                # Обновляем прогресс после каждого батча
                broadcast.sent = sent
                broadcast.failed = failed
                await session.commit()

                offset += _BATCH_SIZE

            # Завершено
            broadcast.status = BroadcastStatus.DONE
            # FIX: заменён deprecated datetime.utcnow()
            broadcast.finished_at = _utcnow()
            broadcast.sent = sent
            broadcast.failed = failed
            await session.commit()

            logger.info(
                "broadcast_id=%s done | sent=%s failed=%s",
                broadcast_id, sent, failed,
            )

        except Exception:
            logger.exception("broadcast_id=%s crashed", broadcast_id)
            broadcast.status = BroadcastStatus.FAILED
            await session.commit()


# ── Helpers ─────────────────────────────────────────────────

async def _send_one(
    bot: Bot,
    telegram_id: int,
    broadcast: Broadcast,
    kb: InlineKeyboardMarkup | None,
) -> bool:
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
                # FIX: disable_web_page_preview deprecated в aiogram 3.x
                link_preview_options={"is_disabled": True},
            )
        return True

    except TelegramRetryAfter as e:
        # FIX: обработка 429 Too Many Requests — ждём и повторяем
        logger.warning("rate limited, sleeping %ss", e.retry_after)
        await asyncio.sleep(e.retry_after)
        return await _send_one(bot, telegram_id, broadcast, kb)

    except TelegramForbiddenError:
        # Пользователь заблокировал бота — не спамим в лог
        return False
    except TelegramBadRequest as e:
        logger.warning("send failed telegram_id=%s: %s", telegram_id, e)
        return False
    except Exception as e:
        logger.error("send error telegram_id=%s: %s", telegram_id, e)
        return False


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
