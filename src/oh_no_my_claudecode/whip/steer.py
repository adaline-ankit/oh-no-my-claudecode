"""Pure, deterministic core for the ``whip`` steering + reward store.

The ``whip`` feature is a durable *steering-directive queue* and *reward-signal
store* that lets a human (or an outer agent) steer a running Claude Code
session and record whether its work was praised or corrected.

Since onmc is a CLI rather than a live daemon, persistence is entirely
file-backed:

- **Directives** — a JSONL queue at ``.onmc/whip/pending.jsonl``.  Each line
  is a JSON object with ``{kind, msg, ts}`` where ``kind`` is either
  ``"nudge"`` (gentle) or ``"redirect"`` (priority course-correction).
  :func:`consume` reads-and-deletes atomically (rewrites the file minus the
  consumed entries), returning directives in priority order: all
  ``"redirect"`` entries first, then ``"nudge"`` entries, each sub-group in
  FIFO insertion order.

- **Reward signals** — appended to ``.onmc/whip/rewards.jsonl``.  Each line
  is a JSON object with ``{kind, goal, agent, reason, ts}`` where ``kind``
  is ``"treat"`` (positive) or ``"crack"`` (negative/correction).  The
  schema is intentionally compatible with the flywheel receipt schema so
  future flywheel analysis can consume reward signals alongside run receipts.

All functions are pure over in-memory data and accept an injectable
``whip_dir: Path`` and ``ts: str`` argument so tests can run without touching
the real filesystem or the real clock.  Only :func:`enqueue`,
:func:`consume`, :func:`clear`, :func:`record_signal`, and :func:`tally`
perform file I/O.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Sub-directory under the repo root where whip state is persisted.
WHIP_SUBDIR = Path(".onmc") / "whip"

#: JSONL file holding queued steering directives.
PENDING_FILE = "pending.jsonl"

#: JSONL file holding reward signals.
REWARDS_FILE = "rewards.jsonl"

#: Directive priority order — lower index → higher priority in :func:`consume`.
_DIRECTIVE_PRIORITY: dict[str, int] = {
    "redirect": 0,
    "nudge": 1,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, skipping malformed lines. Returns [] when absent."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if isinstance(entry, dict):
                out.append(entry)
        except json.JSONDecodeError:
            pass
    return out


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON line to *path*, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Overwrite *path* with *records* as JSONL, or remove it when empty."""
    if not records:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Directive queue
# ---------------------------------------------------------------------------


def enqueue(
    kind: str,
    msg: str,
    *,
    whip_dir: Path,
    ts: str,
) -> dict[str, Any]:
    """Append a steering directive to the pending queue.

    Parameters
    ----------
    kind:
        ``"nudge"`` for a gentle steer; ``"redirect"`` for a hard
        course-correction (rendered with higher priority by :func:`consume`).
    msg:
        The directive message text.
    whip_dir:
        Directory where ``pending.jsonl`` lives (injectable for tests).
    ts:
        ISO-8601 timestamp string (caller-supplied so the core is deterministic).

    Returns
    -------
    dict[str, Any]
        The record that was appended.
    """
    if kind not in {"nudge", "redirect"}:
        raise ValueError(f"kind must be 'nudge' or 'redirect', got {kind!r}")
    record: dict[str, Any] = {"kind": kind, "msg": msg, "ts": ts}
    _append_jsonl(whip_dir / PENDING_FILE, record)
    return record


def consume(*, whip_dir: Path) -> list[dict[str, Any]]:
    """Read and remove all queued directives, returning them in priority order.

    Priority: all ``"redirect"`` entries first (FIFO within that group),
    then all ``"nudge"`` entries (FIFO within that group).  This ensures a
    hard course-correction is always surfaced ahead of a gentle nudge
    regardless of insertion order.

    Atomically rewrites (or removes) the pending file so each directive is
    delivered exactly once.

    Returns
    -------
    list[dict[str, Any]]
        Directives in priority order; empty list when nothing is queued.
    """
    path = whip_dir / PENDING_FILE
    records = _read_jsonl(path)
    if not records:
        return []
    _write_jsonl(path, [])
    records.sort(key=lambda r: _DIRECTIVE_PRIORITY.get(str(r.get("kind", "")), 99))
    return records


def clear(*, whip_dir: Path) -> int:
    """Discard all queued directives without returning them.

    Returns
    -------
    int
        Number of directives that were discarded.
    """
    path = whip_dir / PENDING_FILE
    records = _read_jsonl(path)
    _write_jsonl(path, [])
    return len(records)


def pending(*, whip_dir: Path) -> list[dict[str, Any]]:
    """Return queued directives in priority order WITHOUT consuming them.

    Unlike :func:`consume`, this does not modify the pending file.

    Returns
    -------
    list[dict[str, Any]]
        Directives in priority order; empty list when nothing is queued.
    """
    records = _read_jsonl(whip_dir / PENDING_FILE)
    records.sort(key=lambda r: _DIRECTIVE_PRIORITY.get(str(r.get("kind", "")), 99))
    return records


# ---------------------------------------------------------------------------
# Reward signals
# ---------------------------------------------------------------------------


def record_signal(
    kind: str,
    *,
    goal: str,
    agent: str,
    reason: str,
    whip_dir: Path,
    ts: str,
) -> dict[str, Any]:
    """Append a reward signal to the rewards store.

    Parameters
    ----------
    kind:
        ``"treat"`` for a positive reward; ``"crack"`` for a negative
        reward (correction).
    goal:
        The current goal or task description (used for grouping in :func:`tally`).
    agent:
        Agent identifier (e.g. ``"claude"`` or the running swarm id).
    reason:
        Optional human-readable rationale (may be an empty string).
    whip_dir:
        Directory where ``rewards.jsonl`` lives (injectable for tests).
    ts:
        ISO-8601 timestamp string (caller-supplied so the core is deterministic).

    Returns
    -------
    dict[str, Any]
        The record that was appended.
    """
    if kind not in {"treat", "crack"}:
        raise ValueError(f"kind must be 'treat' or 'crack', got {kind!r}")
    record: dict[str, Any] = {
        "kind": kind,
        "goal": goal,
        "agent": agent,
        "reason": reason,
        "ts": ts,
    }
    _append_jsonl(whip_dir / REWARDS_FILE, record)
    return record


def tally(*, whip_dir: Path) -> dict[str, Any]:
    """Aggregate reward signals per goal and per agent.

    Returns a deterministic summary dict:

    .. code-block:: json

        {
            "total": 5,
            "treats": 3,
            "cracks": 2,
            "by_goal": {
                "refactor the parser": {"treats": 2, "cracks": 1},
                "add timeout param":   {"treats": 1, "cracks": 1}
            },
            "by_agent": {
                "claude": {"treats": 3, "cracks": 2}
            }
        }

    Corrupt or malformed reward records are skipped silently.
    """
    records = _read_jsonl(whip_dir / REWARDS_FILE)
    total_treats = 0
    total_cracks = 0
    by_goal: dict[str, dict[str, int]] = {}
    by_agent: dict[str, dict[str, int]] = {}

    for rec in records:
        kind = rec.get("kind", "")
        if kind not in {"treat", "crack"}:
            continue
        goal = str(rec.get("goal", "unknown"))
        agent = str(rec.get("agent", "unknown"))

        if kind == "treat":
            total_treats += 1
        else:
            total_cracks += 1

        bucket = "treats" if kind == "treat" else "cracks"
        by_goal.setdefault(goal, {"treats": 0, "cracks": 0})
        by_goal[goal][bucket] += 1

        by_agent.setdefault(agent, {"treats": 0, "cracks": 0})
        by_agent[agent][bucket] += 1

    return {
        "total": total_treats + total_cracks,
        "treats": total_treats,
        "cracks": total_cracks,
        "by_goal": by_goal,
        "by_agent": by_agent,
    }
