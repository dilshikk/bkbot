"""
Чистая логика проверки и выбора зеркал (без БД и сети) — легко тестировать.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar
from urllib.parse import urlsplit


class MirrorLike(Protocol):
    id: int
    priority: int
    is_active: bool
    is_healthy: bool
    is_deleted: bool


M = TypeVar("M", bound=MirrorLike)


def status_ok(code: int, *, allow_403: bool) -> bool:
    """2xx/3xx — сайт работает. 403 — по настройке (Cloudflare часто так отвечает ботам)."""
    if 200 <= code < 400:
        return True
    return allow_403 and code == 403


def site_host(url: str) -> str:
    """Домен без www и без точки в конце."""
    if "://" not in url:
        url = "http://" + url
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def same_site(original_url: str, final_url: str) -> bool:
    """
    True, если после редиректов мы остались на том же сайте
    (тот же домен или его поддомен). Редирект на чужой домен —
    обычно заглушка провайдера о блокировке.
    """
    a, b = site_host(original_url), site_host(final_url)
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def needs_switch(links: Iterable[MirrorLike]) -> bool:
    """
    Переключать нужно, только если активные зеркала есть, но все упали.
    Если админ сам выключил все зеркала — ничего не включаем.
    """
    active = [link for link in links if link.is_active and not link.is_deleted]
    return bool(active) and not any(link.is_healthy for link in active)


def pick_replacement(links: Iterable[M]) -> M | None:
    """
    Следующее рабочее зеркало вместо упавшего активного:
    не удалено, не активно, здорово. Выше приоритет — лучше,
    при равном приоритете — более старое (меньший id).
    """
    candidates = [
        link for link in links
        if not link.is_deleted and not link.is_active and link.is_healthy
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda link: (-link.priority, link.id))
