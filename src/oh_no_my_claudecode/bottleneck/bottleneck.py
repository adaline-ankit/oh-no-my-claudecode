"""Pure, deterministic bottleneck analysis for the ``onmc bottleneck`` command.

``bottleneck`` answers *what is slowing your agents down* — distinct from
:mod:`oh_no_my_claudecode.cost` (money) and
:mod:`oh_no_my_claudecode.flywheel` (which model wins on verified-rate). This
module looks at the same run-receipt schema
(:mod:`oh_no_my_claudecode.ledger.accounting`, schema_version "2") that
``onmc loop`` / ``onmc swarm`` write to ``.agent-memory/receipts/`` and folds
them into: slowest goals (by total and average wall-clock), slowest models
(by average wall-clock and average iterations), outlier runs (unusually slow
or unusually iteration-heavy), and a short "time sinks" summary.

Design notes
------------
- **Pure core**: :func:`build_bottleneck` takes an already-loaded list of
  receipt dicts — it never touches the clock or the filesystem. The command
  layer (:mod:`oh_no_my_claudecode.bottleneck.commands`) is responsible for
  loading receipts.
- **Deterministic**: same input list -> identical :class:`BottleneckReport`,
  identical rendered text. Goal/model breakdowns are sorted by total wall
  descending then name ascending; outliers are sorted by wall descending then
  goal ascending. Ties never reorder between runs.
- **Never fabricates**: a receipt with ``wall_seconds`` missing or not a
  finite non-negative number is excluded from all aggregates and tallied in
  ``excluded_count`` rather than silently dropped or coerced to zero.
- **Outlier detection is a fixed, explainable rule**: a run is flagged when
  its ``wall_seconds`` or ``iterations`` exceeds the 90th percentile *or* is
  more than 2x the median across all included runs. Percentile and median use
  a simple deterministic nearest-rank method — no external stats dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: Default number of entries to show per ranked list.
DEFAULT_TOP = 5

#: Outlier threshold: flag a run whose metric exceeds this percentile.
_OUTLIER_PERCENTILE = 90

#: Outlier threshold: flag a run whose metric exceeds this multiple of the median.
_OUTLIER_MEDIAN_MULTIPLE = 2.0


@dataclass(frozen=True)
class GoalStat:
    """Wall-clock aggregate for one goal string."""

    goal: str
    runs: int
    total_wall_seconds: float
    avg_wall_seconds: float


@dataclass(frozen=True)
class ModelStat:
    """Wall-clock + iteration aggregate for one model."""

    model: str
    runs: int
    avg_wall_seconds: float
    avg_iterations: float


@dataclass(frozen=True)
class OutlierRun:
    """A single run flagged as unusually slow or iteration-heavy."""

    goal: str
    model: str
    wall_seconds: float
    iterations: int | None
    verified: bool
    reason: str


@dataclass(frozen=True)
class BottleneckReport:
    """The full slowdown analysis over a set of run receipts.

    Fields
    ------
    total_runs:
        Number of receipts with a usable ``wall_seconds`` included in the
        analysis.
    excluded_count:
        Receipts skipped because ``wall_seconds`` was missing, non-numeric,
        negative, or non-finite.
    total_wall_seconds:
        Sum of ``wall_seconds`` across all included runs.
    by_goal:
        Per-goal breakdown, sorted by ``total_wall_seconds`` descending then
        ``goal`` ascending, truncated to ``top`` entries.
    by_model:
        Per-model breakdown, sorted by ``avg_wall_seconds`` descending then
        ``model`` ascending, truncated to ``top`` entries.
    outliers:
        Runs whose wall time or iteration count exceeds the p90 or 2x-median
        threshold, sorted by ``wall_seconds`` descending then ``goal``
        ascending, truncated to ``top`` entries.
    time_sink_summary:
        Human-readable one-liners such as "goal X = 40% of total wall",
        covering the top goal(s) that dominate total time. Empty when there
        is nothing to report.
    notes:
        Honest, human-readable caveats.
    """

    total_runs: int
    excluded_count: int
    total_wall_seconds: float
    by_goal: list[GoalStat] = field(default_factory=list)
    by_model: list[ModelStat] = field(default_factory=list)
    outliers: list[OutlierRun] = field(default_factory=list)
    time_sink_summary: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers (pure)
# ---------------------------------------------------------------------------


def _coerce_wall_seconds(raw: Any) -> float | None:
    """Return a finite, non-negative float, or ``None`` if unusable."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _coerce_iterations(raw: Any) -> int | None:
    """Return a non-negative int, or ``None`` if unusable."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def _coerce_receipt(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return a normalised view of one receipt, or ``None`` to skip it."""
    if not isinstance(data, dict):
        return None
    wall = _coerce_wall_seconds(data.get("wall_seconds"))
    if wall is None:
        return None
    return {
        "goal": str(data.get("goal") or "unknown"),
        "model": str(data.get("model") or "unknown"),
        "wall_seconds": wall,
        "iterations": _coerce_iterations(data.get("iterations")),
        "verified": bool(data.get("verified", False)),
    }


def _percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile of *values* (already may be unsorted).

    Deterministic, no external dependency. ``values`` must be non-empty.
    """
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = math.ceil((pct / 100.0) * len(ordered))
    rank = max(1, min(len(ordered), rank))
    return ordered[rank - 1]


def _median(values: list[float]) -> float:
    """Deterministic median of *values*. ``values`` must be non-empty."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_bottleneck(
    receipts: list[dict[str, Any]],
    *,
    top: int = DEFAULT_TOP,
) -> BottleneckReport:
    """Fold *receipts* into a :class:`BottleneckReport`.

    Args:
        receipts: Raw receipt dicts (any order), typically from
            :func:`oh_no_my_claudecode.ledger.accounting.load_receipts`.
        top: Number of entries to keep per ranked list (default
            :data:`DEFAULT_TOP`). Values less than 1 are clamped to 1.

    Returns:
        A :class:`BottleneckReport` with deterministic ordering.
    """
    top_n = max(1, top)
    notes: list[str] = []

    included: list[dict[str, Any]] = []
    excluded_count = 0
    for raw in receipts:
        coerced = _coerce_receipt(raw) if isinstance(raw, dict) else None
        if coerced is None:
            excluded_count += 1
            continue
        included.append(coerced)

    if excluded_count:
        plural = "" if excluded_count == 1 else "s"
        notes.append(
            f"{excluded_count} receipt{plural} had no usable wall_seconds and "
            "were excluded from the analysis"
        )

    total_runs = len(included)
    total_wall_seconds = round(sum(r["wall_seconds"] for r in included), 4)

    if total_runs == 0:
        notes.append("No run receipts with timing data were found.")
        return BottleneckReport(
            total_runs=0,
            excluded_count=excluded_count,
            total_wall_seconds=0.0,
            notes=notes,
        )

    # --- by goal ---
    goal_buckets: dict[str, dict[str, Any]] = {}
    for r in included:
        gb = goal_buckets.setdefault(r["goal"], {"runs": 0, "total_wall": 0.0})
        gb["runs"] += 1
        gb["total_wall"] += r["wall_seconds"]

    by_goal = [
        GoalStat(
            goal=name,
            runs=b["runs"],
            total_wall_seconds=round(b["total_wall"], 4),
            avg_wall_seconds=round(b["total_wall"] / b["runs"], 4),
        )
        for name, b in goal_buckets.items()
    ]
    by_goal.sort(key=lambda g: (-g.total_wall_seconds, g.goal))

    # --- by model ---
    model_buckets: dict[str, dict[str, Any]] = {}
    for r in included:
        mb = model_buckets.setdefault(
            r["model"], {"runs": 0, "total_wall": 0.0, "iter_sum": 0, "iter_count": 0}
        )
        mb["runs"] += 1
        mb["total_wall"] += r["wall_seconds"]
        if r["iterations"] is not None:
            mb["iter_sum"] += r["iterations"]
            mb["iter_count"] += 1

    by_model = [
        ModelStat(
            model=name,
            runs=b["runs"],
            avg_wall_seconds=round(b["total_wall"] / b["runs"], 4),
            avg_iterations=(
                round(b["iter_sum"] / b["iter_count"], 2) if b["iter_count"] > 0 else 0.0
            ),
        )
        for name, b in model_buckets.items()
    ]
    by_model.sort(key=lambda m: (-m.avg_wall_seconds, m.model))

    # --- outliers ---
    wall_values = [r["wall_seconds"] for r in included]
    iter_values = [float(r["iterations"]) for r in included if r["iterations"] is not None]

    wall_p90 = _percentile(wall_values, _OUTLIER_PERCENTILE)
    wall_median = _median(wall_values)
    iter_p90 = _percentile(iter_values, _OUTLIER_PERCENTILE) if iter_values else None
    iter_median = _median(iter_values) if iter_values else None

    outliers: list[OutlierRun] = []
    for r in included:
        reasons: list[str] = []
        wall = r["wall_seconds"]
        if wall > wall_p90:
            reasons.append(f"wall {wall:.1f}s > p90 ({wall_p90:.1f}s)")
        elif wall_median > 0 and wall > wall_median * _OUTLIER_MEDIAN_MULTIPLE:
            reasons.append(f"wall {wall:.1f}s > 2x median ({wall_median:.1f}s)")

        iterations = r["iterations"]
        if iterations is not None and iter_p90 is not None and iter_median is not None:
            iter_f = float(iterations)
            if iter_f > iter_p90:
                reasons.append(f"iterations {iterations} > p90 ({iter_p90:.1f})")
            elif iter_median > 0 and iter_f > iter_median * _OUTLIER_MEDIAN_MULTIPLE:
                reasons.append(f"iterations {iterations} > 2x median ({iter_median:.1f})")

        if reasons:
            outliers.append(
                OutlierRun(
                    goal=r["goal"],
                    model=r["model"],
                    wall_seconds=wall,
                    iterations=iterations,
                    verified=r["verified"],
                    reason="; ".join(reasons),
                )
            )

    outliers.sort(key=lambda o: (-o.wall_seconds, o.goal))

    # --- time sink summary ---
    time_sink_summary: list[str] = []
    if total_wall_seconds > 0:
        for g in by_goal[:top_n]:
            pct = (g.total_wall_seconds / total_wall_seconds) * 100.0
            if pct >= 1.0:
                time_sink_summary.append(
                    f'goal "{g.goal}" = {pct:.0f}% of total wall time '
                    f"({g.total_wall_seconds:.1f}s across {g.runs} run"
                    f"{'s' if g.runs != 1 else ''})"
                )

    return BottleneckReport(
        total_runs=total_runs,
        excluded_count=excluded_count,
        total_wall_seconds=total_wall_seconds,
        by_goal=by_goal[:top_n],
        by_model=by_model[:top_n],
        outliers=outliers[:top_n],
        time_sink_summary=time_sink_summary,
        notes=notes,
    )


def render_text(report: BottleneckReport) -> str:
    """Render *report* as deterministic, readable plain-text English."""
    lines: list[str] = ["Agent bottlenecks", ""]

    for note in report.notes:
        lines.append(f"note: {note}")
    if report.notes:
        lines.append("")

    if report.total_runs == 0:
        lines.append("No agent runs with timing data found.")
        return "\n".join(lines)

    lines.append(
        f"{report.total_runs} run{'s' if report.total_runs != 1 else ''} analysed, "
        f"{report.total_wall_seconds:.1f}s total wall time."
    )
    lines.append("")

    lines.append("Slowest goals (by total wall time):")
    for g in report.by_goal:
        lines.append(
            f'  - "{g.goal}": {g.total_wall_seconds:.1f}s total, '
            f"{g.avg_wall_seconds:.1f}s avg over {g.runs} run{'s' if g.runs != 1 else ''}"
        )
    lines.append("")

    lines.append("Slowest models (by avg wall time):")
    for m in report.by_model:
        lines.append(
            f"  - {m.model}: {m.avg_wall_seconds:.1f}s avg wall, "
            f"{m.avg_iterations:.1f} avg iterations over {m.runs} run"
            f"{'s' if m.runs != 1 else ''}"
        )
    lines.append("")

    if report.outliers:
        lines.append("Outlier runs:")
        for o in report.outliers:
            verified_str = "verified" if o.verified else "unverified"
            iter_str = (
                f"{o.iterations} iterations" if o.iterations is not None else "iterations n/a"
            )
            lines.append(
                f'  - "{o.goal}" ({o.model}): {o.wall_seconds:.1f}s, {iter_str}, '
                f"{verified_str} — {o.reason}"
            )
    else:
        lines.append("Outlier runs: none.")
    lines.append("")

    if report.time_sink_summary:
        lines.append("Time sinks:")
        for line in report.time_sink_summary:
            lines.append(f"  - {line}")
    else:
        lines.append("Time sinks: none stand out (spend is evenly spread).")

    return "\n".join(lines)


__all__ = [
    "DEFAULT_TOP",
    "BottleneckReport",
    "GoalStat",
    "ModelStat",
    "OutlierRun",
    "build_bottleneck",
    "render_text",
]
