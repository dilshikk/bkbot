"""
Redis клиент — единственный экземпляр на всё приложение.
Используется для throttle, distributed locks, кеша.
"""
from __future__ import annotations

import redis.asyncio as aioredis
from redis.asyncio import Redis

from bot.core.config import settings

_redis: Redis | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None