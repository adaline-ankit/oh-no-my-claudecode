"""Pure merge-queue state machine for ``onmc refinery``.

This module is **pure** — no imports of git, gh, subprocess, network, or any
other I/O.  All functions return new values; nothing is mutated in place.
File persistence (reading/writing ``queue.json``) is handled here via an
injectable directory path so tests can redirect to a ``tmp_path``.

Data model
----------
``Queue`` is a list of ``QueueEntry`` records sorted by (priority desc, pos
asc) — highest-priority entries first; within the same priority, earlier
enqueue order wins (FIFO).

State machine
-------------
Each ``QueueEntry`` can be in one of four states::

    QUEUED   — waiting to be processed (initial state)
    TESTING  — head was rebased; now awaiting CI result
    MERGED   — successfully merged (terminal)
    KICKED   — failed with a reason (terminal); removed from active queue

The ``next_action`` function maps a CI observation to an ``Action`` the
driver should perform on the current head:

    CiStatus  →  Action
    ─────────────────────
    BEHIND    →  REBASE   (update-branch first, then wait for CI)
    PENDING   →  WAIT     (still running — poll again later)
    GREEN     →  MERGE    (all gates pass)
    RED       →  KICK     (CI failed; kick with reason)
    BLOCKED   →  KICK     (merge conflict; kick with reason)
    DONE      →  DONE     (queue is empty)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

REFINERY_SUBDIR = ".onmc/refinery"
QUEUE_FILENAME = "queue.json"


class PRState(StrEnum):
    """Lifecycle state of a single PR entry in the queue."""

    QUEUED = "queued"
    TESTING = "testing"
    MERGED = "merged"
    KICKED = "kicked"


class CiStatus(StrEnum):
    """Observed CI state returned by the gh adapter."""

    BEHIND = "behind"    # PR branch is behind main — needs rebase
    PENDING = "pending"  # CI still running
    GREEN = "green"      # all gates pass (quality + CodeQL)
    RED = "red"          # quality or CodeQL failed
    BLOCKED = "blocked"  # merge conflict / cannot rebase cleanly


class Action(StrEnum):
    """Instruction the driver should execute for the current queue head."""

    WAIT = "wait"    # CI pending — come back later
    REBASE = "rebase"  # update-branch (rebase onto main)
    MERGE = "merge"  # CI green — merge now
    KICK = "kick"    # CI failed / conflict — kick with reason
    DONE = "done"    # queue is empty — nothing to do


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class QueueEntry:
    """A single PR in the merge queue."""

    pr: int
    priority: int = 0
    state: PRState = PRState.QUEUED
    reason: str = ""
    enqueued_at: float = field(default_factory=time.time)
    position: int = 0  # insertion-order index, used for stable sort


@dataclass
class Queue:
    """The full refinery queue state — a pure value."""

    entries: list[QueueEntry] = field(default_factory=list)
    version: int = 0  # incremented on every mutation


# ---------------------------------------------------------------------------
# Pure operations
# ---------------------------------------------------------------------------


def enqueue(queue: Queue, pr: int, *, priority: int = 0) -> Queue:
    """Return a new Queue with *pr* added (or its priority updated).

    If *pr* is already in the queue (in any state), its priority is updated
    and it stays in place — no duplicate insertion.
    """
    for entry in queue.entries:
        if entry.pr == pr:
            # Update priority in-place on a copy
            new_entry = QueueEntry(
                pr=entry.pr,
                priority=priority,
                state=entry.state,
                reason=entry.reason,
                enqueued_at=entry.enqueued_at,
                position=entry.position,
            )
            new_entries = [new_entry if e.pr == pr else e for e in queue.entries]
            return Queue(entries=_sorted(new_entries), version=queue.version + 1)

    position = len(queue.entries)
    new_entry = QueueEntry(pr=pr, priority=priority, position=position)
    new_entries = queue.entries + [new_entry]
    return Queue(entries=_sorted(new_entries), version=queue.version + 1)


def drop(queue: Queue, pr: int) -> Queue:
    """Return a new Queue with *pr* removed (any state)."""
    new_entries = [e for e in queue.entries if e.pr != pr]
    return Queue(entries=new_entries, version=queue.version + 1)


def clear(queue: Queue) -> Queue:
    """Return an empty Queue."""
    return Queue(entries=[], version=queue.version + 1)


def active_entries(queue: Queue) -> list[QueueEntry]:
    """Return entries that are not yet in a terminal state (MERGED or KICKED)."""
    return [e for e in queue.entries if e.state not in (PRState.MERGED, PRState.KICKED)]


def head(queue: Queue) -> QueueEntry | None:
    """Return the current queue head (highest-priority, earliest enqueue), or None."""
    active = active_entries(queue)
    return active[0] if active else None


def set_state(
    queue: Queue,
    pr: int,
    state: PRState,
    *,
    reason: str = "",
) -> Queue:
    """Return a new Queue with *pr*'s state set to *state*."""
    new_entries = [
        QueueEntry(
            pr=e.pr,
            priority=e.priority,
            state=state,
            reason=reason,
            enqueued_at=e.enqueued_at,
            position=e.position,
        )
        if e.pr == pr
        else e
        for e in queue.entries
    ]
    return Queue(entries=new_entries, version=queue.version + 1)


# ---------------------------------------------------------------------------
# State-machine logic
# ---------------------------------------------------------------------------


def next_action(ci_status: CiStatus) -> Action:
    """Map an observed ``CiStatus`` to the ``Action`` the driver should take.

    Pure function — no side effects.
    """
    mapping: dict[CiStatus, Action] = {
        CiStatus.BEHIND: Action.REBASE,
        CiStatus.PENDING: Action.WAIT,
        CiStatus.GREEN: Action.MERGE,
        CiStatus.RED: Action.KICK,
        CiStatus.BLOCKED: Action.KICK,
    }
    return mapping[ci_status]


# ---------------------------------------------------------------------------
# File persistence (injectable directory)
# ---------------------------------------------------------------------------


def _queue_path(queue_dir: Path) -> Path:
    return queue_dir / QUEUE_FILENAME


def load_queue(queue_dir: Path) -> Queue:
    """Load the queue from *queue_dir*/queue.json.

    Returns an empty Queue if the file does not exist or cannot be parsed.
    """
    path = _queue_path(queue_dir)
    if not path.exists():
        return Queue()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = [
            QueueEntry(
                pr=e["pr"],
                priority=e.get("priority", 0),
                state=PRState(e.get("state", PRState.QUEUED.value)),
                reason=e.get("reason", ""),
                enqueued_at=e.get("enqueued_at", 0.0),
                position=e.get("position", i),
            )
            for i, e in enumerate(raw.get("entries", []))
        ]
        return Queue(entries=entries, version=raw.get("version", 0))
    except Exception:  # noqa: BLE001 - corrupt file → start fresh
        return Queue()


def save_queue(queue: Queue, queue_dir: Path) -> None:
    """Persist *queue* to *queue_dir*/queue.json atomically."""
    queue_dir.mkdir(parents=True, exist_ok=True)
    path = _queue_path(queue_dir)
    data = {
        "version": queue.version,
        "entries": [
            {
                "pr": e.pr,
                "priority": e.priority,
                "state": e.state.value,
                "reason": e.reason,
                "enqueued_at": e.enqueued_at,
                "position": e.position,
            }
            for e in queue.entries
        ],
    }
    # Atomic write via a temp file
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sorted(entries: list[QueueEntry]) -> list[QueueEntry]:
    """Sort entries: highest priority first, ties broken by insertion position."""
    return sorted(entries, key=lambda e: (-e.priority, e.position))
