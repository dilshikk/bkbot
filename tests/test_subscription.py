import enum

import pytest

from bot.utils.subscription import is_channel_member


class Status(str, enum.Enum):
    MEMBER = "member"
    LEFT = "left"


@pytest.mark.parametrize(
    ("status", "is_member", "expected"),
    [
        ("creator", None, True),
        ("administrator", None, True),
        ("member", None, True),
        ("left", None, False),
        ("kicked", None, False),
        ("restricted", True, True),
        ("restricted", False, False),
        ("restricted", None, False),
        (Status.MEMBER, None, True),
        (Status.LEFT, None, False),
    ],
)
def test_is_channel_member(status, is_member, expected) -> None:
    assert is_channel_member(status, is_member) is expected
