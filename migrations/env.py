"""
Alembic env.py для async SQLAlchemy (asyncpg + PostgreSQL).

Поддерживает:
- online mode  (применение миграций к живой БД)
- offline mode (генерация SQL-скрипта без подключения)
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Импортируем модели и настройки ───────────────────────────
import sys
import os

# Добавляем корень проекта в sys.path
# чтобы работал import bot.database.*
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot.core.config import settings
from bot.database.base import Base
from bot.database import models  # noqa: F401 — регистрируем все модели

# ── Alembic Config ───────────────────────────────────────────
config = context.config

# Вставляем DATABASE_URL из .env — переопределяем пустое значение из alembic.ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Настраиваем логирование через alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Метаданные всех моделей — нужны для autogenerate
target_metadata = Base.metadata


# ── Offline mode ─────────────────────────────────────────────

def run_migrations_offline() -> None:
    """
    Генерирует SQL без реального подключения к БД.
    Запуск: alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode ──────────────────────────────────────────────

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Async engine для asyncpg."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # миграции не нуждаются в пуле
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Точка входа ──────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
