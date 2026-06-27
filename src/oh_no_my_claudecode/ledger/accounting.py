"""Ledger accounting — pure aggregation over run receipts.

Methodology (honest description)
--------------------------------
All numbers are derived directly from ``RunReceipt`` JSON files written by
``onmc loop`` / ``onmc swarm`` to ``.agent-memory/receipts/``.  The same receipt
shape (schema_version "2") is reused verbatim — no new schema is introduced.

The fields consumed per receipt:

- ``agent``        — agent selector (e.g. "claude", "codex", "dry-run").
- ``model``        — model name when the adapter surfaced one; else None.
- ``verified``     — honest success flag (converged AND verifier passed).
- ``cost_usd``     — USD cost when reported; often ``None``.
- ``wall_seconds`` — wall-clock seconds for the run.
- ``ended_at`` / ``started_at`` — ISO-8601 UTC timestamps for date scoping.

Honesty constraints
~~~~~~~~~~~~~~~~~~~
- **Null cost is never faked.**  A receipt with ``cost_usd is None`` adds
  nothing to ``total_cost_usd`` and is tallied in ``cost_unknown_count`` so the
  caller can render "n/a" rather than an invented number.
- **Empty input is safe.**  Zero receipts → all-zero summary, no division by
  zero (``success_rate == 0.0``).
- **ROI is an estimate.**  :func:`roi` is labelled ``est`` and exposes its one
  assumption (human-minutes-per-run) so the figure is never mistaken for a
  measured saving.

This module is **pure** with the single exception of :func:`load_receipts`,
which reads the receipt directory for the CLI and is not used by tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tunable, honestly-labelled ROI assumption
# ---------------------------------------------------------------------------

#: Assumed wall-clock minutes a human would spend doing the work of one run.
#: This is a transparent placeholder, NOT a measurement — see :func:`roi`.
_ASSUMED_HUMAN_MINUTES_PER_RUN = 30.0


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerSummary:
    """Aggregated agent-work accounting over a set of run receipts.

    Fields
    ------
    scope:
        The scope label this summary was computed for ("today", "project", …).
    run_count:
        Number of valid receipts included in the summary.
    total_cost_usd:
        Sum of all *known* ``cost_usd`` values.  Receipts with ``None`` cost
        contribute nothing and are counted in ``cost_unknown_count`` instead.
    cost_unknown_count:
        Number of receipts whose ``cost_usd`` was ``None`` (cost not reported).
    total_wall_seconds:
        Sum of all ``wall_seconds`` values.
    success_count:
        Number of receipts with ``verified=True``.
    success_rate:
        ``success_count / run_count`` (0.0 when ``run_count == 0`` — no
        division by zero).
    by_model:
        Per-model breakdown keyed by model name ("unknown" when None).  Each
        value is ``{runs, cost_usd, wall_seconds, success_count,
        cost_unknown_count}``.
    by_agent:
        Per-agent breakdown keyed by agent selector, same value shape as
        ``by_model``.
    note:
        Honest, human-readable caveat (e.g. when cost data is partial/absent).
    """

    scope: str
    run_count: int
    total_cost_usd: float
    cost_unknown_count: int
    total_wall_seconds: float
    success_count: int
    success_rate: float
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_agent: dict[str, dict[str, Any]] = field(default_factory=dict)
    note: str = ""

    @property
    def cost_label(self) -> str:
        """Honest cost headline: ``"n/a"`` when no receipt reported a cost."""
        if self.run_count == 0:
            return "n/a"
        if self.cost_unknown_count == self.run_count:
            return "n/a"
        return f"${self.total_cost_usd:.4f}"


@dataclass(frozen=True)
class RoiEstimate:
    """An honestly-labelled ROI *estimate* (never a measurement).

    Fields
    ------
    estimated:
        Always ``True`` — present so callers cannot forget this is an estimate.
    label:
        The literal string ``"est"`` for terse rendering.
    agent_wall_minutes:
        Real measured wall-clock minutes the agent spent (from receipts).
    assumed_human_minutes_per_run:
        The transparent assumption used: human minutes per run.
    estimated_human_minutes:
        ``run_count * assumed_human_minutes_per_run`` — the modelled human cost.
    estimated_minutes_saved:
        ``estimated_human_minutes - agent_wall_minutes``.  May be negative when
        the agent took longer than the assumed human baseline (reported
        honestly, not clamped).
    total_cost_usd:
        Known agent spend carried over from the summary (for $/run context).
    assumption_note:
        Plain-English statement of the assumption so the number is auditable.
    """

    estimated: bool
    label: str
    agent_wall_minutes: float
    assumed_human_minutes_per_run: float
    estimated_human_minutes: float
    estimated_minutes_saved: float
    total_cost_usd: float
    assumption_note: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 UTC string; return None on failure or empty input."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _receipt_when(data: dict[str, Any]) -> datetime | None:
    """Return the receipt's timestamp (ended_at preferred, then started_at)."""
    return _parse_iso(str(data.get("ended_at") or "")) or _parse_iso(
        str(data.get("started_at") or "")
    )


def _empty_bucket() -> dict[str, Any]:
    return {
        "runs": 0,
        "cost_usd": 0.0,
        "wall_seconds": 0.0,
        "success_count": 0,
        "cost_unknown_count": 0,
    }


# ---------------------------------------------------------------------------
# Pure aggregation
# ---------------------------------------------------------------------------


def summarize_receipts(
    receipts: list[dict[str, Any]],
    *,
    scope: str,
) -> LedgerSummary:
    """Aggregate *receipts* into a :class:`LedgerSummary`.

    Pure and deterministic: given the same receipt list it always returns the
    same summary.  Inject the list directly for offline testing.

    Parameters
    ----------
    receipts:
        A list of receipt dicts (already loaded / filtered by the caller).
    scope:
        Scope label to record on the summary ("today", "project", …).

    Returns
    -------
    LedgerSummary
        Fully populated summary.  An empty list yields an all-zero summary with
        ``success_rate == 0.0`` and no division by zero.
    """
    run_count = 0
    total_cost_usd = 0.0
    cost_unknown_count = 0
    total_wall_seconds = 0.0
    success_count = 0
    by_model: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, dict[str, Any]] = {}

    for data in receipts:
        if not isinstance(data, dict):
            continue
        try:
            verified = bool(data.get("verified", False))
            wall = float(data.get("wall_seconds", 0.0) or 0.0)
            cost_raw = data.get("cost_usd")
            cost_val: float | None = float(cost_raw) if cost_raw is not None else None
            model = str(data.get("model") or "unknown")
            agent = str(data.get("agent") or "unknown")
        except (TypeError, ValueError):
            # Skip receipts with invalid field types — never crash.
            continue

        run_count += 1
        total_wall_seconds += wall
        if verified:
            success_count += 1
        if cost_val is None:
            cost_unknown_count += 1
        else:
            total_cost_usd += cost_val

        for key, table in ((model, by_model), (agent, by_agent)):
            bucket = table.setdefault(key, _empty_bucket())
            bucket["runs"] += 1
            bucket["wall_seconds"] += wall
            if verified:
                bucket["success_count"] += 1
            if cost_val is None:
                bucket["cost_unknown_count"] += 1
            else:
                bucket["cost_usd"] += cost_val

    success_rate = success_count / run_count if run_count > 0 else 0.0

    note = _build_note(
        run_count=run_count,
        cost_unknown_count=cost_unknown_count,
    )

    # Round breakdown floats for stable, readable output.
    for table in (by_model, by_agent):
        for bucket in table.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 4)
            bucket["wall_seconds"] = round(bucket["wall_seconds"], 3)

    return LedgerSummary(
        scope=scope,
        run_count=run_count,
        total_cost_usd=round(total_cost_usd, 4),
        cost_unknown_count=cost_unknown_count,
        total_wall_seconds=round(total_wall_seconds, 3),
        success_count=success_count,
        success_rate=round(success_rate, 4),
        by_model=by_model,
        by_agent=by_agent,
        note=note,
    )


def _build_note(*, run_count: int, cost_unknown_count: int) -> str:
    """Return an honest caveat string for the summary."""
    if run_count == 0:
        return "No run receipts found — run `onmc loop` or `onmc swarm` first."
    if cost_unknown_count == run_count:
        return (
            "Cost is n/a — no receipt reported cost_usd (the agent adapter did "
            "not surface a price). Wall-time and success-rate are real."
        )
    if cost_unknown_count > 0:
        return (
            f"Cost is partial — {cost_unknown_count} of {run_count} receipts "
            "had no cost_usd and are excluded from the cost total."
        )
    return "Cost reported on all receipts."


# ---------------------------------------------------------------------------
# ROI estimate (honestly labelled)
# ---------------------------------------------------------------------------


def roi(
    summary: LedgerSummary,
    *,
    assumed_human_minutes_per_run: float = _ASSUMED_HUMAN_MINUTES_PER_RUN,
) -> RoiEstimate:
    """Return an honestly-labelled ROI *estimate* for *summary*.

    The estimate compares real agent wall-clock time against a transparent
    assumption of how long a human would have taken per run.  It is explicitly
    marked ``est`` and carries its assumption so it can never be mistaken for a
    measured saving.

    Parameters
    ----------
    summary:
        The :class:`LedgerSummary` to estimate ROI for.
    assumed_human_minutes_per_run:
        Transparent assumption: human minutes per run (default
        ``_ASSUMED_HUMAN_MINUTES_PER_RUN``).

    Returns
    -------
    RoiEstimate
        The estimate, with ``estimated=True`` and ``label="est"``.
    """
    agent_wall_minutes = round(summary.total_wall_seconds / 60.0, 2)
    estimated_human_minutes = round(
        summary.run_count * assumed_human_minutes_per_run, 2
    )
    estimated_minutes_saved = round(
        estimated_human_minutes - agent_wall_minutes, 2
    )
    assumption_note = (
        f"est: assumes {assumed_human_minutes_per_run:g} human-min/run; "
        f"compares against {agent_wall_minutes:g} real agent wall-min. "
        "Not a measurement."
    )
    return RoiEstimate(
        estimated=True,
        label="est",
        agent_wall_minutes=agent_wall_minutes,
        assumed_human_minutes_per_run=assumed_human_minutes_per_run,
        estimated_human_minutes=estimated_human_minutes,
        estimated_minutes_saved=estimated_minutes_saved,
        total_cost_usd=summary.total_cost_usd,
        assumption_note=assumption_note,
    )


# ---------------------------------------------------------------------------
# Impure I/O loader (CLI only — never used in tests)
# ---------------------------------------------------------------------------


def load_receipts(
    repo_root: Path,
    *,
    scope: str = "project",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Load receipt dicts from ``.agent-memory/receipts/`` under *repo_root*.

    This is the impure boundary used by the CLI.  Tests should call
    :func:`summarize_receipts` with an injected list instead.

    Parameters
    ----------
    repo_root:
        Repository root containing ``.agent-memory/receipts/``.
    scope:
        ``"today"`` filters to receipts whose timestamp falls on the current
        UTC date; any other value loads all receipts ("project" scope).
    now:
        Injectable current time (defaults to ``datetime.now(UTC)``).  Used only
        for the ``"today"`` date comparison.

    Returns
    -------
    list[dict[str, Any]]
        Receipt dicts.  Malformed or unreadable files are skipped silently.
    """
    receipts_dir = repo_root / ".agent-memory" / "receipts"
    out: list[dict[str, Any]] = []
    if not (receipts_dir.exists() and receipts_dir.is_dir()):
        return out

    today = (now or datetime.now(UTC)).date()

    for entry in sorted(receipts_dir.iterdir()):
        if entry.suffix != ".json" or not entry.name.startswith("run-"):
            continue
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if scope == "today":
            when = _receipt_when(data)
            if when is None or when.astimezone(UTC).date() != today:
                continue
        out.append(data)

    return out


__all__ = [
    "LedgerSummary",
    "RoiEstimate",
    "load_receipts",
    "roi",
    "summarize_receipts",
]
