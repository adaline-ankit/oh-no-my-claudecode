"""Pure, deterministic agent-activity digest for the ``onmc standup`` command.

A "standup" answers *what did my agents do* over a recent window — distinct
from :mod:`oh_no_my_claudecode.digest` (a memory changelog) and
:mod:`oh_no_my_claudecode.timeline` (a memory narrative). ``standup`` looks at
**run receipts** (:mod:`oh_no_my_claudecode.ledger.accounting`), the same
schema-version-"2" JSON files ``onmc loop`` / ``onmc swarm`` write to
``.agent-memory/receipts/``, and summarises them into a daily-standup-style
report: how many runs happened, how many verified, what they cost, which
models did the work, which goals were worked on, and anything that stands out.

Design notes
------------
- **Pure core**: :func:`build_standup` takes an already-loaded list of receipt
  dicts plus an injected ``now`` — it never touches the clock or the
  filesystem. The command layer (:mod:`oh_no_my_claudecode.standup.commands`)
  is responsible for loading receipts and supplying ``now``.
- **Deterministic**: same input list + same ``now`` → identical
  :class:`StandupReport`, identical rendered text. Model/goal breakdowns are
  sorted by count descending, then name ascending, so ties never reorder
  between runs.
- **Never fabricates**: a receipt with an unparsable/missing timestamp is
  excluded from the window (we cannot prove it falls inside it) and counted in
  a note rather than silently dropped.
- **Honest costs**: a receipt with ``cost_usd is None`` contributes nothing to
  the total and is tallied separately, mirroring
  :mod:`oh_no_my_claudecode.ledger.accounting`'s honesty constraint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

#: Iteration count at/above which a verified run is flagged as "notable" —
#: mirrors postmortem.HIGH_ITERATION_THRESHOLD so the two features agree on
#: what "took real effort" means.
HIGH_ITERATION_THRESHOLD = 5

#: Default window when no --since is given.
DEFAULT_SINCE = "24h"

#: Number of top goals surfaced in the report.
_TOP_GOALS_LIMIT = 5

#: Number of notable items surfaced in the report.
_NOTABLE_LIMIT = 10


@dataclass(frozen=True)
class ModelBreakdown:
    """Run counts + cost/wall totals for one model."""

    model: str
    runs: int
    verified: int
    cost_usd: float
    cost_unknown_count: int
    wall_seconds: float


@dataclass(frozen=True)
class GoalBreakdown:
    """Run count for one distinct goal string."""

    goal: str
    runs: int
    verified: int


@dataclass(frozen=True)
class NotableRun:
    """A run worth calling out: a failure or a high-iteration success."""

    goal: str
    model: str
    reason: str
    iterations: int | None
    stop_reason: str | None


@dataclass(frozen=True)
class StandupReport:
    """The full standup: window bounds, totals, breakdowns, notable items."""

    since: datetime
    now: datetime
    since_label: str
    total_runs: int
    verified_count: int
    failed_count: int
    success_rate: float
    total_cost_usd: float
    cost_unknown_count: int
    total_wall_seconds: float
    by_model: list[ModelBreakdown] = field(default_factory=list)
    top_goals: list[GoalBreakdown] = field(default_factory=list)
    notable: list[NotableRun] = field(default_factory=list)
    excluded_undated_count: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers (pure)
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 UTC string; return None on failure or empty input."""
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _receipt_when(data: dict[str, Any]) -> datetime | None:
    """Return a receipt's timestamp (``ended_at`` preferred, then ``started_at``)."""
    return _parse_iso(str(data.get("ended_at") or "")) or _parse_iso(
        str(data.get("started_at") or "")
    )


def parse_since(token: str, now: datetime) -> datetime | None:
    """Parse a ``--since`` token into an aware UTC cutoff, or ``None`` if invalid.

    Accepts a relative window (``24h``, ``7d``) or an ISO date/datetime
    (``2026-07-01``). Uses only simple string ops — no regex — to stay clear of
    ReDoS.
    """
    stripped = token.strip()
    if not stripped:
        return None
    now_utc = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)

    if len(stripped) >= 2 and stripped[-1] in ("h", "H") and stripped[:-1].isdigit():
        return now_utc - timedelta(hours=int(stripped[:-1]))
    if len(stripped) >= 2 and stripped[-1] in ("d", "D") and stripped[:-1].isdigit():
        return now_utc - timedelta(days=int(stripped[:-1]))

    parsed = _parse_iso(stripped)
    if parsed is not None:
        return parsed
    try:
        return datetime.fromisoformat(stripped).replace(tzinfo=UTC)
    except ValueError:
        return None


def _coerce_receipt(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return a normalised view of one receipt, or ``None`` to skip unusable input."""
    if not isinstance(data, dict):
        return None
    try:
        verified = bool(data.get("verified", False))
        wall = float(data.get("wall_seconds", 0.0) or 0.0)
        cost_raw = data.get("cost_usd")
        cost: float | None = float(cost_raw) if cost_raw is not None else None
        model = str(data.get("model") or "unknown")
        goal = str(data.get("goal") or "(no goal recorded)")
        stop_reason = data.get("stop_reason")
        iterations_raw = data.get("iterations")
        iterations = int(iterations_raw) if iterations_raw is not None else None
    except (TypeError, ValueError):
        return None
    return {
        "verified": verified,
        "wall_seconds": wall,
        "cost_usd": cost,
        "model": model,
        "goal": goal,
        "stop_reason": str(stop_reason) if stop_reason is not None else None,
        "iterations": iterations,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_standup(
    receipts: list[dict[str, Any]],
    *,
    now: datetime,
    since: str = DEFAULT_SINCE,
) -> StandupReport:
    """Fold *receipts* into a :class:`StandupReport` covering the window since *since*.

    Args:
        receipts: Raw receipt dicts (any order), typically from
            :func:`oh_no_my_claudecode.ledger.accounting.load_receipts`.
        now: Reference instant for resolving a relative ``since`` (e.g.
            ``24h``). Never read from the clock inside this function.
        since: A relative window (``24h``, ``7d``) or an ISO date/datetime.
            Defaults to ``"24h"``.

    Returns:
        A :class:`StandupReport` with deterministic ordering: model and goal
        breakdowns sorted by run count descending, then name ascending;
        notable items sorted by goal, then model.
    """
    notes: list[str] = []
    now_utc = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)

    cutoff = parse_since(since, now_utc)
    since_label = since
    if cutoff is None:
        notes.append(f"could not parse --since {since!r}; defaulting to {DEFAULT_SINCE}")
        cutoff = parse_since(DEFAULT_SINCE, now_utc)
        since_label = DEFAULT_SINCE
    if cutoff is None:  # pragma: no cover - DEFAULT_SINCE always parses
        cutoff = now_utc

    included: list[dict[str, Any]] = []
    excluded_undated = 0
    for raw in receipts:
        coerced = _coerce_receipt(raw) if isinstance(raw, dict) else None
        if coerced is None:
            continue
        when = _receipt_when(raw) if isinstance(raw, dict) else None
        if when is None:
            excluded_undated += 1
            continue
        if when < cutoff:
            continue
        included.append(coerced)

    if excluded_undated:
        plural = "" if excluded_undated == 1 else "s"
        notes.append(
            f"{excluded_undated} receipt{plural} had no usable timestamp and "
            "were excluded from the window"
        )

    total_runs = len(included)
    verified_count = sum(1 for r in included if r["verified"])
    failed_count = total_runs - verified_count
    success_rate = (verified_count / total_runs) if total_runs else 0.0

    total_cost_usd = 0.0
    cost_unknown_count = 0
    total_wall_seconds = 0.0
    model_buckets: dict[str, dict[str, Any]] = {}
    goal_buckets: dict[str, dict[str, Any]] = {}
    notable: list[NotableRun] = []

    for r in included:
        total_wall_seconds += r["wall_seconds"]
        if r["cost_usd"] is None:
            cost_unknown_count += 1
        else:
            total_cost_usd += r["cost_usd"]

        mb = model_buckets.setdefault(
            r["model"],
            {
                "runs": 0,
                "verified": 0,
                "cost_usd": 0.0,
                "cost_unknown_count": 0,
                "wall_seconds": 0.0,
            },
        )
        mb["runs"] += 1
        mb["wall_seconds"] += r["wall_seconds"]
        if r["verified"]:
            mb["verified"] += 1
        if r["cost_usd"] is None:
            mb["cost_unknown_count"] += 1
        else:
            mb["cost_usd"] += r["cost_usd"]

        gb = goal_buckets.setdefault(r["goal"], {"runs": 0, "verified": 0})
        gb["runs"] += 1
        if r["verified"]:
            gb["verified"] += 1

        if not r["verified"]:
            notable.append(
                NotableRun(
                    goal=r["goal"],
                    model=r["model"],
                    reason="failed",
                    iterations=r["iterations"],
                    stop_reason=r["stop_reason"],
                )
            )
        elif r["iterations"] is not None and r["iterations"] >= HIGH_ITERATION_THRESHOLD:
            notable.append(
                NotableRun(
                    goal=r["goal"],
                    model=r["model"],
                    reason="high-iteration",
                    iterations=r["iterations"],
                    stop_reason=r["stop_reason"],
                )
            )

    by_model = sorted(
        (
            ModelBreakdown(
                model=name,
                runs=bucket["runs"],
                verified=bucket["verified"],
                cost_usd=bucket["cost_usd"],
                cost_unknown_count=bucket["cost_unknown_count"],
                wall_seconds=bucket["wall_seconds"],
            )
            for name, bucket in model_buckets.items()
        ),
        key=lambda m: (-m.runs, m.model),
    )

    top_goals = sorted(
        (
            GoalBreakdown(goal=name, runs=bucket["runs"], verified=bucket["verified"])
            for name, bucket in goal_buckets.items()
        ),
        key=lambda g: (-g.runs, g.goal),
    )[:_TOP_GOALS_LIMIT]

    notable.sort(key=lambda n: (n.goal, n.model))
    notable = notable[:_NOTABLE_LIMIT]

    return StandupReport(
        since=cutoff,
        now=now_utc,
        since_label=since_label,
        total_runs=total_runs,
        verified_count=verified_count,
        failed_count=failed_count,
        success_rate=success_rate,
        total_cost_usd=total_cost_usd,
        cost_unknown_count=cost_unknown_count,
        total_wall_seconds=total_wall_seconds,
        by_model=by_model,
        top_goals=top_goals,
        notable=notable,
        excluded_undated_count=excluded_undated,
        notes=notes,
    )


def render_text(report: StandupReport) -> str:
    """Render *report* as deterministic, readable plain-text English."""
    lines: list[str] = ["Agent standup", ""]

    for note in report.notes:
        lines.append(f"note: {note}")
    if report.notes:
        lines.append("")

    if report.total_runs == 0:
        lines.append(f"No agent runs in the last {report.since_label}.")
        return "\n".join(lines)

    cost_str = f"${report.total_cost_usd:.2f}" if report.cost_unknown_count == 0 else (
        f"${report.total_cost_usd:.2f} (+{report.cost_unknown_count} run"
        f"{'s' if report.cost_unknown_count != 1 else ''} with unknown cost)"
    )
    wall_minutes = report.total_wall_seconds / 60.0

    lines.append(
        f"Since {report.since_label}: {report.total_runs} run"
        f"{'s' if report.total_runs != 1 else ''}, "
        f"{report.verified_count} verified, {report.failed_count} failed "
        f"({report.success_rate * 100:.0f}% success rate)."
    )
    lines.append(f"Cost: {cost_str}. Wall time: {wall_minutes:.1f} min.")
    lines.append("")

    lines.append("By model:")
    for m in report.by_model:
        m_cost = f"${m.cost_usd:.2f}" if m.cost_unknown_count == 0 else (
            f"${m.cost_usd:.2f} (+{m.cost_unknown_count} unknown)"
        )
        lines.append(
            f"  - {m.model}: {m.runs} run{'s' if m.runs != 1 else ''}, "
            f"{m.verified} verified, {m_cost}, {m.wall_seconds / 60.0:.1f} min"
        )
    lines.append("")

    lines.append("Top goals:")
    for g in report.top_goals:
        run_word = "run" if g.runs == 1 else "runs"
        lines.append(f"  - {g.goal} ({g.runs} {run_word}, {g.verified} verified)")
    lines.append("")

    if report.notable:
        lines.append("Notable:")
        for n in report.notable:
            if n.reason == "failed":
                detail = (
                    f"stop_reason={n.stop_reason}" if n.stop_reason else "no stop_reason recorded"
                )
                lines.append(f"  - FAILED: {n.goal} ({n.model}, {detail})")
            else:
                lines.append(
                    f"  - HIGH-ITERATION: {n.goal} ({n.model}, {n.iterations} iterations)"
                )
    else:
        lines.append("Notable: nothing stands out — all runs verified cleanly.")

    return "\n".join(lines)


__all__ = [
    "DEFAULT_SINCE",
    "HIGH_ITERATION_THRESHOLD",
    "GoalBreakdown",
    "ModelBreakdown",
    "NotableRun",
    "StandupReport",
    "build_standup",
    "parse_since",
    "render_text",
]
