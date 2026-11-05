import pytest
from fakeredis import aioredis as fake_aioredis

from bot.utils.reply_cleanup import EXPIRE_KEY, claim_expired, remember_reply

CHAT = -1001
OTHER_CHAT = -1002
NOW = 1_000_000.0


@pytest.fixture
async def redis():
    client = fake_aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_first_reply_has_nothing_to_delete(redis) -> None:
    assert await remember_reply(redis, CHAT, "link", 10, ttl=120, now=NOW) is None


async def test_new_reply_returns_previous_for_deletion(redis) -> None:
    await remember_reply(redis, CHAT, "link", 10, ttl=120, now=NOW)
    assert await remember_reply(redis, CHAT, "link", 20, ttl=120, now=NOW) == 10
    assert await remember_reply(redis, CHAT, "link", 30, ttl=120, now=NOW) == 20


async def test_previous_reply_is_per_command_and_per_chat(redis) -> None:
    await remember_reply(redis, CHAT, "link", 10, ttl=120, now=NOW)
    # Ответ на /app не трогает ответ на /link, другой чат — тоже
    assert await remember_reply(redis, CHAT, "app", 11, ttl=300, now=NOW) is None
    assert await remember_reply(redis, OTHER_CHAT, "link", 12, ttl=120, now=NOW) is None


async def test_replaced_reply_is_removed_from_timer(redis) -> None:
    await remember_reply(redis, CHAT, "link", 10, ttl=120, now=NOW)
    await remember_reply(redis, CHAT, "link", 20, ttl=120, now=NOW)
    # Старый ответ уже удалён при замене — второй раз его не удаляем
    assert await claim_expired(redis, NOW + 1000) == {CHAT: [20]}


async def test_claim_returns_only_expired(redis) -> None:
    await remember_reply(redis, CHAT, "link", 10, ttl=120, now=NOW)
    await remember_reply(redis, CHAT, "app", 11, ttl=300, now=NOW)

    assert await claim_expired(redis, NOW + 60) == {}
    assert await claim_expired(redis, NOW + 120) == {CHAT: [10]}
    assert await claim_expired(redis, NOW + 300) == {CHAT: [11]}


async def test_claim_groups_by_chat_and_is_one_time(redis) -> None:
    await remember_reply(redis, CHAT, "link", 10, ttl=120, now=NOW)
    await remember_reply(redis, OTHER_CHAT, "link", 20, ttl=120, now=NOW)

    assert await claim_expired(redis, NOW + 200) == {CHAT: [10], OTHER_CHAT: [20]}
    assert await claim_expired(redis, NOW + 200) == {}


async def test_zero_ttl_disables_timer_but_keeps_replacement(redis) -> None:
    await remember_reply(redis, CHAT, "link", 10, ttl=0, now=NOW)
    assert await redis.zcard(EXPIRE_KEY) == 0
    assert await remember_reply(redis, CHAT, "link", 20, ttl=0, now=NOW) == 10


async def test_claim_respects_limit(redis) -> None:
    for message_id in range(5):
        await remember_reply(redis, CHAT, f"cmd{message_id}", message_id, ttl=1, now=NOW)

    first = await claim_expired(redis, NOW + 10, limit=3)
    rest = await claim_expired(redis, NOW + 10, limit=3)
    assert len(first[CHAT]) == 3
    assert len(rest[CHAT]) == 2
