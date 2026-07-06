"""Pure narrative builder for the ``onmc postmortem`` command.

A "postmortem" turns a completed swarm's manifest + unit receipts into a
readable, deterministic recap: how many units ran, how many verified, how long
it took, and a per-unit account of what happened. Every fact is read straight
off the manifest (:mod:`oh_no_my_claudecode.missioncontrol.dashboard`) and the
receipt each unit points at (:class:`~oh_no_my_claudecode.loop.receipt.RunReceipt`
dicts, same shape :mod:`oh_no_my_claudecode.ledger` and
:mod:`oh_no_my_claudecode.badge.badge` consume) — there is **no LLM call** and
no randomness anywhere in this module.

Design notes
------------
- :func:`build_postmortem` is pure: it takes an already-built
  :class:`~oh_no_my_claudecode.missioncontrol.dashboard.DashboardModel` (plus an
  injectable per-unit receipt reader) and returns a :class:`Postmortem`
  dataclass. It never touches the filesystem itself — the command layer wires
  up the real reads via :mod:`oh_no_my_claudecode.missioncontrol.dashboard`.
- Missing/partial data never crashes anything: a unit without a receipt gets a
  "no receipt recorded" narration line instead of an exception.
- :func:`render_text` is the only place prose is assembled, so the wording is
  reviewable/testable in one spot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from oh_no_my_claudecode.missioncontrol.dashboard import DashboardModel, UnitStatus

#: Iteration count at/above which a verified unit is called out as "high-iteration"
#: in the honest summary — it converged, but it took real effort to get there.
HIGH_ITERATION_THRESHOLD = 5


@dataclass(frozen=True)
class UnitNarrative:
    """One unit's postmortem line, plus the raw facts it was built from.

    Fields
    ------
    unit_id:
        The unit key from the manifest (e.g. ``"unit-0000"``).
    goal:
        Truncated goal text as stored in the manifest.
    state:
        Lifecycle state from the manifest (``done``/``failed``/``aborted``/...).
    verified:
        The unit's ``verified`` flag; ``None`` when never recorded.
    iterations:
        Iteration count from the receipt; ``None`` when no receipt was read.
    wall_seconds:
        Wall-clock seconds from the receipt; ``None`` when no receipt was read.
    stop_reason:
        The receipt's ``stop_reason``; ``None`` when no receipt was read.
    git_tree_sha:
        The receipt's ``git_tree_sha``; ``None`` when no receipt was read.
    error:
        Manifest error message for a failed unit; ``None`` otherwise.
    has_receipt:
        True when a receipt dict was actually read for this unit.
    line:
        The rendered one-line narration for this unit.
    """

    unit_id: str
    goal: str
    state: str
    verified: bool | None
    iterations: int | None
    wall_seconds: float | None
    stop_reason: str | None
    git_tree_sha: str | None
    error: str | None
    has_receipt: bool
    line: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "goal": self.goal,
            "state": self.state,
            "verified": self.verified,
            "iterations": self.iterations,
            "wall_seconds": self.wall_seconds,
            "stop_reason": self.stop_reason,
            "git_tree_sha": self.git_tree_sha,
            "error": self.error,
            "has_receipt": self.has_receipt,
            "line": self.line,
        }


@dataclass(frozen=True)
class Postmortem:
    """A full structured postmortem for one swarm run.

    Fields
    ------
    swarm_id:
        The swarm identifier.
    exists:
        False when no manifest was found for the swarm — callers render a
        graceful "not found" message rather than an empty report.
    mode / agent / concurrency / started_at:
        Swarm-level metadata mirrored from the manifest (``None`` when absent).
    total:
        Total unit count.
    verified_count:
        Units with ``verified is True``.
    failed_count:
        Units in the ``failed`` or ``aborted`` lifecycle state.
    total_wall_seconds:
        Sum of ``wall_seconds`` across units that carried a receipt (0.0 when
        none did).
    units:
        Per-unit :class:`UnitNarrative`, in manifest (sorted unit-id) order.
    went_well:
        Honest, evidence-based observations about what worked.
    needs_attention:
        Honest, evidence-based observations about what didn't (failed units,
        high-iteration units, missing receipts). Empty when nothing stands out.
    """

    swarm_id: str
    exists: bool
    mode: str | None = None
    agent: str | None = None
    concurrency: int | None = None
    started_at: str | None = None
    total: int = 0
    verified_count: int = 0
    failed_count: int = 0
    total_wall_seconds: float = 0.0
    units: list[UnitNarrative] = field(default_factory=list)
    went_well: list[str] = field(default_factory=list)
    needs_attention: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "swarm_id": self.swarm_id,
            "exists": self.exists,
            "mode": self.mode,
            "agent": self.agent,
            "concurrency": self.concurrency,
            "started_at": self.started_at,
            "total": self.total,
            "verified_count": self.verified_count,
            "failed_count": self.failed_count,
            "total_wall_seconds": self.total_wall_seconds,
            "units": [u.to_dict() for u in self.units],
            "went_well": self.went_well,
            "needs_attention": self.needs_attention,
        }


#: Injectable receipt reader: given a manifest unit dict, return the parsed
#: receipt dict (or None when unreadable/missing). Command layer supplies the
#: real filesystem-backed reader; tests inject an in-memory lookup.
ReceiptReader = Any  # Callable[[dict[str, Any]], dict[str, Any] | None]


def _fmt_seconds(seconds: float) -> str:
    """Render a wall-clock duration compactly (``"42s"`` or ``"3m12s"``)."""
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    return f"{minutes}m{secs:02d}s"


def _unit_line(unit: UnitStatus, receipt: dict[str, Any] | None) -> UnitNarrative:
    """Build one unit's :class:`UnitNarrative` from its status + receipt."""
    goal = unit.goal or "(no goal recorded)"

    if receipt is None:
        state_word = {
            "done": "finished",
            "failed": "failed",
            "aborted": "was aborted",
            "running": "is still running",
            "pending": "has not started",
            "queued": "is queued",
        }.get(unit.state, unit.state)
        suffix = f" — {unit.error}" if unit.state == "failed" and unit.error else ""
        line = f"{unit.unit_id}: {goal} — {state_word}, no receipt recorded{suffix}"
        return UnitNarrative(
            unit_id=unit.unit_id,
            goal=goal,
            state=unit.state,
            verified=unit.verified,
            iterations=None,
            wall_seconds=None,
            stop_reason=None,
            git_tree_sha=None,
            error=unit.error,
            has_receipt=False,
            line=line,
        )

    verified = bool(receipt.get("verified", False))
    iterations_raw = receipt.get("iterations")
    iterations = int(iterations_raw) if isinstance(iterations_raw, int) else None
    wall_raw = receipt.get("wall_seconds")
    wall_seconds = float(wall_raw) if isinstance(wall_raw, int | float) else None
    stop_reason = receipt.get("stop_reason")
    stop_reason = str(stop_reason) if stop_reason is not None else None
    git_tree_sha = receipt.get("git_tree_sha")
    git_tree_sha = str(git_tree_sha) if git_tree_sha is not None else None

    iter_part = (
        f"{iterations} iteration(s)"
        if iterations is not None
        else "an unknown number of iterations"
    )
    wall_part = _fmt_seconds(wall_seconds) if wall_seconds is not None else "an unknown time"
    verb = "verified" if verified else "did not verify"
    reason_part = f", stopped: {stop_reason}" if stop_reason else ""

    line = f"{unit.unit_id}: {goal} — {verb} in {iter_part} over {wall_part}{reason_part}"

    return UnitNarrative(
        unit_id=unit.unit_id,
        goal=goal,
        state=unit.state,
        verified=verified,
        iterations=iterations,
        wall_seconds=wall_seconds,
        stop_reason=stop_reason,
        git_tree_sha=git_tree_sha,
        error=unit.error,
        has_receipt=True,
        line=line,
    )


def _build_went_well(units: list[UnitNarrative]) -> list[str]:
    """Derive honest "what went well" observations from unit narratives."""
    out: list[str] = []
    verified = [u for u in units if u.verified is True]
    if verified:
        low_iter = [
            u
            for u in verified
            if u.iterations is not None and u.iterations < HIGH_ITERATION_THRESHOLD
        ]
        low_iter_note = (
            f", {len(low_iter)} of them in under {HIGH_ITERATION_THRESHOLD} iterations"
            if low_iter
            else ""
        )
        out.append(f"{len(verified)}/{len(units)} unit(s) verified{low_iter_note}")
    fast_units = [u for u in verified if u.wall_seconds is not None]
    if fast_units:
        wall_total = sum(u.wall_seconds for u in fast_units if u.wall_seconds is not None)
        avg_wall = wall_total / len(fast_units)
        out.append(f"average wall time for verified units: {_fmt_seconds(avg_wall)}")
    return out


def _build_needs_attention(units: list[UnitNarrative]) -> list[str]:
    """Derive honest "what needs attention" observations from unit narratives."""
    out: list[str] = []

    failed = [u for u in units if u.state in ("failed", "aborted") or u.verified is False]
    if failed:
        names = ", ".join(u.unit_id for u in failed[:5])
        more = f" (+{len(failed) - 5} more)" if len(failed) > 5 else ""
        out.append(f"{len(failed)} unit(s) did not verify: {names}{more}")

    high_iter = [
        u
        for u in units
        if u.verified is True
        and u.iterations is not None
        and u.iterations >= HIGH_ITERATION_THRESHOLD
    ]
    if high_iter:
        names = ", ".join(u.unit_id for u in high_iter[:5])
        more = f" (+{len(high_iter) - 5} more)" if len(high_iter) > 5 else ""
        out.append(
            f"{len(high_iter)} unit(s) verified but needed >= {HIGH_ITERATION_THRESHOLD} "
            f"iterations: {names}{more}"
        )

    missing_receipt = [u for u in units if not u.has_receipt]
    if missing_receipt:
        names = ", ".join(u.unit_id for u in missing_receipt[:5])
        more = f" (+{len(missing_receipt) - 5} more)" if len(missing_receipt) > 5 else ""
        out.append(f"{len(missing_receipt)} unit(s) have no receipt recorded: {names}{more}")

    return out


def build_postmortem(
    model: DashboardModel,
    receipt_reader: ReceiptReader,
) -> Postmortem:
    """Build a :class:`Postmortem` from a dashboard model + a receipt reader.

    Parameters
    ----------
    model:
        A :class:`~oh_no_my_claudecode.missioncontrol.dashboard.DashboardModel`
        already built for the target swarm (``exists=False`` is handled
        gracefully — an empty postmortem is returned).
    receipt_reader:
        A callable ``(unit: UnitStatus) -> dict | None`` that resolves a unit's
        receipt to a plain dict (or ``None`` when unreadable/missing). The
        command layer supplies a filesystem-backed reader; tests inject an
        in-memory lookup — this function performs no I/O itself.

    Returns
    -------
    Postmortem
        Deterministic given the same model + receipt data. Never raises for
        missing/partial data.
    """
    if not model.exists:
        return Postmortem(swarm_id=model.swarm_id, exists=False)

    units: list[UnitNarrative] = []
    total_wall = 0.0
    for unit in model.units:
        receipt = receipt_reader(unit)
        narrative = _unit_line(unit, receipt)
        units.append(narrative)
        if narrative.wall_seconds is not None:
            total_wall += narrative.wall_seconds

    failed_count = sum(1 for u in units if u.state in ("failed", "aborted"))

    return Postmortem(
        swarm_id=model.swarm_id,
        exists=True,
        mode=model.mode,
        agent=model.agent,
        concurrency=model.concurrency,
        started_at=model.started_at,
        total=model.total,
        verified_count=model.verified_count,
        failed_count=failed_count,
        total_wall_seconds=round(total_wall, 3),
        units=units,
        went_well=_build_went_well(units),
        needs_attention=_build_needs_attention(units),
    )


def render_text(pm: Postmortem) -> str:
    """Render a :class:`Postmortem` as a deterministic English narrative.

    No LLM call — plain string assembly from the structured facts. Missing
    data renders as an explicit "not found" message rather than an empty page.
    """
    if not pm.exists:
        return (
            f"No swarm found with id {pm.swarm_id}. Run `onmc missioncontrol --all` to list swarms."
        )

    lines: list[str] = []
    lines.append(f"Postmortem — swarm {pm.swarm_id}")
    meta_bits = [
        f"mode: {pm.mode or '?'}",
        f"agent: {pm.agent or '?'}",
        f"concurrency: {pm.concurrency if pm.concurrency is not None else '?'}",
        f"started: {pm.started_at or '?'}",
    ]
    lines.append("  " + "  ·  ".join(meta_bits))
    lines.append("")

    if pm.total == 0:
        lines.append("No units recorded for this swarm.")
        return "\n".join(lines)

    lines.append(
        f"Overview: {pm.total} unit(s), {pm.verified_count} verified, "
        f"{pm.failed_count} failed, total wall time {_fmt_seconds(pm.total_wall_seconds)}."
    )
    lines.append("")

    lines.append("Per-unit:")
    for unit in pm.units:
        lines.append(f"  - {unit.line}")
    lines.append("")

    lines.append("Summary:")
    if pm.went_well:
        lines.append("  What went well:")
        for note in pm.went_well:
            lines.append(f"    - {note}")
    if pm.needs_attention:
        lines.append("  What needs attention:")
        for note in pm.needs_attention:
            lines.append(f"    - {note}")
    if not pm.went_well and not pm.needs_attention:
        lines.append("  Nothing notable to report.")

    return "\n".join(lines)


__all__ = [
    "HIGH_ITERATION_THRESHOLD",
    "Postmortem",
    "ReceiptReader",
    "UnitNarrative",
    "build_postmortem",
    "render_text",
]
