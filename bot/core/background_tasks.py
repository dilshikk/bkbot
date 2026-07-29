from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def create_background_task(awaitable: Awaitable, *, name: str | None = None) -> asyncio.Task:
    task = asyncio.create_task(awaitable, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(_log_task_error)
    return task


async def shutdown_background_tasks(timeout: float = 15.0) -> None:
    if not _background_tasks:
        return

    tasks = tuple(_background_tasks)
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Cancelling %s background task(s)", len(_background_tasks))
        for task in tuple(_background_tasks):
            task.cancel()
        await asyncio.gather(*tuple(_background_tasks), return_exceptions=True)


def _log_task_error(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error(
            "Background task failed",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
