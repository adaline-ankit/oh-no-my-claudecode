"""Pure, deterministic spend accounting for the ``onmc cost`` command.

``cost`` answers *where did the money go, and where is it going* — distinct
from :mod:`oh_no_my_claudecode.savings` (an ROI/"wrapped" estimate against an
assumed human baseline) and :mod:`oh_no_my_claudecode.standup` (an activity
digest). This module looks at the same run-receipt schema
(:mod:`oh_no_my_claudecode.ledger.accounting`, schema_version "2") that
``onmc loop`` / ``onmc swarm`` write to ``.agent-memory/receipts/`` and folds
them into: total spend, spend by model, spend by day (within a trailing
window), cost-per-verified-run, and a simple linear forecast.

Design notes
------------
- **Pure core**: :func:`build_cost_report` takes an already-loaded list of
  receipt dicts plus an injected ``now`` — it never touches the clock or the
  filesystem. The command layer (:mod:`oh_no_my_claudecode.cost.commands`) is
  responsible for loading receipts and supplying ``now``.
- **Deterministic**: same input list + same ``now`` + same ``days`` → identical
  :class:`CostReport`, identical rendered text. Model breakdowns are sorted by
  cost descending then name ascending; day breakdowns are sorted
  chronologically. Ties never reorder between runs.
- **Never fabricates**: a receipt with ``cost_usd is None`` contributes nothing
  to any total and is tallied separately (``cost_unknown_count``), mirroring
  :mod:`oh_no_my_claudecode.ledger.accounting`'s honesty constraint. A receipt
  with no usable timestamp is excluded from the day breakdown and the window
  filter (we cannot prove which day, or whether it falls in the window) and is
  counted in a note rather than silently dropped.
- **Forecast is explicitly an estimate**: :func:`build_cost_report` computes
  ``forecast_monthly_usd`` as ``(known spend in window / days elapsed in
  window) * 30`` — a flat linear projection, labelled ``est`` in every render
  path. It is ``None`` (never fabricated) when there is no known cost or no
  elapsed time to average over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

#: Default trailing window, in days, when no ``--days`` is given.
DEFAULT_DAYS = 30


@dataclass(frozen=True)
class ModelSpend:
    """Spend + run counts for one model."""

    model: str
    runs: int
    cost_usd: float
    cost_unknown_count: int
    verified: int


@dataclass(frozen=True)
class DaySpend:
    """Spend + run counts for one calendar day (UTC), chronological order."""

    day: str  # ISO date, e.g. "2026-07-06"
    runs: int
    cost_usd: float
    cost_unknown_count: int


@dataclass(frozen=True)
class CostReport:
    """The full spend breakdown + forecast for a trailing window.

    Fields
    ------
    since / now:
        The resolved window bounds (aware UTC datetimes).
    days:
        The requested window size in days.
    total_runs:
        Number of receipts included in the window (timestamp resolvable and
        falling within it).
    total_cost_usd:
        Sum of all *known* ``cost_usd`` values in the window.
    cost_unknown_count:
        Number of in-window receipts whose ``cost_usd`` was ``None``.
    verified_count:
        Number of in-window receipts with ``verified=True``.
    cost_per_verified_run_usd:
        ``total_cost_usd / verified_count``, or ``None`` when there are no
        verified runs (never a division by zero, never fabricated).
    by_model:
        Per-model breakdown, sorted by ``cost_usd`` descending then ``model``
        ascending.
    by_day:
        Per-day breakdown covering the window, sorted chronologically. Days
        with zero receipts still appear with zero counts, so callers can plot
        a continuous series.
    forecast_daily_avg_usd:
        Average known daily spend over the *elapsed* portion of the window
        (``None`` when there is no known cost or zero elapsed days).
    forecast_monthly_usd:
        ``forecast_daily_avg_usd * 30`` — a flat linear projection, always
        ``None`` when ``forecast_daily_avg_usd`` is ``None``. Labelled an
        estimate at every render boundary.
    excluded_undated_count:
        Receipts skipped because they had no usable timestamp.
    notes:
        Honest, human-readable caveats.
    """

    since: datetime
    now: datetime
    days: int
    total_runs: int
    total_cost_usd: float
    cost_unknown_count: int
    verified_count: int
    cost_per_verified_run_usd: float | None
    by_model: list[ModelSpend] = field(default_factory=list)
    by_day: list[DaySpend] = field(default_factory=list)
    forecast_daily_avg_usd: float | None = None
    forecast_monthly_usd: float | None = None
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


def _coerce_receipt(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return a normalised view of one receipt, or ``None`` to skip unusable input."""
    if not isinstance(data, dict):
        return None
    try:
        verified = bool(data.get("verified", False))
        cost_raw = data.get("cost_usd")
        cost: float | None = float(cost_raw) if cost_raw is not None else None
        model = str(data.get("model") or "unknown")
    except (TypeError, ValueError):
        return None
    return {"verified": verified, "cost_usd": cost, "model": model}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_cost_report(
    receipts: list[dict[str, Any]],
    *,
    now: datetime,
    days: int = DEFAULT_DAYS,
) -> CostReport:
    """Fold *receipts* into a :class:`CostReport` covering the trailing window.

    Args:
        receipts: Raw receipt dicts (any order), typically from
            :func:`oh_no_my_claudecode.ledger.accounting.load_receipts`.
        now: Reference instant defining the end of the window. Never read
            from the clock inside this function.
        days: Trailing window size in days (default :data:`DEFAULT_DAYS`).
            Values less than 1 are clamped to 1.

    Returns:
        A :class:`CostReport` with deterministic ordering: model breakdown
        sorted by cost descending then name ascending; day breakdown sorted
        chronologically covering every day in the window (zero-filled).
    """
    notes: list[str] = []
    now_utc = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
    window_days = max(1, days)
    since = now_utc - timedelta(days=window_days)

    included: list[dict[str, Any]] = []
    included_when: list[datetime] = []
    excluded_undated = 0
    for raw in receipts:
        if not isinstance(raw, dict):
            continue
        coerced = _coerce_receipt(raw)
        if coerced is None:
            continue
        when = _receipt_when(raw)
        if when is None:
            excluded_undated += 1
            continue
        if when < since or when > now_utc:
            continue
        included.append(coerced)
        included_when.append(when)

    if excluded_undated:
        plural = "" if excluded_undated == 1 else "s"
        notes.append(
            f"{excluded_undated} receipt{plural} had no usable timestamp and "
            "were excluded from the window"
        )

    total_runs = len(included)
    total_cost_usd = 0.0
    cost_unknown_count = 0
    verified_count = 0
    model_buckets: dict[str, dict[str, Any]] = {}
    day_buckets: dict[str, dict[str, Any]] = {}

    # Zero-fill every day in the window so callers get a continuous series.
    for offset in range(window_days + 1):
        day_key = (since + timedelta(days=offset)).date().isoformat()
        day_buckets[day_key] = {"runs": 0, "cost_usd": 0.0, "cost_unknown_count": 0}

    for r, when in zip(included, included_when, strict=True):
        if r["verified"]:
            verified_count += 1
        if r["cost_usd"] is None:
            cost_unknown_count += 1
        else:
            total_cost_usd += r["cost_usd"]

        mb = model_buckets.setdefault(
            r["model"], {"runs": 0, "cost_usd": 0.0, "cost_unknown_count": 0, "verified": 0}
        )
        mb["runs"] += 1
        if r["verified"]:
            mb["verified"] += 1
        if r["cost_usd"] is None:
            mb["cost_unknown_count"] += 1
        else:
            mb["cost_usd"] += r["cost_usd"]

        day_key = when.date().isoformat()
        db = day_buckets.setdefault(day_key, {"runs": 0, "cost_usd": 0.0, "cost_unknown_count": 0})
        db["runs"] += 1
        if r["cost_usd"] is None:
            db["cost_unknown_count"] += 1
        else:
            db["cost_usd"] += r["cost_usd"]

    by_model = [
        ModelSpend(
            model=name,
            runs=b["runs"],
            cost_usd=round(b["cost_usd"], 4),
            cost_unknown_count=b["cost_unknown_count"],
            verified=b["verified"],
        )
        for name, b in model_buckets.items()
    ]
    by_model.sort(key=lambda m: (-m.cost_usd, m.model))

    by_day = [
        DaySpend(
            day=day_key,
            runs=b["runs"],
            cost_usd=round(b["cost_usd"], 4),
            cost_unknown_count=b["cost_unknown_count"],
        )
        for day_key, b in sorted(day_buckets.items())
    ]

    cost_per_verified_run_usd = (
        round(total_cost_usd / verified_count, 4) if verified_count > 0 else None
    )

    # Linear forecast: average known daily spend over the *elapsed* days in
    # the window, projected to a flat 30-day month. Never fabricated when
    # there is nothing to average.
    elapsed_days = max(1.0, (now_utc - since).total_seconds() / 86400.0)
    forecast_daily_avg_usd: float | None = None
    forecast_monthly_usd: float | None = None
    # Only compute a forecast when at least one receipt in the window
    # actually reported a cost — an all-unknown or empty window has nothing
    # to average and must stay "n/a" rather than fabricate a number.
    has_known_cost = total_runs > 0 and cost_unknown_count < total_runs
    if has_known_cost:
        forecast_daily_avg_usd = round(total_cost_usd / elapsed_days, 4)
        forecast_monthly_usd = round(forecast_daily_avg_usd * 30, 2)

    if total_runs == 0:
        notes.append(f"No run receipts in the last {window_days} day(s).")
    elif cost_unknown_count == total_runs:
        notes.append(
            "Cost is n/a — no receipt in the window reported cost_usd (the "
            "agent adapter did not surface a price)."
        )
        forecast_daily_avg_usd = None
        forecast_monthly_usd = None
    elif cost_unknown_count > 0:
        notes.append(
            f"Cost is partial — {cost_unknown_count} of {total_runs} receipts "
            "in the window had no cost_usd and are excluded from totals."
        )

    return CostReport(
        since=since,
        now=now_utc,
        days=window_days,
        total_runs=total_runs,
        total_cost_usd=round(total_cost_usd, 4),
        cost_unknown_count=cost_unknown_count,
        verified_count=verified_count,
        cost_per_verified_run_usd=cost_per_verified_run_usd,
        by_model=by_model,
        by_day=by_day,
        forecast_daily_avg_usd=forecast_daily_avg_usd,
        forecast_monthly_usd=forecast_monthly_usd,
        excluded_undated_count=excluded_undated,
        notes=notes,
    )


def render_text(report: CostReport) -> str:
    """Render *report* as deterministic, readable plain-text English."""
    lines: list[str] = ["Agent spend", ""]

    for note in report.notes:
        lines.append(f"note: {note}")
    if report.notes:
        lines.append("")

    if report.total_runs == 0:
        lines.append(f"No agent runs with cost data in the last {report.days} day(s).")
        return "\n".join(lines)

    cost_str = (
        f"${report.total_cost_usd:.2f}"
        if report.cost_unknown_count == 0
        else (
            f"${report.total_cost_usd:.2f} (+{report.cost_unknown_count} run"
            f"{'s' if report.cost_unknown_count != 1 else ''} with unknown cost)"
        )
    )
    per_verified = (
        f"${report.cost_per_verified_run_usd:.4f}"
        if report.cost_per_verified_run_usd is not None
        else "n/a"
    )

    lines.append(
        f"Last {report.days} day(s): {report.total_runs} run"
        f"{'s' if report.total_runs != 1 else ''}, total spend {cost_str}."
    )
    lines.append(
        f"Verified runs: {report.verified_count}. Cost per verified run: {per_verified}."
    )
    lines.append("")

    lines.append("By model:")
    for m in report.by_model:
        m_cost = (
            f"${m.cost_usd:.2f}"
            if m.cost_unknown_count == 0
            else f"${m.cost_usd:.2f} (+{m.cost_unknown_count} unknown)"
        )
        lines.append(
            f"  - {m.model}: {m.runs} run{'s' if m.runs != 1 else ''}, "
            f"{m.verified} verified, {m_cost}"
        )
    lines.append("")

    lines.append("By day:")
    for d in report.by_day:
        if d.runs == 0:
            lines.append(f"  - {d.day}: no runs")
            continue
        d_cost = (
            f"${d.cost_usd:.2f}"
            if d.cost_unknown_count == 0
            else f"${d.cost_usd:.2f} (+{d.cost_unknown_count} unknown)"
        )
        lines.append(f"  - {d.day}: {d.runs} run{'s' if d.runs != 1 else ''}, {d_cost}")
    lines.append("")

    if report.forecast_monthly_usd is not None:
        lines.append(
            f"Forecast (est): ${report.forecast_daily_avg_usd:.2f}/day avg -> "
            f"${report.forecast_monthly_usd:.2f}/month projected. "
            "Linear estimate from known spend in this window, not a measurement."
        )
    else:
        lines.append("Forecast (est): n/a — no known cost in this window to project from.")

    return "\n".join(lines)


__all__ = [
    "DEFAULT_DAYS",
    "CostReport",
    "DaySpend",
    "ModelSpend",
    "build_cost_report",
    "render_text",
]
