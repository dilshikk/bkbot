"""
Настройка логирования через loguru.

Использование в любом модуле:
    from loguru import logger
    logger.info("message")
    logger.error("error: {}", e)
"""
from __future__ import annotations

import logging
import sys

from loguru import logger


def setup_logging(level: str = "INFO", log_file: str | None = "logs/bot.log") -> None:
    """
    Вызывать один раз при старте в main.py.

    level    — уровень логов: DEBUG / INFO / WARNING / ERROR
    log_file — путь к файлу (None = только консоль)
    """
    # Убираем дефолтный хендлер loguru
    logger.remove()

    # ── Консоль ──────────────────────────────────────────────
    logger.add(
        sys.stdout,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # ── Файл (ротация по размеру, хранить 7 дней) ────────────
    if log_file:
        logger.add(
            log_file,
            level=level,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
                "{name}:{function}:{line} | {message}"
            ),
            rotation="10 MB",     # новый файл каждые 10 МБ
            retention="7 days",   # удалять старше 7 дней
            compression="zip",    # сжимать старые файлы
            encoding="utf-8",
            enqueue=True,         # асинхронная запись — не блокирует бота
            # Без значений переменных в traceback: иначе в файл попадают
            # сообщения пользователей и служебные данные, а лог раздувается
            diagnose=False,
            backtrace=False,
        )

    # ── Перехватываем стандартный logging (aiogram, sqlalchemy) ──
    _intercept_standard_logging(level)

    logger.info("Logging configured | level={} file={}", level, log_file or "stdout only")


class _InterceptHandler(logging.Handler):
    """
    Перенаправляет все записи стандартного logging в loguru.
    Нужно чтобы логи aiogram, sqlalchemy, apscheduler
    выводились в одном формате.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Определяем уровень loguru
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = str(record.levelno)

        # Находим правильный frame для имени файла/строки
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


class _NetworkRetryFilter(logging.Filter):
    """
    Кратковременные обрывы связи с Telegram (Connection reset, Bad Gateway)
    aiogram сам переживает и повторяет запрос. Пишем их как WARNING,
    чтобы настоящие ошибки было видно среди ERROR.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.ERROR and "Failed to fetch updates" in record.getMessage():
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        return True


def _intercept_standard_logging(level: str) -> None:
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    # Заглушаем слишком шумные логгеры.
    # apscheduler писал две строки на каждый запуск задачи (~98% лога),
    # ошибки задач он по-прежнему пишет как WARNING/ERROR.
    for noisy in ("aiohttp.access", "aiogram.dispatcher", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("aiogram.dispatcher").addFilter(_NetworkRetryFilter())
