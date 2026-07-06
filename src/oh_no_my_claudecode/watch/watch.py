"""Pure, testable frame builder + renderer for ``onmc watch``.

``onmc watch`` is the terminal-native complement to the web ``onmc ui`` — a
continuously-refreshing live view of what active swarms are doing *right
now*.  It is distinct from ``onmc missioncontrol``, which renders a
**one-shot** snapshot of a single named swarm: ``watch`` re-renders a summary
across **all** swarms on an interval, entirely from the command layer.

This module contains zero I/O beyond reading already-loaded swarm state: it
reuses :func:`oh_no_my_claudecode.missioncontrol.build_dashboard` and
:func:`oh_no_my_claudecode.missioncontrol.list_swarm_ids` for the actual
manifest/receipt reads, and only adds pure aggregation + rendering on top.
The refreshing loop (the only side-effecting, time-based part) lives
exclusively in :mod:`oh_no_my_claudecode.watch.commands`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.missioncontrol.dashboard import (
    DashboardModel,
    build_dashboard,
    list_swarm_ids,
)

# A swarm is considered "active" (worth showing in the live view) when it has
# at least one unit that has not reached a terminal state yet.  Once every
# unit is done/failed/aborted the swarm is still shown for one frame is not
# required by this feature — watch is scoped to units currently in flight.
_TERMINAL_STATES = frozenset({"done", "failed", "aborted"})

# How many of the most recent unit goals to surface per swarm in the frame —
# keeps the terminal view compact when a swarm has many units.
_MAX_RECENT_GOALS = 3


@dataclass
class SwarmFrame:
    """Aggregated, read-only view of one swarm for a single watch frame."""

    swarm_id: str
    total: int
    running: int
    queued: int
    pending: int
    done: int
    failed: int
    aborted: int
    verified_count: int
    recent_goals: list[str] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        """True when at least one unit has not reached a terminal state."""
        return (self.running + self.queued + self.pending) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "swarm_id": self.swarm_id,
            "total": self.total,
            "running": self.running,
            "queued": self.queued,
            "pending": self.pending,
            "done": self.done,
            "failed": self.failed,
            "aborted": self.aborted,
            "verified_count": self.verified_count,
            "recent_goals": list(self.recent_goals),
        }


@dataclass
class WatchFrame:
    """One rendered instant of the live watch view — a pure snapshot."""

    swarms: list[SwarmFrame] = field(default_factory=list)

    @property
    def active_count(self) -> int:
        return sum(1 for s in self.swarms if s.is_active)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_count": self.active_count,
            "swarms": [s.to_dict() for s in self.swarms],
        }


def _swarm_frame_from_model(model: DashboardModel) -> SwarmFrame:
    """Reduce a :class:`DashboardModel` down to the compact watch summary."""
    counts = model.state_counts
    # Recent goals: prefer units still in flight (running, then queued, then
    # pending) so the frame highlights what's happening *now*, not stale
    # completed work. Falls back to any unit's goal when nothing is in flight.
    in_flight = [u for u in model.units if u.state not in _TERMINAL_STATES]
    ordered = in_flight if in_flight else list(model.units)
    recent_goals = [u.goal for u in ordered[:_MAX_RECENT_GOALS] if u.goal]

    return SwarmFrame(
        swarm_id=model.swarm_id,
        total=model.total,
        running=counts.get("running", 0),
        queued=counts.get("queued", 0),
        pending=counts.get("pending", 0),
        done=counts.get("done", 0),
        failed=counts.get("failed", 0),
        aborted=counts.get("aborted", 0),
        verified_count=model.verified_count,
        recent_goals=recent_goals,
    )


def build_frame(state_dir: Path, *, active_only: bool = True) -> WatchFrame:
    """Build a :class:`WatchFrame` across every swarm under ``state_dir``.

    Parameters
    ----------
    state_dir:
        The repo's swarm base — ``<repo>/.onmc/swarm``.
    active_only:
        When True (the default), swarms where every unit has already reached
        a terminal state are dropped from the frame — the live view is about
        what's happening *now*.  Pass False to see every swarm with a
        manifest, regardless of completion.

    Returns
    -------
    WatchFrame
        Never raises for missing/empty state — an empty ``.onmc/swarm`` (or a
        repo with no swarms at all) yields a frame with an empty swarm list.
    """
    frames: list[SwarmFrame] = []
    for swarm_id in list_swarm_ids(state_dir):
        model = build_dashboard(state_dir, swarm_id)
        if not model.exists:
            continue
        frame = _swarm_frame_from_model(model)
        if active_only and not frame.is_active:
            continue
        frames.append(frame)
    return WatchFrame(swarms=frames)


def render_frame(frame: WatchFrame) -> str:
    """Render a :class:`WatchFrame` to a plain-text string (no ANSI/Rich).

    Kept dependency-free so it can be used both as the ``--json``-less plain
    fallback and unit-tested without a terminal.  The command layer may still
    layer Rich coloring on top when rendering to an interactive terminal.
    """
    lines: list[str] = []
    if not frame.swarms:
        lines.append("No active swarms.")
        return "\n".join(lines)

    lines.append(f"{len(frame.swarms)} active swarm(s):")
    lines.append("")
    for s in frame.swarms:
        lines.append(
            f"[{s.swarm_id}]  running={s.running} queued={s.queued} "
            f"pending={s.pending} done={s.done} failed={s.failed}  "
            f"verified={s.verified_count}/{s.total}"
        )
        for goal in s.recent_goals:
            trimmed = goal if len(goal) <= 70 else goal[:67] + "..."
            lines.append(f"    - {trimmed}")
        lines.append("")

    return "\n".join(lines).rstrip("\n")
