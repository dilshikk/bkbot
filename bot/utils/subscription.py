from __future__ import annotations

from typing import Any


def is_channel_member(status: Any, is_member: bool | None = None) -> bool:
    """
    Считается ли участник подписанным на канал.

    - left / kicked — нет;
    - restricted — только если is_member=True (иначе человек не в канале,
      на него просто наложены ограничения);
    - creator / administrator / member — да.
    """
    value = str(getattr(status, "value", status))
    if value in ("left", "kicked"):
        return False
    if value == "restricted":
        return bool(is_member)
    return True
