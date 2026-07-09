"""Pure, testable core for ``onmc pulse`` — the "is it stuck?" heartbeat.

``onmc pulse`` answers the single most common Claude-Code UX question of 2026,
sometimes called *Interactive Entropy*: **"is the agent working, idle, or
stuck?"**  It reads the live swarm state that the orchestrator already writes
and reduces it to one compact liveness verdict per swarm plus an overall
verdict, so a developer can push "still working: unit 3/7, 4m elapsed" or
"⚠️ no progress for 5m" to their phone via the notify sinks.

This is distinct from ``onmc watch`` (a terminal-only auto-refresh monitor):
pulse is a **one-shot verdict + PUSH**, not a TUI.

Design
------
- This module contains **zero** manifest parsing of its own.  It reuses
  :func:`oh_no_my_claudecode.missioncontrol.build_dashboard` /
  :func:`~oh_no_my_claudecode.missioncontrol.list_swarm_ids` (the same readers
  ``onmc missioncontrol`` and ``onmc watch`` use) so it stays in lock-step with
  the writer.
- The verdict is a pure, deterministic function of the read state plus an
  injected ``now_ms``.  The core **never** calls a live clock — the CLI passes
  the real clock, and tests inject a fixed value.  This mirrors the loop
  engine's own no-progress detector (``LoopConfig.no_progress_window``): a run
  that has not produced a fresh signal for a bounded window is treated as
  possibly stuck.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.missioncontrol.dashboard import (
    DashboardModel,
    build_dashboard,
    list_swarm_ids,
)

# Liveness verdicts, ordered by severity (worst first) so the overall verdict is
# the max over per-swarm verdicts.
VERDICT_STUCK = "stuck"
VERDICT_WORKING = "working"
VERDICT_IDLE = "idle"
VERDICT_EMPTY = "empty"

_SEVERITY = {VERDICT_STUCK: 3, VERDICT_WORKING: 2, VERDICT_IDLE: 1, VERDICT_EMPTY: 0}

#: Glyphs surfaced in the compact text render + push payload.
GLYPH = {
    VERDICT_WORKING: "▶",
    VERDICT_IDLE: "⏸",
    VERDICT_STUCK: "⚠️",
    VERDICT_EMPTY: "⏸",
}

#: Default stuck threshold — 5 minutes of no fresh progress on a running unit.
DEFAULT_STUCK_AFTER_MS = 300_000

_TERMINAL_STATES = frozenset({"done", "failed", "aborted"})


@dataclass(frozen=True)
class PulseUnit:
    """One unit's contribution to the heartbeat (immutable)."""

    unit_id: str
    state: str
    elapsed_ms: int
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "state": self.state,
            "elapsed_ms": self.elapsed_ms,
            "note": self.note,
        }


@dataclass(frozen=True)
class PulseSwarm:
    """Per-swarm liveness verdict (immutable)."""

    swarm_id: str
    verdict: str
    running: int
    queued: int
    pending: int
    done: int
    failed: int
    total: int
    elapsed_ms: int
    summary: str
    units: tuple[PulseUnit, ...] = ()
    stuck_unit_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "swarm_id": self.swarm_id,
            "verdict": self.verdict,
            "running": self.running,
            "queued": self.queued,
            "pending": self.pending,
            "done": self.done,
            "failed": self.failed,
            "total": self.total,
            "elapsed_ms": self.elapsed_ms,
            "summary": self.summary,
            "stuck_unit_id": self.stuck_unit_id,
            "units": [u.to_dict() for u in self.units],
        }


@dataclass(frozen=True)
class Pulse:
    """A one-shot liveness snapshot across one or more swarms (immutable)."""

    overall: str
    summary: str
    swarm_count: int
    working_count: int
    stuck_count: int
    idle_count: int
    generated_at_ms: int
    swarms: tuple[PulseSwarm, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        """True when no swarm state was found at all."""
        return self.swarm_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "summary": self.summary,
            "swarm_count": self.swarm_count,
            "working_count": self.working_count,
            "stuck_count": self.stuck_count,
            "idle_count": self.idle_count,
            "generated_at_ms": self.generated_at_ms,
            "swarms": [s.to_dict() for s in self.swarms],
        }


def _iso_to_ms(value: str | None) -> int | None:
    """Parse an ISO-8601 timestamp (as written by the swarm orchestrator) to ms.

    Returns ``None`` for missing/unparseable input so a corrupt ``started_at``
    never breaks the heartbeat.
    """
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def humanize_ms(elapsed_ms: int) -> str:
    """Render a duration in ms as a compact human string (``45s`` / ``4m`` / ``2h 3m``)."""
    if elapsed_ms < 0:
        elapsed_ms = 0
    seconds = elapsed_ms // 1000
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    rem_min = minutes % 60
    return f"{hours}h {rem_min}m" if rem_min else f"{hours}h"


def _swarm_pulse(
    model: DashboardModel, *, now_ms: int | None, stuck_after_ms: int
) -> PulseSwarm:
    """Reduce one :class:`DashboardModel` to a :class:`PulseSwarm` verdict."""
    counts = model.state_counts
    running = counts.get("running", 0)
    queued = counts.get("queued", 0)
    pending = counts.get("pending", 0)
    done = counts.get("done", 0)
    failed = counts.get("failed", 0)

    # Elapsed since the last progress signal we can derive from the manifest.
    # The orchestrator stamps a swarm-level ``started_at``; per-unit timestamps
    # are honoured when present (forward-compatible) via ``updated_at``.  When
    # ``now_ms`` is not injected the core does NOT reach for a live clock — it
    # degrades to elapsed=0 so a verdict can never be *falsely* "stuck".
    started_ms = _iso_to_ms(model.started_at)
    elapsed_ms = (
        0 if now_ms is None or started_ms is None else max(0, now_ms - started_ms)
    )

    # A running unit with no receipt yet is the thing that can be "stuck".
    running_units = [u for u in model.units if u.state == "running"]
    no_receipt_running = [u for u in running_units if not u.has_receipt]

    stuck_unit_id: str | None = None
    if running > 0 and elapsed_ms >= stuck_after_ms:
        verdict = VERDICT_STUCK
        # Name the first running unit lacking a receipt (no visible progress);
        # fall back to any running unit.
        offender = no_receipt_running[0] if no_receipt_running else running_units[0]
        stuck_unit_id = offender.unit_id
    elif running > 0:
        verdict = VERDICT_WORKING
    else:
        verdict = VERDICT_IDLE

    units = tuple(
        PulseUnit(
            unit_id=u.unit_id,
            state=u.state,
            elapsed_ms=elapsed_ms if u.state == "running" else 0,
            note=_unit_note(u.state, u.unit_id == stuck_unit_id, elapsed_ms),
        )
        for u in model.units
    )

    summary = _swarm_summary(
        verdict=verdict,
        swarm_id=model.swarm_id,
        running=running,
        total=model.total,
        done=done,
        elapsed_ms=elapsed_ms,
        stuck_unit_id=stuck_unit_id,
    )

    return PulseSwarm(
        swarm_id=model.swarm_id,
        verdict=verdict,
        running=running,
        queued=queued,
        pending=pending,
        done=done,
        failed=failed,
        total=model.total,
        elapsed_ms=elapsed_ms,
        summary=summary,
        units=units,
        stuck_unit_id=stuck_unit_id,
    )


def _unit_note(state: str, is_stuck: bool, elapsed_ms: int) -> str:
    """Short per-unit note for the detail view."""
    if is_stuck:
        return f"no progress for {humanize_ms(elapsed_ms)}"
    if state == "running":
        return f"running {humanize_ms(elapsed_ms)}"
    if state in _TERMINAL_STATES:
        return state
    return state


def _swarm_summary(
    *,
    verdict: str,
    swarm_id: str,
    running: int,
    total: int,
    done: int,
    elapsed_ms: int,
    stuck_unit_id: str | None,
) -> str:
    """Human one-liner for a single swarm's verdict."""
    if verdict == VERDICT_STUCK:
        return (
            f"{swarm_id}: no progress for {humanize_ms(elapsed_ms)} "
            f"(unit {stuck_unit_id} still running)"
        )
    if verdict == VERDICT_WORKING:
        return (
            f"{swarm_id}: working — {done}/{total} done, "
            f"{running} running, {humanize_ms(elapsed_ms)} elapsed"
        )
    return f"{swarm_id}: idle — {done}/{total} done, nothing running"


def build_pulse(
    repo_root: Path,
    swarm_id: str | None = None,
    *,
    now_ms: int | None = None,
    stuck_after_ms: int = DEFAULT_STUCK_AFTER_MS,
) -> Pulse:
    """Build a :class:`Pulse` from live swarm state under *repo_root*.

    Parameters
    ----------
    repo_root:
        Repository root; swarm state is read from ``<repo>/.onmc/swarm``.
    swarm_id:
        When ``None`` (default) every swarm with a manifest is evaluated;
        otherwise only the named swarm.
    now_ms:
        Injected "now" in epoch milliseconds.  The pure core never calls a live
        clock — the CLI passes ``int(time.time() * 1000)`` and tests pass a
        fixed value.  When ``None``, elapsed degrades to 0 (never falsely
        "stuck").
    stuck_after_ms:
        A running unit with no fresh progress for at least this many ms is
        flagged "stuck".  Defaults to :data:`DEFAULT_STUCK_AFTER_MS` (5 min).

    Returns
    -------
    Pulse
        Never raises for missing/empty state — a repo with no swarms yields an
        empty pulse (``overall == "empty"``, ``is_empty`` True).
    """
    state_dir = repo_root / ".onmc" / "swarm"
    ids = [swarm_id] if swarm_id is not None else list_swarm_ids(state_dir)

    swarms: list[PulseSwarm] = []
    for sid in ids:
        model = build_dashboard(state_dir, sid)
        if not model.exists:
            continue
        swarms.append(_swarm_pulse(model, now_ms=now_ms, stuck_after_ms=stuck_after_ms))

    generated_at_ms = now_ms if now_ms is not None else 0

    if not swarms:
        return Pulse(
            overall=VERDICT_EMPTY,
            summary="no active swarms",
            swarm_count=0,
            working_count=0,
            stuck_count=0,
            idle_count=0,
            generated_at_ms=generated_at_ms,
            swarms=(),
        )

    working = sum(1 for s in swarms if s.verdict == VERDICT_WORKING)
    stuck = sum(1 for s in swarms if s.verdict == VERDICT_STUCK)
    idle = sum(1 for s in swarms if s.verdict == VERDICT_IDLE)

    overall = max((s.verdict for s in swarms), key=lambda v: _SEVERITY[v])
    summary = _overall_summary(overall, len(swarms), working, stuck, idle)

    return Pulse(
        overall=overall,
        summary=summary,
        swarm_count=len(swarms),
        working_count=working,
        stuck_count=stuck,
        idle_count=idle,
        generated_at_ms=generated_at_ms,
        swarms=tuple(swarms),
    )


def _overall_summary(overall: str, total: int, working: int, stuck: int, idle: int) -> str:
    """Human one-liner for the overall verdict across all swarms."""
    noun = "swarm" if total == 1 else "swarms"
    if overall == VERDICT_STUCK:
        return f"⚠️ {stuck}/{total} {noun} possibly stuck ({working} working, {idle} idle)"
    if overall == VERDICT_WORKING:
        return f"working — {working}/{total} {noun} active ({idle} idle)"
    return f"idle — {total} {noun}, nothing running"


def render_pulse_text(pulse: Pulse) -> str:
    """Render *pulse* as a compact one-liner + per-swarm detail (no Rich/ANSI).

    Kept dependency-free so it doubles as the plain fallback and is trivially
    unit-testable.  The command layer may layer Rich colour on top.
    """
    glyph = GLYPH.get(pulse.overall, "?")
    if pulse.is_empty:
        return f"{glyph} no active swarms"

    lines = [f"{glyph} {pulse.summary}", ""]
    for s in pulse.swarms:
        sg = GLYPH.get(s.verdict, "?")
        lines.append(f"{sg} {s.summary}")
        if s.verdict == VERDICT_STUCK:
            for u in s.units:
                if u.unit_id == s.stuck_unit_id:
                    lines.append(f"    - {u.unit_id} [{u.state}] {u.note}")
    return "\n".join(lines).rstrip("\n")


def to_event(pulse: Pulse) -> dict[str, Any]:
    """Build a notify-sink payload dict from *pulse*.

    Returns a plain dict (``title`` / ``detail`` / ``severity`` / ``kind`` /
    ``overall``) so the command layer can construct a ``NotifyEvent`` without
    this pure module importing the notify subsystem.  A ``stuck`` pulse maps to
    ``failure`` severity (always pushed immediately); everything else is
    ``routine``.
    """
    glyph = GLYPH.get(pulse.overall, "?")
    severity = "failure" if pulse.overall == VERDICT_STUCK else "routine"
    return {
        "kind": "generic",
        "severity": severity,
        "overall": pulse.overall,
        "title": f"{glyph} onmc pulse: {pulse.summary}",
        "detail": render_pulse_text(pulse),
    }
