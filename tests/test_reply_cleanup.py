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


async def test_first_call_has_nothing_to_delete(redis) -> None:
    assert await remember_reply(redis, CHAT, "link", [9, 10], ttl=120, now=NOW) == []


async def test_new_call_returns_previous_command_and_reply(redis) -> None:
    await remember_reply(redis, CHAT, "link", [9, 10], ttl=120, now=NOW)
    assert await remember_reply(redis, CHAT, "link", [19, 20], ttl=120, now=NOW) == [9, 10]
    assert await remember_reply(redis, CHAT, "link", [29, 30], ttl=120, now=NOW) == [19, 20]


async def test_old_single_id_format_is_still_deleted(redis) -> None:
    # Значение, записанное прошлой версией бота (только id ответа)
    await redis.set(f"group_reply:last:{CHAT}:link", "10")
    assert await remember_reply(redis, CHAT, "link", [19, 20], ttl=120, now=NOW) == [10]


async def test_previous_call_is_per_command_and_per_chat(redis) -> None:
    await remember_reply(redis, CHAT, "link", [9, 10], ttl=120, now=NOW)
    # Вызов /app не трогает /link, другой чат — тоже
    assert await remember_reply(redis, CHAT, "app", [11, 12], ttl=300, now=NOW) == []
    assert await remember_reply(redis, OTHER_CHAT, "link", [13, 14], ttl=120, now=NOW) == []


async def test_replaced_messages_are_removed_from_timer(redis) -> None:
    await remember_reply(redis, CHAT, "link", [9, 10], ttl=120, now=NOW)
    await remember_reply(redis, CHAT, "link", [19, 20], ttl=120, now=NOW)
    # Старые сообщения уже удалены при замене — второй раз их не удаляем
    claimed = await claim_expired(redis, NOW + 1000)
    assert sorted(claimed[CHAT]) == [19, 20]


async def test_claim_returns_only_expired(redis) -> None:
    await remember_reply(redis, CHAT, "link", [9, 10], ttl=120, now=NOW)
    await remember_reply(redis, CHAT, "app", [11, 12], ttl=300, now=NOW)

    assert await claim_expired(redis, NOW + 60) == {}
    assert sorted((await claim_expired(redis, NOW + 120))[CHAT]) == [9, 10]
    assert sorted((await claim_expired(redis, NOW + 300))[CHAT]) == [11, 12]


async def test_claim_groups_by_chat_and_is_one_time(redis) -> None:
    await remember_reply(redis, CHAT, "link", [10], ttl=120, now=NOW)
    await remember_reply(redis, OTHER_CHAT, "link", [20], ttl=120, now=NOW)

    assert await claim_expired(redis, NOW + 200) == {CHAT: [10], OTHER_CHAT: [20]}
    assert await claim_expired(redis, NOW + 200) == {}


async def test_zero_ttl_disables_timer_but_keeps_replacement(redis) -> None:
    await remember_reply(redis, CHAT, "link", [9, 10], ttl=0, now=NOW)
    assert await redis.zcard(EXPIRE_KEY) == 0
    assert await remember_reply(redis, CHAT, "link", [19, 20], ttl=0, now=NOW) == [9, 10]


async def test_empty_ids_do_nothing(redis) -> None:
    assert await remember_reply(redis, CHAT, "link", [], ttl=120, now=NOW) == []
    assert await redis.zcard(EXPIRE_KEY) == 0


async def test_claim_respects_limit(redis) -> None:
    for message_id in range(5):
        await remember_reply(redis, CHAT, f"cmd{message_id}", [message_id], ttl=1, now=NOW)

    first = await claim_expired(redis, NOW + 10, limit=3)
    rest = await claim_expired(redis, NOW + 10, limit=3)
    assert len(first[CHAT]) == 3
    assert len(rest[CHAT]) == 2
