"""Estimate — pure, offline, pre-run cost/time forecast from run receipts.

``onmc estimate <goal>`` answers a question the other receipt-mining features
don't: *before* you run a loop/swarm, what should you expect it to cost and
take? It clusters recorded run receipts whose ``goal`` shares keywords with
the input goal (reusing the same keyword-overlap approach as
:mod:`oh_no_my_claudecode.race.race` / :mod:`oh_no_my_claudecode.flywheel.analyze`)
and predicts expected cost (median + range), expected wall-clock time,
expected iterations, and a verified-probability — all derived from *actual*
past outcomes for similar work.

Distinct from its siblings
---------------------------
- ``onmc cost``     — historical spend accounting (what you *already* spent).
- ``onmc race``     — model tournament for a goal (which model *won*).
- ``onmc flywheel`` — model win-rates across the whole corpus.
- ``onmc estimate`` — **predictive**: forecasts a *future* run's cost/time/
  outcome from the cluster of similar *past* runs, before you spend anything.

Data source
-----------
Receipts are the same tamper-evident ``RunReceipt`` JSON files written by
``onmc loop`` / ``onmc swarm`` to ``.agent-memory/receipts/`` and read via
:func:`oh_no_my_claudecode.ledger.accounting.load_receipts`. No new schema.

Honesty constraints (same methodology as ``ledger`` / ``race`` / ``flywheel``)
-------------------------------------------------------------------------------
- **Null cost is never faked.** Cost median/range are computed only over runs
  that reported a ``cost_usd``; when none did, cost fields are ``None`` ("n/a")
  — never a fabricated ``0.0``.
- **Insufficient data is stated, not smoothed over.** A goal cluster needs at
  least :data:`MIN_SIMILAR_RUNS` matching runs before a confident estimate is
  produced. Below that, :func:`build_estimate` still shows whatever it found
  but sets ``confidence="low"`` and an explicit ``note`` explaining the
  fallback (falling back further to the *overall* corpus, or to "no history"
  when the corpus itself is empty).
- **Corrupt / partial receipts are skipped, never crash.**
- **No randomness, no clock.** Ranking/statistics are a deterministic total
  order; :func:`build_estimate` takes no wall-clock input.

Everything here is pure over an in-memory ``list[dict]`` so it is fully
testable offline. The only I/O this package performs is reusing
:func:`oh_no_my_claudecode.ledger.accounting.load_receipts` (called by the CLI
layer, never by this module).
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any

#: Minimum number of *similar* (goal-keyword-matched) runs required before an
#: estimate is considered high-confidence. Below this, `build_estimate` still
#: reports numbers from whatever it found but flags low confidence and, when
#: possible, additionally reports overall-corpus averages as a fallback.
MIN_SIMILAR_RUNS = 3

#: Stopwords stripped when deriving goal keywords, mirroring race/flywheel so
#: clustering stays consistent across all receipt-mining features.
_GOAL_STOPWORDS = frozenset(
    {
        "the", "a", "an", "to", "of", "for", "and", "or", "in", "on", "with",
        "add", "fix", "make", "do", "run", "this", "that", "it", "is", "be",
        "into", "from", "by", "at", "as", "so", "we", "i",
    }
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Range:
    """A simple inclusive ``[low, high]`` range, or ``None`` fields when unknown."""

    low: float | None
    high: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"low": self.low, "high": self.high}


@dataclass(frozen=True)
class Estimate:
    """A predictive forecast for a goal, derived from similar past runs.

    Fields
    ------
    goal:
        The input goal string the estimate was requested for.
    model:
        Optional model filter the estimate was conditioned on, or ``None``.
    matched_keywords:
        Keywords extracted from ``goal`` used to match receipts.
    sample_size:
        Number of receipts in the matched cluster actually used to compute
        this estimate (after any ``model`` filter).
    fallback:
        ``"none"`` when the goal cluster itself met :data:`MIN_SIMILAR_RUNS`;
        ``"overall"`` when the goal cluster was too thin and overall-corpus
        averages were substituted instead; ``"empty"`` when there is no
        history at all to estimate from.
    confidence:
        ``"high"`` when ``sample_size >= MIN_SIMILAR_RUNS`` and
        ``fallback == "none"``; ``"low"`` otherwise (including all fallback
        cases).
    expected_cost_usd:
        Median ``cost_usd`` over runs that reported one, or ``None`` when none
        did — never a fabricated ``0.0``.
    cost_range:
        ``[min, max]`` of known ``cost_usd`` values, or ``(None, None)``.
    expected_wall_seconds:
        Median ``wall_seconds`` over the cluster (``None`` when cluster empty).
    wall_seconds_range:
        ``[min, max]`` of ``wall_seconds`` values, or ``(None, None)``.
    expected_iterations:
        Median ``iterations`` over runs that reported one, or ``None``.
    iterations_range:
        ``[min, max]`` of known ``iterations`` values, or ``(None, None)``.
    verified_probability:
        ``verified_count / sample_size`` in ``[0.0, 1.0]``, or ``None`` when
        ``sample_size == 0``.
    note:
        Honest, human-readable caveat — always explains fallback / low
        confidence / empty history.
    """

    goal: str
    model: str | None
    matched_keywords: list[str] = field(default_factory=list)
    sample_size: int = 0
    fallback: str = "none"
    confidence: str = "low"
    expected_cost_usd: float | None = None
    cost_range: Range = field(default_factory=lambda: Range(None, None))
    expected_wall_seconds: float | None = None
    wall_seconds_range: Range = field(default_factory=lambda: Range(None, None))
    expected_iterations: float | None = None
    iterations_range: Range = field(default_factory=lambda: Range(None, None))
    verified_probability: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict of the whole estimate."""
        return {
            "goal": self.goal,
            "model": self.model,
            "matched_keywords": self.matched_keywords,
            "sample_size": self.sample_size,
            "fallback": self.fallback,
            "confidence": self.confidence,
            "expected_cost_usd": self.expected_cost_usd,
            "cost_range": self.cost_range.to_dict(),
            "expected_wall_seconds": self.expected_wall_seconds,
            "wall_seconds_range": self.wall_seconds_range.to_dict(),
            "expected_iterations": self.expected_iterations,
            "iterations_range": self.iterations_range.to_dict(),
            "verified_probability": self.verified_probability,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_receipt(data: Any) -> dict[str, Any] | None:
    """Return a normalised view of one receipt, or ``None`` to skip it.

    Tolerates missing keys and wrong types: anything that cannot be read as a
    usable run is skipped rather than raising.
    """
    if not isinstance(data, dict):
        return None
    try:
        verified = bool(data.get("verified", False))
        wall = float(data.get("wall_seconds", 0.0) or 0.0)
        cost_raw = data.get("cost_usd")
        cost: float | None = float(cost_raw) if cost_raw is not None else None
        iterations_raw = data.get("iterations")
        iterations: int | None = (
            int(iterations_raw) if iterations_raw is not None else None
        )
        model = str(data.get("model") or "unknown")
        goal = str(data.get("goal") or "")
    except (TypeError, ValueError):
        return None
    return {
        "verified": verified,
        "wall_seconds": wall,
        "cost_usd": cost,
        "iterations": iterations,
        "model": model,
        "goal": goal,
    }


def goal_keywords(goal: str) -> list[str]:
    """Derive matchable keywords from a goal string.

    Lower-cases, tokenizes on alphanumerics, drops stopwords and words shorter
    than 3 characters, and de-duplicates while preserving first-seen order.
    Mirrors :func:`oh_no_my_claudecode.race.race.goal_keywords` exactly so
    clustering stays consistent across features.
    """
    words = re.findall(r"[a-z0-9]+", goal.lower())
    out: list[str] = []
    for word in words:
        if len(word) < 3 or word in _GOAL_STOPWORDS:
            continue
        if word not in out:
            out.append(word)
    return out


def _matches_query(receipt_keywords: set[str], query_keywords: list[str]) -> bool:
    """True when a receipt's goal shares at least one keyword with the query."""
    return any(kw in receipt_keywords for kw in query_keywords)


def cluster_by_goal(
    receipts: list[dict[str, Any]], goal: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return coerced receipts whose goal shares a keyword with *goal*, plus
    the keywords used to match.

    Pure and deterministic. Receipts that fail to coerce are dropped silently.
    Returns ``([], [])`` when *goal* yields no keywords (all stopwords / too
    short) rather than matching everything by accident.
    """
    query_keywords = goal_keywords(goal)
    if not query_keywords:
        return [], []

    matched: list[dict[str, Any]] = []
    for data in receipts:
        clean = _coerce_receipt(data)
        if clean is None:
            continue
        receipt_keywords = set(goal_keywords(clean["goal"]))
        if _matches_query(receipt_keywords, query_keywords):
            matched.append(clean)
    return matched, query_keywords


def _median(values: list[float]) -> float | None:
    """Median of *values*, or ``None`` when empty."""
    if not values:
        return None
    return round(statistics.median(values), 4)


def _range(values: list[float]) -> Range:
    """``[min, max]`` of *values*, or ``(None, None)`` when empty."""
    if not values:
        return Range(None, None)
    return Range(round(min(values), 4), round(max(values), 4))


# ---------------------------------------------------------------------------
# Forecast statistics over an already-clustered/filtered set of receipts
# ---------------------------------------------------------------------------


def _forecast_stats(clean: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute median/range/probability stats over *clean* coerced receipts."""
    sample_size = len(clean)
    costs = [c["cost_usd"] for c in clean if c["cost_usd"] is not None]
    walls = [c["wall_seconds"] for c in clean]
    iters = [float(c["iterations"]) for c in clean if c["iterations"] is not None]
    verified_count = sum(1 for c in clean if c["verified"])

    return {
        "sample_size": sample_size,
        "expected_cost_usd": _median(costs),
        "cost_range": _range(costs),
        "expected_wall_seconds": _median(walls),
        "wall_seconds_range": _range(walls),
        "expected_iterations": _median(iters),
        "iterations_range": _range(iters),
        "verified_probability": (
            round(verified_count / sample_size, 4) if sample_size else None
        ),
    }


def _filter_by_model(clean: list[dict[str, Any]], model: str | None) -> list[dict[str, Any]]:
    """Keep only receipts matching *model* (case-sensitive, exact), or all when None."""
    if model is None:
        return clean
    return [c for c in clean if c["model"] == model]


def _build_note(
    *, fallback: str, sample_size: int, model: str | None, cost_known: int
) -> str:
    """Honest caveat explaining the estimate's basis and confidence."""
    if fallback == "empty":
        return "No run receipts found at all — run `onmc loop` or `onmc swarm` first."
    model_suffix = f" for model '{model}'" if model else ""
    if fallback == "overall":
        return (
            f"Not enough similar history{model_suffix} (< {MIN_SIMILAR_RUNS} matching "
            "runs) — showing overall averages across all recorded runs instead."
        )
    if sample_size < MIN_SIMILAR_RUNS:
        return (
            f"Only {sample_size} similar run(s){model_suffix} — too few to trust "
            f"(need >= {MIN_SIMILAR_RUNS}); numbers shown are from this thin sample."
        )
    if cost_known == 0:
        return (
            "ESTIMATE from historical data: cost is n/a (no matching run reported "
            "cost_usd) — wall-time and verified-probability are still real."
        )
    if cost_known < sample_size:
        return (
            f"ESTIMATE from historical data: cost known for {cost_known} of "
            f"{sample_size} similar runs; median/range cover only those."
        )
    return f"ESTIMATE from historical data: based on {sample_size} similar past run(s)."


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def build_estimate(
    receipts: list[dict[str, Any]],
    goal: str,
    model: str | None = None,
) -> Estimate:
    """Build a predictive :class:`Estimate` for *goal* from historical *receipts*.

    Parameters
    ----------
    receipts:
        Raw receipt dicts (already loaded by the caller, e.g. via
        :func:`oh_no_my_claudecode.ledger.accounting.load_receipts`).
    goal:
        The goal to forecast a run for. Clustered against past receipts by
        keyword overlap (see :func:`cluster_by_goal`).
    model:
        Optional model name to condition the estimate on — only receipts
        whose ``model`` field exactly matches are used (applied within the
        matched cluster, and within the overall-corpus fallback).

    Returns
    -------
    Estimate
        Deterministic forecast. When the goal cluster has fewer than
        :data:`MIN_SIMILAR_RUNS` matching receipts (after any ``model``
        filter), falls back to overall-corpus averages (still filtered by
        ``model`` if given) and marks ``fallback="overall"``,
        ``confidence="low"``. When there is no history at all, returns an
        all-``None`` estimate with ``fallback="empty"``.
    """
    all_clean = [c for c in (_coerce_receipt(d) for d in receipts) if c is not None]
    all_clean = _filter_by_model(all_clean, model)

    if not all_clean:
        return Estimate(
            goal=goal,
            model=model,
            matched_keywords=[],
            sample_size=0,
            fallback="empty",
            confidence="low",
            note=_build_note(fallback="empty", sample_size=0, model=model, cost_known=0),
        )

    matched, matched_keywords = cluster_by_goal(receipts, goal)
    matched = _filter_by_model(matched, model)

    if len(matched) >= MIN_SIMILAR_RUNS:
        stats = _forecast_stats(matched)
        cost_known = sum(1 for c in matched if c["cost_usd"] is not None)
        return Estimate(
            goal=goal,
            model=model,
            matched_keywords=matched_keywords,
            sample_size=stats["sample_size"],
            fallback="none",
            confidence="high",
            expected_cost_usd=stats["expected_cost_usd"],
            cost_range=stats["cost_range"],
            expected_wall_seconds=stats["expected_wall_seconds"],
            wall_seconds_range=stats["wall_seconds_range"],
            expected_iterations=stats["expected_iterations"],
            iterations_range=stats["iterations_range"],
            verified_probability=stats["verified_probability"],
            note=_build_note(
                fallback="none",
                sample_size=stats["sample_size"],
                model=model,
                cost_known=cost_known,
            ),
        )

    # Not enough similar history: fall back to the overall corpus (still
    # honestly labelled). If the overall corpus is *itself* too thin, the
    # plainer "too few" wording is more specific than the fallback wording,
    # so _build_note is given fallback="none" in that case even though the
    # Estimate's own `fallback` field still records "overall" (we did in fact
    # widen the sample beyond the goal cluster).
    stats = _forecast_stats(all_clean)
    cost_known = sum(1 for c in all_clean if c["cost_usd"] is not None)
    note_fallback = "overall" if len(all_clean) >= MIN_SIMILAR_RUNS else "none"
    note = _build_note(
        fallback=note_fallback,
        sample_size=stats["sample_size"],
        model=model,
        cost_known=cost_known,
    )

    return Estimate(
        goal=goal,
        model=model,
        matched_keywords=matched_keywords,
        sample_size=stats["sample_size"],
        fallback="overall",
        confidence="low",
        expected_cost_usd=stats["expected_cost_usd"],
        cost_range=stats["cost_range"],
        expected_wall_seconds=stats["expected_wall_seconds"],
        wall_seconds_range=stats["wall_seconds_range"],
        expected_iterations=stats["expected_iterations"],
        iterations_range=stats["iterations_range"],
        verified_probability=stats["verified_probability"],
        note=note,
    )


# ---------------------------------------------------------------------------
# Rendering (plain text — the CLI layer decides whether to use Rich instead)
# ---------------------------------------------------------------------------


def _fmt_cost(cost: float | None) -> str:
    """Render a cost as ``$X.XXXX`` or ``n/a`` — never a fabricated number."""
    return "n/a" if cost is None else f"${cost:.4f}"


def _fmt_range(rng: Range, *, unit: str = "", money: bool = False) -> str:
    """Render a :class:`Range` as ``low - high<unit>`` or ``n/a`` when unknown."""
    if rng.low is None or rng.high is None:
        return "n/a"
    if money:
        return f"${rng.low:.4f} - ${rng.high:.4f}"
    return f"{rng.low:g}{unit} - {rng.high:g}{unit}"


def render_text(estimate: Estimate) -> str:
    """Render *estimate* as a plain-text report (no Rich dependency).

    Every number is explicitly labelled as an ESTIMATE derived from
    historical data, per the feature contract.
    """
    lines = [
        "",
        f"  onmc estimate — '{estimate.goal}'"
        + (f" (model: {estimate.model})" if estimate.model else ""),
        "  ESTIMATE from historical data — not a guarantee",
        "",
    ]

    if estimate.fallback == "empty":
        lines.append("  No run history found at all.")
        lines.append(f"  note: {estimate.note}")
        lines.append("")
        return "\n".join(lines)

    if estimate.matched_keywords:
        lines.append(f"  matched keywords: {', '.join(estimate.matched_keywords)}")
    basis = {
        "none": "similar past runs",
        "overall": "overall corpus (fallback — too few similar runs)",
    }.get(estimate.fallback, "similar past runs")
    lines.append(f"  sample: {estimate.sample_size} run(s) — basis: {basis}")
    lines.append(f"  confidence: {estimate.confidence}")
    lines.append("")
    lines.append(f"  expected cost:        {_fmt_cost(estimate.expected_cost_usd)}")
    lines.append(f"  cost range:           {_fmt_range(estimate.cost_range, money=True)}")
    ew = estimate.expected_wall_seconds
    lines.append(f"  expected wall time:   {'n/a' if ew is None else f'{ew:g}s'}")
    lines.append(f"  wall time range:      {_fmt_range(estimate.wall_seconds_range, unit='s')}")
    ei = estimate.expected_iterations
    lines.append(f"  expected iterations:  {'n/a' if ei is None else f'{ei:g}'}")
    lines.append(f"  iterations range:     {_fmt_range(estimate.iterations_range)}")
    vp = estimate.verified_probability
    lines.append(
        f"  probability verified: {'n/a' if vp is None else f'{vp:.0%}'}"
    )
    lines.append("")
    lines.append(f"  note: {estimate.note}")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "MIN_SIMILAR_RUNS",
    "Estimate",
    "Range",
    "build_estimate",
    "cluster_by_goal",
    "goal_keywords",
    "render_text",
]
