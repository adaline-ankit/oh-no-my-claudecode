"""M8 — temporal validity: staleness is a time problem, not a similarity problem.

Borrowed from the temporal-KG memory line (Graphiti's crack): a memory carries
a validity interval instead of being true forever. Expired memories stop
loading — without being deleted, because evidence is never destroyed — and
"what did we believe at time T" stays answerable.

Composes in front of any recall surface (skill router, hierarchy, hosted
store): filter first, route what survives.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ValidityWindow:
    """When a memory is believed true. ``valid_until_ms=None`` = still open."""

    valid_from_ms: int
    valid_until_ms: int | None = None

    def __post_init__(self) -> None:
        if self.valid_until_ms is not None and self.valid_until_ms < self.valid_from_ms:
            raise ValueError("valid_until_ms precedes valid_from_ms")

    def active_at(self, now_ms: int) -> bool:
        if now_ms < self.valid_from_ms:
            return False
        return self.valid_until_ms is None or now_ms < self.valid_until_ms

    def to_dict(self) -> dict[str, object]:
        return {"valid_from_ms": self.valid_from_ms, "valid_until_ms": self.valid_until_ms}


def filter_active(
    items: Mapping[str, str],
    windows: Mapping[str, ValidityWindow],
    *,
    now_ms: int,
) -> dict[str, str]:
    """Drop expired/not-yet-valid items before recall.

    Fail-open on missing windows by design: an unwindowed memory behaves as
    always-valid (windows are an *additional* restriction, not a new
    obligation on every existing memory). Superseding a fact = closing its
    window and writing the successor with a fresh one.
    """
    return {
        key: value
        for key, value in items.items()
        if key not in windows or windows[key].active_at(now_ms)
    }


def close_window(window: ValidityWindow, *, at_ms: int) -> ValidityWindow:
    """Supersede: close an open window at *at_ms* (idempotent if already closed earlier)."""
    if window.valid_until_ms is not None and window.valid_until_ms <= at_ms:
        return window
    return ValidityWindow(window.valid_from_ms, at_ms)


__all__ = ["ValidityWindow", "close_window", "filter_active"]
