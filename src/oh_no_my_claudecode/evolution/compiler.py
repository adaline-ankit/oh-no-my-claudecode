"""Evolution compiler — pure function that produces an EvolutionReport.

Methodology (honest description)
----------------------------------
Numbers are derived entirely from ``RunReceipt`` JSON files written by
``onmc loop`` / ``onmc autopilot`` to ``.agent-memory/receipts/``.

Trend calculation
~~~~~~~~~~~~~~~~~
Receipts are sorted chronologically (``ended_at`` → ``started_at`` → file
mtime → filename as fallback for null timestamps).  When there are ≥ 2
receipts the series is split into an **early window** (first half, rounded
down) and a **recent window** (second half, rounded up).  Means of each
window are compared to produce headline deltas.

Honesty constraints
~~~~~~~~~~~~~~~~~~~
- **≥ 2 receipts required** — fewer returns a report flagged
  ``insufficient_data=True``; no trend numbers are fabricated.
- **Cost delta is optional** — if no receipt in either window has
  ``cost_usd`` the cost trend is omitted and ``cost_unavailable=True`` is
  set.
- **"iterations-to-converge"** is the wasted-effort proxy: it measures how
  many loop iterations were needed before the run ended.  A converging run
  that needs fewer iterations over time signals learning.  The label in the
  report is explicit so callers can display it honestly.

This function is **pure** — it reads files and returns a dataclass; it
never writes or calls an LLM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunPoint:
    """One receipt reduced to the fields needed for trend analysis."""

    index: int
    """0-based chronological position."""
    goal_short: str
    """First 60 chars of the goal."""
    agent: str
    """Agent selector (e.g. "claude", "dry-run")."""
    verified: bool
    """True iff the loop converged and verifier passed."""
    iterations: int
    """Number of iterations completed (proxy for wasted effort)."""
    tokens: int
    """Total tokens consumed."""
    cost_usd: float | None
    """USD cost when reported; None otherwise."""
    wall_seconds: float
    """Wall-clock seconds for the run."""
    when: str | None
    """ISO-8601 timestamp (ended_at preferred, then started_at, else None)."""


@dataclass(frozen=True)
class EvolutionReport:
    """All data needed to render the evolution card.

    Fields
    ------
    runs:
        Chronologically ordered list of :class:`RunPoint` objects.
    run_count:
        Total number of valid receipts loaded.
    insufficient_data:
        True when fewer than 2 receipts are available; no trend is meaningful.
    cost_change_pct:
        Percentage change in mean cost from early → recent window.
        Negative = cheaper (improving).  ``None`` when cost is unavailable
        or ``insufficient_data`` is True.
    iterations_change_pct:
        Percentage change in mean iterations from early → recent window.
        Negative = fewer iterations (improving).  ``None`` when
        ``insufficient_data`` is True.
    cost_unavailable:
        True when no receipt in either window has ``cost_usd``.
    verified_rate:
        Fraction of runs (0.0–1.0) that ended ``verified=True``.
    total_cost_usd:
        Sum of all known ``cost_usd`` values; 0.0 when none known.
    total_tokens:
        Sum of all ``tokens_used`` values.
    total_runs:
        Same as ``run_count``.
    first_when:
        Timestamp of the earliest run (or None).
    latest_when:
        Timestamp of the most recent run (or None).
    early_mean_iterations:
        Mean iterations in the early window; None when insufficient_data.
    recent_mean_iterations:
        Mean iterations in the recent window; None when insufficient_data.
    early_mean_cost_usd:
        Mean cost in the early window; None when cost unavailable or
        insufficient_data.
    recent_mean_cost_usd:
        Mean cost in the recent window; None when cost unavailable or
        insufficient_data.
    iterations_proxy_label:
        Human-readable label for the iterations proxy metric.
    """

    runs: list[RunPoint]
    run_count: int
    insufficient_data: bool

    # trend deltas (None when insufficient_data or cost unavailable)
    cost_change_pct: float | None
    iterations_change_pct: float | None
    cost_unavailable: bool

    # rates and totals
    verified_rate: float
    total_cost_usd: float
    total_tokens: int
    total_runs: int

    # time window
    first_when: str | None
    latest_when: str | None

    # window means (for display and debugging)
    early_mean_iterations: float | None
    recent_mean_iterations: float | None
    early_mean_cost_usd: float | None
    recent_mean_cost_usd: float | None

    # honesty label
    iterations_proxy_label: str = "iterations-to-converge"

    # inline per-run list (populated from runs)
    run_summary: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 UTC string; return None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sort_key(receipt_dict: dict[str, Any], mtime: float, filename: str) -> tuple[object, ...]:
    """Return a sort key for chronological ordering.

    Priority: ended_at → started_at → mtime → filename.
    Null timestamps sort after non-null ones.
    """
    has_end = 1
    end_dt = _parse_iso(receipt_dict.get("ended_at") or "")
    if end_dt is not None:
        return (0, end_dt, mtime, filename)

    start_dt = _parse_iso(receipt_dict.get("started_at") or "")
    if start_dt is not None:
        return (1, start_dt, mtime, filename)

    # Fall back to file mtime then filename
    del has_end
    return (2, datetime(1970, 1, 1, tzinfo=UTC), mtime, filename)


def _safe_mean(values: list[float]) -> float | None:
    """Return the mean of *values*, or None for an empty list."""
    if not values:
        return None
    return sum(values) / len(values)


def _pct_change(old: float, new: float) -> float | None:
    """Return percentage change from *old* to *new*; None when old is zero."""
    if old == 0.0:
        return None
    return (new - old) / old * 100.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_evolution(
    receipts_dir: Path,
    *,
    now: datetime | None = None,  # noqa: ARG001  (reserved for future injection)
) -> EvolutionReport:
    """Compile an :class:`EvolutionReport` from receipts on disk.

    Parameters
    ----------
    receipts_dir:
        Directory containing ``run-*.json`` receipt files
        (typically ``.agent-memory/receipts/``).
    now:
        Injectable current time (reserved for future use; currently unused).

    Returns
    -------
    EvolutionReport
        A fully populated report.  When ``receipts_dir`` does not exist or
        contains fewer than 2 valid receipts, ``insufficient_data=True`` is
        set and all trend fields are ``None``.
    """
    # --- load and sort receipts ---
    raw: list[tuple[dict[str, Any], float, str]] = []  # (data, mtime, filename)

    if receipts_dir.exists() and receipts_dir.is_dir():
        for entry in sorted(receipts_dir.iterdir()):
            if entry.suffix != ".json":
                continue
            try:
                text = entry.read_text(encoding="utf-8")
                data: dict[str, Any] = json.loads(text)
                if not isinstance(data, dict):
                    continue
                mtime = entry.stat().st_mtime
                raw.append((data, mtime, entry.name))
            except (OSError, json.JSONDecodeError, ValueError):
                # Skip malformed or unreadable files — never crash.
                continue

    # Sort chronologically.
    raw.sort(key=lambda t: _sort_key(t[0], t[1], t[2]))

    # --- build RunPoint list ---
    points: list[RunPoint] = []
    for idx, (data, _mtime, _fname) in enumerate(raw):
        try:
            goal_raw = str(data.get("goal") or "")
            agent_raw = str(data.get("agent") or "unknown")
            verified_raw = bool(data.get("verified", False))
            iterations_raw = int(data.get("iterations", 0))
            tokens_raw = int(data.get("tokens_used", 0))
            cost_raw = data.get("cost_usd")
            cost_val: float | None = float(cost_raw) if cost_raw is not None else None
            wall_raw = float(data.get("wall_seconds", 0.0))

            ended = data.get("ended_at") or data.get("started_at")
            when_val: str | None = str(ended) if ended else None

            points.append(
                RunPoint(
                    index=idx,
                    goal_short=goal_raw[:60],
                    agent=agent_raw,
                    verified=verified_raw,
                    iterations=iterations_raw,
                    tokens=tokens_raw,
                    cost_usd=cost_val,
                    wall_seconds=wall_raw,
                    when=when_val,
                )
            )
        except (TypeError, ValueError):
            # Skip receipts with invalid field types.
            continue

    n = len(points)
    run_count = n

    # --- totals (always computable) ---
    total_tokens = sum(p.tokens for p in points)
    total_cost_usd = sum(p.cost_usd for p in points if p.cost_usd is not None)
    verified_count = sum(1 for p in points if p.verified)
    verified_rate = verified_count / n if n > 0 else 0.0

    first_when = points[0].when if points else None
    latest_when = points[-1].when if points else None

    # --- insufficient data path ---
    if n < 2:  # noqa: PLR2004
        return EvolutionReport(
            runs=points,
            run_count=run_count,
            insufficient_data=True,
            cost_change_pct=None,
            iterations_change_pct=None,
            cost_unavailable=True,
            verified_rate=verified_rate,
            total_cost_usd=total_cost_usd,
            total_tokens=total_tokens,
            total_runs=run_count,
            first_when=first_when,
            latest_when=latest_when,
            early_mean_iterations=None,
            recent_mean_iterations=None,
            early_mean_cost_usd=None,
            recent_mean_cost_usd=None,
            run_summary=_build_run_summary(points),
        )

    # --- split into early vs recent windows ---
    # First half (floor) = early; second half (ceiling) = recent.
    split = n // 2
    early = points[:split]
    recent = points[split:]

    early_iter_vals = [float(p.iterations) for p in early]
    recent_iter_vals = [float(p.iterations) for p in recent]
    early_mean_iter = _safe_mean(early_iter_vals)
    recent_mean_iter = _safe_mean(recent_iter_vals)

    iterations_change_pct: float | None = None
    if early_mean_iter is not None and recent_mean_iter is not None:
        iterations_change_pct = _pct_change(early_mean_iter, recent_mean_iter)

    # Cost trend (optional — only when data exists in both windows).
    early_cost_vals = [p.cost_usd for p in early if p.cost_usd is not None]
    recent_cost_vals = [p.cost_usd for p in recent if p.cost_usd is not None]
    cost_unavailable = not early_cost_vals or not recent_cost_vals
    early_mean_cost = _safe_mean(list(early_cost_vals))
    recent_mean_cost = _safe_mean(list(recent_cost_vals))

    cost_change_pct: float | None = None
    if not cost_unavailable and early_mean_cost is not None and recent_mean_cost is not None:
        cost_change_pct = _pct_change(early_mean_cost, recent_mean_cost)

    cost_pct_rounded = round(cost_change_pct, 1) if cost_change_pct is not None else None
    iter_pct_rounded = (
        round(iterations_change_pct, 1) if iterations_change_pct is not None else None
    )
    return EvolutionReport(
        runs=points,
        run_count=run_count,
        insufficient_data=False,
        cost_change_pct=cost_pct_rounded,
        iterations_change_pct=iter_pct_rounded,
        cost_unavailable=cost_unavailable,
        verified_rate=round(verified_rate, 3),
        total_cost_usd=round(total_cost_usd, 4),
        total_tokens=total_tokens,
        total_runs=run_count,
        first_when=first_when,
        latest_when=latest_when,
        early_mean_iterations=round(early_mean_iter, 2) if early_mean_iter is not None else None,
        recent_mean_iterations=round(recent_mean_iter, 2) if recent_mean_iter is not None else None,
        early_mean_cost_usd=round(early_mean_cost, 4) if early_mean_cost is not None else None,
        recent_mean_cost_usd=round(recent_mean_cost, 4) if recent_mean_cost is not None else None,
        run_summary=_build_run_summary(points),
    )


def _build_run_summary(points: list[RunPoint]) -> list[dict[str, Any]]:
    """Build a JSON-serialisable summary list from *points*."""
    return [
        {
            "index": p.index,
            "goal_short": p.goal_short,
            "agent": p.agent,
            "verified": p.verified,
            "iterations": p.iterations,
            "tokens": p.tokens,
            "cost_usd": p.cost_usd,
            "wall_seconds": p.wall_seconds,
            "when": p.when,
        }
        for p in points
    ]


__all__ = [
    "RunPoint",
    "EvolutionReport",
    "compile_evolution",
]
