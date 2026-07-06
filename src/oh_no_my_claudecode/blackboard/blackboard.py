"""Pure, testable core for the ``onmc blackboard`` shared-memory coordination board.

A blackboard is a shared **append-only** channel for a swarm: units post
findings/claims/warnings/questions (and a terminal "done") so other units
(and humans) can read what's already known instead of working blind. It is
purely additive — it does not change how swarm units execute; it's an
opt-in coordination channel + reader.

Storage is one JSON object per line at
``.onmc/swarm/<swarm-id>/blackboard.jsonl`` — the same append-only,
line-delimited convention used elsewhere in onmc (e.g. receipts).

Everything here is pure and path-based: no clock reads, no randomness. The
command layer supplies ``ts`` (see :mod:`oh_no_my_claudecode.blackboard.commands`)
so this module stays trivially testable and deterministic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Valid ``kind`` values for a blackboard entry. ``finding`` is the default —
#: most posts are "here's what I observed" rather than a claim/warning/question.
VALID_KINDS = ("finding", "claim", "warning", "question", "done")

DEFAULT_KIND = "finding"


class InvalidEntryError(ValueError):
    """Raised when an entry's ``kind`` is not one of :data:`VALID_KINDS`."""


@dataclass(frozen=True)
class BoardEntry:
    """One immutable line of the blackboard.

    Parameters
    ----------
    ts:
        Unix timestamp (seconds) supplied by the command layer at post time.
    unit_id:
        The swarm unit (or human) that posted the entry.
    kind:
        One of :data:`VALID_KINDS`.
    note:
        Free-text body of the post.
    """

    ts: float
    unit_id: str
    kind: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict (used for both the ``.jsonl`` line and ``--json``)."""
        return {"ts": self.ts, "unit_id": self.unit_id, "kind": self.kind, "note": self.note}


def _validate_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        msg = f"invalid kind {kind!r}; must be one of {', '.join(VALID_KINDS)}"
        raise InvalidEntryError(msg)


def append_entry(board_path: Path, entry: BoardEntry) -> None:
    """Append *entry* to the board at *board_path* as one JSON line.

    Creates parent directories and the file itself as needed. Never rewrites
    or reorders existing lines — strictly append-only, matching how the file
    is meant to accumulate concurrent swarm-unit posts.
    """
    _validate_kind(entry.kind)
    board_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry.to_dict())
    with board_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_board(board_path: Path) -> list[BoardEntry]:
    """Read every entry from *board_path*, in on-disk (append) order.

    Returns an empty list when the file does not exist. Malformed lines are
    skipped rather than raising, so one corrupt line never hides the rest of
    the board from a reader.
    """
    if not board_path.exists():
        return []
    entries: list[BoardEntry] = []
    for raw_line in board_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        try:
            ts = float(data["ts"])
            unit_id = str(data["unit_id"])
            kind = str(data["kind"])
            note = str(data["note"])
        except (KeyError, TypeError, ValueError):
            continue
        if kind not in VALID_KINDS:
            continue
        entries.append(BoardEntry(ts=ts, unit_id=unit_id, kind=kind, note=note))
    return entries


def filter_entries(
    entries: list[BoardEntry],
    *,
    kind: str | None = None,
    unit_id: str | None = None,
) -> list[BoardEntry]:
    """Return the subset of *entries* matching optional ``kind``/``unit_id`` filters.

    Order is preserved (callers pass already-ordered entries from :func:`read_board`).
    """
    result = entries
    if kind is not None:
        result = [e for e in result if e.kind == kind]
    if unit_id is not None:
        result = [e for e in result if e.unit_id == unit_id]
    return result


def render_board(entries: list[BoardEntry]) -> str:
    """Render *entries* as a human-readable board: a small header + one line per entry.

    Header carries the entry count and the number of distinct posting units.
    An empty board renders an honest "no posts yet" message instead of a bare
    header, so a human never mistakes a fresh board for a broken one.
    """
    if not entries:
        return "Blackboard is empty — units haven't posted yet."

    distinct_units = len({e.unit_id for e in entries})
    suffix = "y" if len(entries) == 1 else "ies"
    header = f"{len(entries)} entr{suffix} · {distinct_units} unit(s)"
    lines = [header, ""]
    for e in entries:
        lines.append(f"{_format_ts(e.ts)} · {e.unit_id} · {e.kind} · {e.note}")
    return "\n".join(lines)


def _format_ts(ts: float) -> str:
    """Format a unix timestamp as UTC ``YYYY-MM-DD HH:MM:SS`` for display.

    Kept as a tiny pure helper (not a clock read) — it only formats a value
    the caller already has.
    """
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
