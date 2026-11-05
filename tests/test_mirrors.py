from dataclasses import dataclass

import pytest

from bot.utils.mirrors import needs_switch, pick_replacement, same_site, status_ok


@dataclass
class FakeLink:
    id: int
    priority: int = 0
    is_active: bool = False
    is_healthy: bool = True
    is_deleted: bool = False


@pytest.mark.parametrize(
    ("code", "allow_403", "expected"),
    [
        (200, False, True),
        (301, False, True),
        (403, True, True),
        (403, False, False),
        (404, True, False),
        (500, True, False),
    ],
)
def test_status_ok(code: int, allow_403: bool, expected: bool) -> None:
    assert status_ok(code, allow_403=allow_403) is expected


@pytest.mark.parametrize(
    ("original", "final", "expected"),
    [
        ("https://mirror1.com", "https://mirror1.com/home", True),
        ("https://mirror1.com", "https://www.mirror1.com/", True),
        ("https://mirror1.com", "https://ru.mirror1.com/", True),
        ("https://ru.mirror1.com", "https://mirror1.com/", True),
        ("https://MIRROR1.com", "https://mirror1.com.", True),
        # Заглушки провайдеров о блокировке
        ("https://mirror1.com", "http://warning.rt.ru/?id=1", False),
        ("https://mirror1.com", "https://blocked.mts.ru/", False),
        # Похожий, но чужой домен
        ("https://mirror1.com", "https://evilmirror1.com/", False),
        ("https://mirror1.com", "", False),
    ],
)
def test_same_site(original: str, final: str, expected: bool) -> None:
    assert same_site(original, final) is expected


def test_needs_switch_only_when_all_active_are_down() -> None:
    assert needs_switch([FakeLink(1, is_active=True, is_healthy=False)]) is True
    assert needs_switch([FakeLink(1, is_active=True, is_healthy=True)]) is False
    # Админ выключил всё сам — не вмешиваемся
    assert needs_switch([FakeLink(1), FakeLink(2)]) is False
    # Удалённое активное не считается
    assert needs_switch([FakeLink(1, is_active=True, is_healthy=False, is_deleted=True)]) is False


def test_pick_replacement_by_priority_then_id() -> None:
    links = [
        FakeLink(1, priority=10, is_active=True, is_healthy=False),
        FakeLink(2, priority=5),
        FakeLink(3, priority=7),
        FakeLink(4, priority=7),
        FakeLink(5, priority=99, is_healthy=False),
        FakeLink(6, priority=100, is_deleted=True),
    ]
    picked = pick_replacement(links)
    assert picked is not None and picked.id == 3


def test_pick_replacement_none_when_no_healthy() -> None:
    links = [
        FakeLink(1, is_active=True, is_healthy=False),
        FakeLink(2, is_healthy=False),
    ]
    assert pick_replacement(links) is None
