from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey,
    Integer, String, Text, JSON, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.database.base import Base, TimestampMixin


# ─────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────

class UserStatus(str, enum.Enum):
    ACTIVE  = "active"
    BANNED  = "banned"
    DELETED = "deleted"


class ActionType(str, enum.Enum):
    START          = "start"
    GET_MIRROR     = "get_mirror"
    GET_APP        = "get_app"
    CHECK_SUB      = "check_sub"
    SUB_PASSED     = "sub_passed"
    SUB_FAILED     = "sub_failed"
    BANNED         = "banned"
    UNBANNED       = "unbanned"
    BROADCAST_SENT = "broadcast_sent"
    LINK_SWITCHED  = "link_switched"
    ADMIN_ACTION   = "admin_action"


class BroadcastStatus(str, enum.Enum):
    DRAFT     = "draft"
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    CANCELLED = "cancelled"
    FAILED    = "failed"


# ─────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id:          Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int]  = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username:    Mapped[str | None] = mapped_column(String(64))
    first_name:  Mapped[str | None] = mapped_column(String(128))
    last_name:   Mapped[str | None] = mapped_column(String(128))
    language:    Mapped[str]  = mapped_column(String(8), default="ru", server_default="ru")
    source:      Mapped[str | None] = mapped_column(String(128))
    ref_code:    Mapped[str | None] = mapped_column(String(64), index=True)
    status:      Mapped[str]  = mapped_column(String(16), default=UserStatus.ACTIVE, server_default="active")
    ban_reason:  Mapped[str | None] = mapped_column(String(256))
    is_subscribed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    registered_at: Mapped[datetime] = mapped_column(DateTime, server_default="now()")

    logs: Mapped[list[ActionLog]] = relationship(back_populates="user", lazy="noload")

    @property
    def is_banned(self) -> bool:
        return self.status == UserStatus.BANNED

    @property
    def full_name(self) -> str:
        parts = filter(None, [self.first_name, self.last_name])
        return " ".join(parts) or self.username or str(self.telegram_id)


# ─────────────────────────────────────────────
# Links (Mirrors)
# ─────────────────────────────────────────────

class Link(Base, TimestampMixin):
    __tablename__ = "links"

    id:          Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    title:       Mapped[str]  = mapped_column(String(128), nullable=False)
    url:         Mapped[str]  = mapped_column(String(2048), nullable=False)
    priority:    Mapped[int]  = mapped_column(Integer, default=0, server_default="0")
    is_active:   Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", index=True)
    is_healthy:  Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    active_from: Mapped[datetime | None] = mapped_column(DateTime)
    active_to:   Mapped[datetime | None] = mapped_column(DateTime)
    click_count: Mapped[int]  = mapped_column(Integer, default=0, server_default="0")
    created_by:  Mapped[int | None] = mapped_column(BigInteger)
    updated_by:  Mapped[int | None] = mapped_column(BigInteger)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_deleted:  Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    photo_file_id: Mapped[str | None] = mapped_column(String(256))

    __table_args__ = (
        Index("ix_links_active_healthy", "is_active", "is_healthy", "is_deleted"),
        Index("ix_links_scheduled", "active_from", "active_to"),
    )


# ─────────────────────────────────────────────
# Channels (обязательные подписки)
# ─────────────────────────────────────────────

class Channel(Base, TimestampMixin):
    __tablename__ = "channels"

    id:          Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int]  = mapped_column(BigInteger, unique=True, nullable=False)
    title:       Mapped[str]  = mapped_column(String(128), nullable=False)
    username:    Mapped[str | None] = mapped_column(String(64))
    invite_link: Mapped[str | None] = mapped_column(String(256))
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_active:   Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


# ─────────────────────────────────────────────
# Settings (singleton — всегда 1 запись)
# ─────────────────────────────────────────────

class Settings(Base, TimestampMixin):
    __tablename__ = "settings"

    id:                Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_enabled:       Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    maintenance:       Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    maintenance_text:  Mapped[str]  = mapped_column(Text, default="🔧 Технические работы. Скоро вернёмся.")
    welcome_text:      Mapped[str]  = mapped_column(Text, default="👋 Добро пожаловать!")
    after_sub_text:    Mapped[str]  = mapped_column(Text, default="✅ Отлично! Теперь у вас есть доступ.")
    support_link:      Mapped[str | None] = mapped_column(String(256))
    version:           Mapped[str]  = mapped_column(String(32), default="1.0.0")
    updated_by:        Mapped[int | None] = mapped_column(BigInteger)

    # ── Приложение (APK) ──────────────────────────────────────
    # app_enabled: показывать ли кнопку "📱 Получить приложение" пользователям
    # app_file_id: Telegram file_id загруженного APK-файла
    # app_caption: текст/описание, которое бот отправляет вместе с файлом
    app_enabled:  Mapped[bool]      = mapped_column(Boolean, default=False, server_default="false")
    app_file_id:  Mapped[str | None] = mapped_column(String(256))
    app_caption:  Mapped[str | None] = mapped_column(Text)


# ─────────────────────────────────────────────
# Broadcasts
# ─────────────────────────────────────────────

class Broadcast(Base, TimestampMixin):
    __tablename__ = "broadcasts"

    id:            Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    text:          Mapped[str | None] = mapped_column(Text)
    photo_file_id: Mapped[str | None] = mapped_column(String(256))
    buttons:       Mapped[dict | None]  = mapped_column(JSON)
    status:        Mapped[str]  = mapped_column(String(16), default=BroadcastStatus.DRAFT)
    scheduled_at:  Mapped[datetime | None] = mapped_column(DateTime)
    started_at:    Mapped[datetime | None] = mapped_column(DateTime)
    finished_at:   Mapped[datetime | None] = mapped_column(DateTime)
    total:         Mapped[int]  = mapped_column(Integer, default=0)
    sent:          Mapped[int]  = mapped_column(Integer, default=0)
    failed:        Mapped[int]  = mapped_column(Integer, default=0)
    created_by:    Mapped[int | None] = mapped_column(BigInteger)


# ─────────────────────────────────────────────
# Action Logs
# ─────────────────────────────────────────────

class ActionLog(Base):
    __tablename__ = "action_logs"

    id:          Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:     Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action:      Mapped[str]  = mapped_column(String(32), nullable=False, index=True)
    meta:        Mapped[dict | None] = mapped_column(JSON)
    created_at:  Mapped[datetime] = mapped_column(DateTime, server_default="now()", index=True)

    user: Mapped[User | None] = relationship(back_populates="logs", lazy="noload")

    __table_args__ = (
        Index("ix_logs_action_created", "action", "created_at"),
    )
