import pytest
from fakeredis import aioredis as fake_aioredis

from bot.utils.group_commands import acquire_cooldown, parse_group_command

BOT = "MirrorBot"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/app", "app"),
        ("/link", "link"),
        ("/link please", "link"),
        ("/app@MirrorBot", "app"),
        ("/link@mirrorbot", "link"),      # username без учёта регистра
        ("/app@OtherBot", None),          # команда другому боту
        ("/start", None),
        ("/menu@MirrorBot", None),
        ("/APP", None),                   # как aiogram Command: регистр важен
        ("/application", None),
        ("hello /link", None),
        ("link", None),
        ("/", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_group_command(text: str | None, expected: str | None) -> None:
    assert parse_group_command(text, BOT) == expected


def test_mention_rejected_when_bot_username_unknown() -> None:
    assert parse_group_command("/app@MirrorBot", None) is None
    assert parse_group_command("/app", None) == "app"


@pytest.fixture
async def redis():
    client = fake_aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_cooldown_blocks_repeat_in_same_chat(redis) -> None:
    assert await acquire_cooldown(redis, -100, "link", 30) is True
    assert await acquire_cooldown(redis, -100, "link", 30) is False


async def test_cooldown_is_per_command_and_per_chat(redis) -> None:
    assert await acquire_cooldown(redis, -100, "link", 30) is True
    assert await acquire_cooldown(redis, -100, "app", 30) is True
    assert await acquire_cooldown(redis, -200, "link", 30) is True


async def test_zero_cooldown_never_blocks(redis) -> None:
    for _ in range(3):
        assert await acquire_cooldown(redis, -100, "link", 0) is True
