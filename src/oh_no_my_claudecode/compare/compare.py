"""Pure, testable core for the ``onmc compare`` side-by-side swarm comparison.

``onmc compare <a> <b>`` puts two completed (or in-flight) swarm runs next to
each other so a human can see which run/config did better — units total,
verified count/rate, wall time, cost, average iterations, and models used —
with a per-metric "winner" marker and a one-line verdict.

This is distinct from:

- ``onmc race`` — a model tournament aggregated over *all* receipts.
- ``onmc postmortem`` — a narrative recap of a *single* run.

Design notes
------------
- :func:`build_comparison` is pure: it takes two already-built
  :class:`~oh_no_my_claudecode.missioncontrol.dashboard.DashboardModel`
  instances (plus an injectable per-unit receipt reader, same shape
  :mod:`oh_no_my_claudecode.postmortem.postmortem` uses) and returns a
  :class:`Comparison` dataclass. It performs no I/O itself.
- Deterministic and clock-free: no ``datetime.now()``, no randomness. Given
  the same two models + receipts, the same :class:`Comparison` comes out.
- Missing/partial data degrades gracefully: a run with zero units, an unknown
  swarm id, or receipts with malformed numeric fields never raises — metrics
  simply read as ``None``/0 and the affected comparisons are skipped rather
  than crashing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from oh_no_my_claudecode.missioncontrol.dashboard import DashboardModel

#: Injectable receipt reader: given a manifest unit (UnitStatus-like object),
#: return the parsed receipt dict (or None when unreadable/missing). Mirrors
#: ``oh_no_my_claudecode.postmortem.postmortem.ReceiptReader``.
ReceiptReader = Any


@dataclass(frozen=True)
class RunMetrics:
    """Aggregated metrics for one swarm run, used as one side of a comparison.

    Fields
    ------
    swarm_id:
        The swarm identifier.
    exists:
        False when no manifest was found for the swarm — callers render a
        graceful "not found" message rather than fabricated zeros.
    mode / agent / concurrency / started_at:
        Swarm-level metadata mirrored from the manifest (``None`` when absent).
    total:
        Total unit count.
    verified_count:
        Units with ``verified is True``.
    verified_rate:
        ``verified_count / total`` (0.0 when ``total`` is 0).
    total_wall_seconds:
        Sum of ``wall_seconds`` across units that carried a receipt with a
        numeric ``wall_seconds`` (0.0 when none did).
    avg_wall_seconds:
        ``total_wall_seconds`` divided by the number of units that
        contributed a wall time (``None`` when no unit did).
    total_cost_usd:
        Sum of each unit's ``cost_usd`` (manifest value; falls back to the
        receipt's ``cost_usd`` when the manifest omits it). 0.0 when unknown.
    avg_iterations:
        Mean ``iterations`` across units with a numeric receipt iteration
        count (``None`` when no unit did).
    models_used:
        Sorted, de-duplicated list of non-null ``model`` values seen across
        receipts.
    """

    swarm_id: str
    exists: bool
    mode: str | None = None
    agent: str | None = None
    concurrency: int | None = None
    started_at: str | None = None
    total: int = 0
    verified_count: int = 0
    verified_rate: float = 0.0
    total_wall_seconds: float = 0.0
    avg_wall_seconds: float | None = None
    total_cost_usd: float = 0.0
    avg_iterations: float | None = None
    models_used: list[str] = field(default_factory=list)

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
            "verified_rate": self.verified_rate,
            "total_wall_seconds": self.total_wall_seconds,
            "avg_wall_seconds": self.avg_wall_seconds,
            "total_cost_usd": self.total_cost_usd,
            "avg_iterations": self.avg_iterations,
            "models_used": self.models_used,
        }


#: The metrics compared side-by-side, in display order. Each entry is
#: ``(field_name, label, higher_is_better)``. ``higher_is_better=None`` marks
#: metrics that are informational only (no winner is computed).
_METRIC_SPECS: tuple[tuple[str, str, bool | None], ...] = (
    ("total", "units total", None),
    ("verified_count", "verified count", True),
    ("verified_rate", "verified rate", True),
    ("total_wall_seconds", "total wall time", False),
    ("avg_wall_seconds", "avg wall time/unit", False),
    ("total_cost_usd", "total cost", False),
    ("avg_iterations", "avg iterations", False),
)


@dataclass(frozen=True)
class MetricComparison:
    """One row of the side-by-side table.

    ``winner`` is ``"a"``, ``"b"``, ``"tie"``, or ``None`` (when either side's
    value is missing, or the metric is informational-only).
    """

    field_name: str
    label: str
    value_a: float | int | None
    value_b: float | int | None
    winner: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field_name,
            "label": self.label,
            "value_a": self.value_a,
            "value_b": self.value_b,
            "winner": self.winner,
        }


@dataclass(frozen=True)
class Comparison:
    """A full side-by-side comparison of two swarm runs.

    ``verdict`` is a single honest sentence summarising which run "won" on
    the majority of decidable metrics, or a neutral note when the two are
    tied or too sparse to judge.
    """

    run_a: RunMetrics
    run_b: RunMetrics
    metrics: list[MetricComparison] = field(default_factory=list)
    verdict: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_a": self.run_a.to_dict(),
            "run_b": self.run_b.to_dict(),
            "metrics": [m.to_dict() for m in self.metrics],
            "verdict": self.verdict,
        }


def _extract_receipt_facts(
    receipt: dict[str, Any] | None,
) -> tuple[float | None, int | None, float | None, str | None]:
    """Pull ``(wall_seconds, iterations, cost_usd, model)`` out of a receipt dict.

    Tolerant of missing keys and wrong types (mirrors
    ``postmortem._unit_line``'s defensive coercion) — never raises.
    """
    if receipt is None:
        return None, None, None, None

    wall_raw = receipt.get("wall_seconds")
    wall_seconds = float(wall_raw) if isinstance(wall_raw, int | float) else None

    iter_raw = receipt.get("iterations")
    iterations = (
        int(iter_raw) if isinstance(iter_raw, int) and not isinstance(iter_raw, bool) else None
    )

    cost_raw = receipt.get("cost_usd")
    cost_usd = float(cost_raw) if isinstance(cost_raw, int | float) else None

    model_raw = receipt.get("model")
    model = str(model_raw) if isinstance(model_raw, str) and model_raw else None

    return wall_seconds, iterations, cost_usd, model


def build_run_metrics(model: DashboardModel, receipt_reader: ReceiptReader) -> RunMetrics:
    """Build a :class:`RunMetrics` summary from a dashboard model + receipts.

    Parameters
    ----------
    model:
        A :class:`~oh_no_my_claudecode.missioncontrol.dashboard.DashboardModel`
        already built for the target swarm (``exists=False`` handled
        gracefully — a metrics-empty result is returned).
    receipt_reader:
        A callable ``(unit) -> dict | None`` resolving a unit's receipt; see
        :data:`ReceiptReader`. Performs no I/O itself — the command layer
        supplies the real reader.
    """
    if not model.exists:
        return RunMetrics(swarm_id=model.swarm_id, exists=False)

    total_wall = 0.0
    wall_samples = 0
    total_cost = 0.0
    iter_sum = 0
    iter_samples = 0
    models: set[str] = set()

    for unit in model.units:
        receipt = receipt_reader(unit)
        wall_seconds, iterations, receipt_cost, model_name = _extract_receipt_facts(receipt)

        if wall_seconds is not None:
            total_wall += wall_seconds
            wall_samples += 1
        if iterations is not None:
            iter_sum += iterations
            iter_samples += 1
        if model_name is not None:
            models.add(model_name)

        # Prefer the manifest's cost_usd (always present, defaults to 0.0);
        # fall back to the receipt's cost_usd only when the manifest carried
        # no usable figure (matches how missioncontrol treats cost as
        # manifest-authoritative while receipts carry the same field too).
        unit_cost = unit.cost_usd if unit.cost_usd else (receipt_cost or 0.0)
        total_cost += unit_cost

    total = model.total
    verified_rate = model.verified_count / total if total else 0.0
    avg_wall = total_wall / wall_samples if wall_samples else None
    avg_iterations = iter_sum / iter_samples if iter_samples else None

    return RunMetrics(
        swarm_id=model.swarm_id,
        exists=True,
        mode=model.mode,
        agent=model.agent,
        concurrency=model.concurrency,
        started_at=model.started_at,
        total=total,
        verified_count=model.verified_count,
        verified_rate=verified_rate,
        total_wall_seconds=round(total_wall, 3),
        avg_wall_seconds=round(avg_wall, 3) if avg_wall is not None else None,
        total_cost_usd=round(total_cost, 6),
        avg_iterations=round(avg_iterations, 3) if avg_iterations is not None else None,
        models_used=sorted(models),
    )


def _metric_winner(
    value_a: float | int | None, value_b: float | int | None, higher_is_better: bool | None
) -> str | None:
    """Decide the winner for one metric row.

    Returns ``None`` when the metric is informational-only, or either value
    is missing (an honest "can't judge" rather than guessing).
    """
    if higher_is_better is None:
        return None
    if value_a is None or value_b is None:
        return None
    if value_a == value_b:
        return "tie"
    if higher_is_better:
        return "a" if value_a > value_b else "b"
    return "a" if value_a < value_b else "b"


def _build_metrics(run_a: RunMetrics, run_b: RunMetrics) -> list[MetricComparison]:
    rows: list[MetricComparison] = []
    for field_name, label, higher_is_better in _METRIC_SPECS:
        value_a = getattr(run_a, field_name)
        value_b = getattr(run_b, field_name)
        winner = _metric_winner(value_a, value_b, higher_is_better)
        rows.append(
            MetricComparison(
                field_name=field_name,
                label=label,
                value_a=value_a,
                value_b=value_b,
                winner=winner,
            )
        )
    return rows


def _build_verdict(run_a: RunMetrics, run_b: RunMetrics, metrics: list[MetricComparison]) -> str:
    """Compose a single honest verdict sentence from the decided metric rows."""
    if not run_a.exists and not run_b.exists:
        return f"Neither {run_a.swarm_id} nor {run_b.swarm_id} could be found."
    if not run_a.exists:
        return f"{run_a.swarm_id} was not found; nothing to compare {run_b.swarm_id} against."
    if not run_b.exists:
        return f"{run_b.swarm_id} was not found; nothing to compare {run_a.swarm_id} against."
    if run_a.total == 0 and run_b.total == 0:
        return f"Both {run_a.swarm_id} and {run_b.swarm_id} have no units recorded."

    decided = [m for m in metrics if m.winner in ("a", "b")]
    if not decided:
        return "Not enough comparable data to declare a winner."

    a_wins = sum(1 for m in decided if m.winner == "a")
    b_wins = sum(1 for m in decided if m.winner == "b")

    if a_wins == b_wins:
        return (
            f"{run_a.swarm_id} and {run_b.swarm_id} are evenly matched "
            f"({a_wins} metric(s) each of {len(decided)} decided)."
        )

    winner_run, loser_run, winner_count, loser_count = (
        (run_a, run_b, a_wins, b_wins) if a_wins > b_wins else (run_b, run_a, b_wins, a_wins)
    )

    # Call out the two headline reasons (verified rate, cost/speed) when the
    # winner actually took them, otherwise keep the verdict generic.
    verified_row = next((m for m in decided if m.field_name == "verified_rate"), None)
    cost_row = next((m for m in decided if m.field_name == "total_cost_usd"), None)
    reasons: list[str] = []
    winner_side = "a" if winner_run is run_a else "b"
    if verified_row is not None and verified_row.winner == winner_side:
        reasons.append("higher verified rate")
    if cost_row is not None and cost_row.winner == winner_side:
        reasons.append("lower cost")
    reason_note = f" ({', '.join(reasons)})" if reasons else ""

    return (
        f"{winner_run.swarm_id} did better than {loser_run.swarm_id} "
        f"({winner_count}/{winner_count + loser_count} decided metrics{reason_note})."
    )


def build_comparison(run_a: RunMetrics, run_b: RunMetrics) -> Comparison:
    """Build a :class:`Comparison` from two already-built :class:`RunMetrics`.

    Pure and deterministic: no filesystem access, no clock, no randomness.
    """
    metrics = _build_metrics(run_a, run_b)
    verdict = _build_verdict(run_a, run_b, metrics)
    return Comparison(run_a=run_a, run_b=run_b, metrics=metrics, verdict=verdict)


def _fmt_seconds(seconds: float) -> str:
    """Render a wall-clock duration compactly (``"42s"`` or ``"3m12s"``)."""
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    return f"{minutes}m{secs:02d}s"


def _fmt_value(field_name: str, value: float | int | None) -> str:
    if value is None:
        return "—"
    if field_name in ("total_wall_seconds", "avg_wall_seconds"):
        return _fmt_seconds(float(value))
    if field_name == "total_cost_usd":
        return f"${float(value):.4f}"
    if field_name == "verified_rate":
        return f"{float(value) * 100:.1f}%"
    if field_name == "avg_iterations":
        return f"{float(value):.2f}"
    return str(value)


def render_text(comparison: Comparison) -> str:
    """Render a :class:`Comparison` as a deterministic plain-text table.

    No LLM call, no colour codes — safe for piping/redirection. Missing runs
    render an explicit "not found" line instead of fabricated rows.
    """
    run_a, run_b = comparison.run_a, comparison.run_b
    lines: list[str] = []
    lines.append(f"Compare — {run_a.swarm_id}  vs  {run_b.swarm_id}")
    lines.append("")

    if not run_a.exists or not run_b.exists:
        for run in (run_a, run_b):
            if not run.exists:
                lines.append(f"  {run.swarm_id}: not found")
        lines.append("")
        lines.append(comparison.verdict)
        return "\n".join(lines)

    conc_a = run_a.concurrency if run_a.concurrency is not None else "?"
    conc_b = run_b.concurrency if run_b.concurrency is not None else "?"
    meta_a = f"{run_a.mode or '?'} · {run_a.agent or '?'} · concurrency {conc_a}"
    meta_b = f"{run_b.mode or '?'} · {run_b.agent or '?'} · concurrency {conc_b}"
    lines.append(f"  A: {run_a.swarm_id}  ({meta_a})")
    lines.append(f"  B: {run_b.swarm_id}  ({meta_b})")
    lines.append("")

    label_width = max(len(m.label) for m in comparison.metrics)
    header = f"  {'metric'.ljust(label_width)}   {'A'.rjust(12)}   {'B'.rjust(12)}   winner"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for m in comparison.metrics:
        val_a = _fmt_value(m.field_name, m.value_a)
        val_b = _fmt_value(m.field_name, m.value_b)
        if m.winner == "a":
            winner_cell = "A"
        elif m.winner == "b":
            winner_cell = "B"
        elif m.winner == "tie":
            winner_cell = "tie"
        else:
            winner_cell = "—"
        label_cell = m.label.ljust(label_width)
        row = f"  {label_cell}   {val_a.rjust(12)}   {val_b.rjust(12)}   {winner_cell}"
        lines.append(row)

    if run_a.models_used or run_b.models_used:
        lines.append("")
        lines.append(f"  models A: {', '.join(run_a.models_used) or '—'}")
        lines.append(f"  models B: {', '.join(run_b.models_used) or '—'}")

    lines.append("")
    lines.append(comparison.verdict)
    return "\n".join(lines)


__all__ = [
    "Comparison",
    "MetricComparison",
    "ReceiptReader",
    "RunMetrics",
    "build_comparison",
    "build_run_metrics",
    "render_text",
]
