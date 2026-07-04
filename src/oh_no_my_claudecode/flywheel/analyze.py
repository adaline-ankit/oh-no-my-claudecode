"""Flywheel analysis — pure, offline aggregation over run receipts.

The self-improvement flywheel
-----------------------------
onmc uniquely holds *verified* trajectories: every ``onmc loop`` / ``onmc
swarm`` run writes a tamper-evident :class:`~oh_no_my_claudecode.loop.receipt.RunReceipt`
recording which model ran, whether the run was ``verified`` (converged AND the
verifier passed), the cost, and the wall-clock time.  No other tool has
verified-*outcome* data keyed to the approach that produced it.

This module mines that corpus to answer: **which approaches actually win?**  It
aggregates receipts by model (and by goal keyword) and computes a verified
success rate per group, so ``onmc flywheel`` can recommend the model that has
historically delivered verified results for work like yours.

Honesty constraints (inherited from the ledger's methodology)
-------------------------------------------------------------
- **Null cost is never faked.**  A receipt with ``cost_usd is None`` contributes
  nothing to the cost total and is counted separately; ``avg_cost`` is ``None``
  ("n/a") when *no* run in a group reported a cost — never ``0.0``.
- **Insufficient data is stated, not papered over.**  With fewer than
  :data:`MIN_SAMPLES` total runs, :func:`recommend` returns a single explicit
  "insufficient data" line rather than a confident-sounding recommendation
  drawn from noise.
- **Corrupt / partial receipts are skipped, never crash.**  Missing keys,
  wrong types, or unreadable files are tolerated.

All functions here are pure over an in-memory ``list[dict]`` so they can be
unit-tested offline.  The only I/O is :func:`load_trajectories`, a thin wrapper
that reuses the ledger's on-disk receipt reader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from oh_no_my_claudecode.ledger.accounting import load_receipts

#: Minimum total verified-or-not runs before :func:`recommend` will offer a
#: model recommendation.  Below this, the sample is too small to trust.
MIN_SAMPLES = 3

#: Stopwords stripped when deriving goal keywords, so groupings key on the
#: meaningful verb/noun of a goal rather than filler.
_GOAL_STOPWORDS = frozenset(
    {
        "the", "a", "an", "to", "of", "for", "and", "or", "in", "on", "with",
        "add", "fix", "make", "do", "run", "this", "that", "it", "is", "be",
        "into", "from", "by", "at", "as", "so", "we", "i",
    }
)

#: How many leading goal keywords to derive per trajectory.
_GOAL_KEYWORDS_PER_GOAL = 3


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelStat:
    """Verified-outcome statistics for one model (or "unknown").

    Fields
    ------
    model:
        Model name; ``"unknown"`` when the receipt did not surface one.
    runs:
        Number of trajectories attributed to this model.
    verified:
        Number of those trajectories with ``verified=True``.
    verified_rate:
        ``verified / runs`` in ``[0.0, 1.0]`` (0.0 when ``runs == 0``).
    avg_cost:
        Mean ``cost_usd`` over runs that *reported* a cost, or ``None`` when no
        run in the group reported one — never a fabricated ``0.0``.
    avg_wall:
        Mean ``wall_seconds`` over all runs in the group (0.0 when empty).
    """

    model: str
    runs: int
    verified: int
    verified_rate: float
    avg_cost: float | None
    avg_wall: float


@dataclass(frozen=True)
class KeywordStat:
    """Verified-outcome statistics for one goal keyword.

    Same shape as :class:`ModelStat` but keyed on a goal keyword, plus the
    single model that verified most often for goals containing this keyword
    (``best_model`` / ``best_model_verified`` / ``best_model_runs``) — the
    basis for the "for goals like X, use model Y" recommendation.
    """

    keyword: str
    runs: int
    verified: int
    verified_rate: float
    avg_cost: float | None
    avg_wall: float
    best_model: str | None = None
    best_model_verified: int = 0
    best_model_runs: int = 0
    best_model_avg_cost: float | None = None


@dataclass(frozen=True)
class FlywheelReport:
    """Aggregated verified-outcome report over a trajectory corpus.

    Fields
    ------
    total:
        Total valid trajectories included.
    verified_total:
        Number of those that were ``verified=True``.
    by_model:
        Per-model :class:`ModelStat`, ranked best-first (see :func:`summarize`).
    by_goal_keyword:
        Per-keyword :class:`KeywordStat`, ranked by run volume then rate.
    best:
        The winning :class:`ModelStat` (highest verified rate among models with
        enough samples), or ``None`` when no model qualifies.
    worst:
        The lowest-ranked qualifying :class:`ModelStat`, or ``None``.
    note:
        Honest caveat about cost coverage / sample size.
    """

    total: int
    verified_total: int
    by_model: list[ModelStat] = field(default_factory=list)
    by_goal_keyword: list[KeywordStat] = field(default_factory=list)
    best: ModelStat | None = None
    worst: ModelStat | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict of the whole report."""

        def _model(stat: ModelStat) -> dict[str, Any]:
            return {
                "model": stat.model,
                "runs": stat.runs,
                "verified": stat.verified,
                "verified_rate": stat.verified_rate,
                "avg_cost": stat.avg_cost,
                "avg_wall": stat.avg_wall,
            }

        def _keyword(stat: KeywordStat) -> dict[str, Any]:
            return {
                "keyword": stat.keyword,
                "runs": stat.runs,
                "verified": stat.verified,
                "verified_rate": stat.verified_rate,
                "avg_cost": stat.avg_cost,
                "avg_wall": stat.avg_wall,
                "best_model": stat.best_model,
                "best_model_verified": stat.best_model_verified,
                "best_model_runs": stat.best_model_runs,
                "best_model_avg_cost": stat.best_model_avg_cost,
            }

        return {
            "total": self.total,
            "verified_total": self.verified_total,
            "by_model": [_model(s) for s in self.by_model],
            "by_goal_keyword": [_keyword(s) for s in self.by_goal_keyword],
            "best": _model(self.best) if self.best else None,
            "worst": _model(self.worst) if self.worst else None,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_receipt(data: Any) -> dict[str, Any] | None:
    """Return a normalised view of one receipt, or ``None`` to skip it.

    Tolerates missing keys and wrong types: anything that cannot be read as a
    usable trajectory is skipped rather than raising.
    """
    if not isinstance(data, dict):
        return None
    try:
        verified = bool(data.get("verified", False))
        wall = float(data.get("wall_seconds", 0.0) or 0.0)
        cost_raw = data.get("cost_usd")
        cost: float | None = float(cost_raw) if cost_raw is not None else None
        model = str(data.get("model") or "unknown")
        goal = str(data.get("goal") or "")
    except (TypeError, ValueError):
        return None
    return {
        "verified": verified,
        "wall_seconds": wall,
        "cost_usd": cost,
        "model": model,
        "goal": goal,
    }


def _goal_keywords(goal: str) -> list[str]:
    """Derive up to :data:`_GOAL_KEYWORDS_PER_GOAL` keywords from a goal string."""
    words = re.findall(r"[a-z0-9]+", goal.lower())
    out: list[str] = []
    for word in words:
        if len(word) < 3 or word in _GOAL_STOPWORDS:
            continue
        if word not in out:
            out.append(word)
        if len(out) >= _GOAL_KEYWORDS_PER_GOAL:
            break
    return out


def _empty_keyword_bucket() -> dict[str, Any]:
    """Fresh per-keyword accumulator (typed as ``Any`` so nested dicts survive)."""
    return {
        "runs": 0,
        "verified": 0,
        "wall": 0.0,
        "cost_sum": 0.0,
        "cost_n": 0,
        # per-model verified tallies within this keyword
        "models": {},
    }


def _avg_cost(cost_sum: float, cost_n: int) -> float | None:
    """Mean cost over runs that reported one, or ``None`` when none did."""
    if cost_n == 0:
        return None
    return round(cost_sum / cost_n, 4)


# ---------------------------------------------------------------------------
# Pure aggregation
# ---------------------------------------------------------------------------


def summarize(trajectories: list[dict[str, Any]]) -> FlywheelReport:
    """Aggregate *trajectories* into a :class:`FlywheelReport`.

    Pure and deterministic.  Groups by model and by goal keyword, computing a
    verified rate, honest average cost (``None`` when unknown), and average
    wall-time for each group.  Models are ranked best-first by verified rate,
    tie-broken by run volume then lower average cost.

    Invalid / partial receipts are skipped by :func:`_coerce_receipt`.
    """
    clean = [c for c in (_coerce_receipt(d) for d in trajectories) if c is not None]
    total = len(clean)
    verified_total = sum(1 for c in clean if c["verified"])

    # --- by model ---------------------------------------------------------
    model_acc: dict[str, dict[str, float]] = {}
    for c in clean:
        acc = model_acc.setdefault(
            c["model"],
            {"runs": 0.0, "verified": 0.0, "wall": 0.0, "cost_sum": 0.0, "cost_n": 0.0},
        )
        acc["runs"] += 1
        acc["wall"] += c["wall_seconds"]
        if c["verified"]:
            acc["verified"] += 1
        if c["cost_usd"] is not None:
            acc["cost_sum"] += c["cost_usd"]
            acc["cost_n"] += 1

    by_model: list[ModelStat] = []
    for model, acc in model_acc.items():
        runs = int(acc["runs"])
        verified = int(acc["verified"])
        by_model.append(
            ModelStat(
                model=model,
                runs=runs,
                verified=verified,
                verified_rate=round(verified / runs, 4) if runs else 0.0,
                avg_cost=_avg_cost(acc["cost_sum"], int(acc["cost_n"])),
                avg_wall=round(acc["wall"] / runs, 3) if runs else 0.0,
            )
        )

    # Rank: highest verified rate, then most runs, then cheapest (known cost).
    def _model_sort_key(s: ModelStat) -> tuple[float, int, float]:
        cost_key = s.avg_cost if s.avg_cost is not None else float("inf")
        return (-s.verified_rate, -s.runs, cost_key)

    by_model.sort(key=_model_sort_key)

    # --- by goal keyword --------------------------------------------------
    kw_acc: dict[str, dict[str, Any]] = {}
    for c in clean:
        for kw in _goal_keywords(c["goal"]):
            acc = kw_acc.setdefault(kw, _empty_keyword_bucket())
            acc["runs"] += 1
            acc["wall"] += c["wall_seconds"]
            if c["verified"]:
                acc["verified"] += 1
            if c["cost_usd"] is not None:
                acc["cost_sum"] += c["cost_usd"]
                acc["cost_n"] += 1
            models = cast("dict[str, dict[str, Any]]", acc["models"])
            m = models.setdefault(
                c["model"], {"runs": 0, "verified": 0, "cost_sum": 0.0, "cost_n": 0}
            )
            m["runs"] += 1
            if c["verified"]:
                m["verified"] += 1
            if c["cost_usd"] is not None:
                m["cost_sum"] += c["cost_usd"]
                m["cost_n"] += 1

    by_goal_keyword: list[KeywordStat] = []
    for kw, acc in kw_acc.items():
        runs = int(acc["runs"])
        verified = int(acc["verified"])
        best_model, bm = _best_model_for_keyword(
            cast("dict[str, dict[str, Any]]", acc["models"])
        )
        by_goal_keyword.append(
            KeywordStat(
                keyword=kw,
                runs=runs,
                verified=verified,
                verified_rate=round(verified / runs, 4) if runs else 0.0,
                avg_cost=_avg_cost(float(acc["cost_sum"]), int(acc["cost_n"])),
                avg_wall=round(float(acc["wall"]) / runs, 3) if runs else 0.0,
                best_model=best_model,
                best_model_verified=bm["verified"] if bm else 0,
                best_model_runs=bm["runs"] if bm else 0,
                best_model_avg_cost=(
                    _avg_cost(bm["cost_sum"], bm["cost_n"]) if bm else None
                ),
            )
        )

    by_goal_keyword.sort(key=lambda s: (-s.runs, -s.verified_rate, s.keyword))

    # --- best / worst (only among models with enough samples) -------------
    qualifying = [s for s in by_model if s.runs >= MIN_SAMPLES]
    best = qualifying[0] if qualifying else None
    worst = qualifying[-1] if len(qualifying) > 1 else None

    note = _build_note(clean)

    return FlywheelReport(
        total=total,
        verified_total=verified_total,
        by_model=by_model,
        by_goal_keyword=by_goal_keyword,
        best=best,
        worst=worst,
        note=note,
    )


def _best_model_for_keyword(
    models: dict[str, dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None]:
    """Pick the model with the most verified runs for a keyword group.

    Tie-break: more verified, then higher verified rate, then more runs.
    Returns ``(None, None)`` when there are no models.
    """
    best_name: str | None = None
    best_bucket: dict[str, Any] | None = None
    best_key: tuple[int, float, int] = (-1, -1.0, -1)
    for name, bucket in sorted(models.items()):
        rate = bucket["verified"] / bucket["runs"] if bucket["runs"] else 0.0
        key = (bucket["verified"], rate, bucket["runs"])
        if key > best_key:
            best_key = key
            best_name = name
            best_bucket = bucket
    return best_name, best_bucket


def _build_note(clean: list[dict[str, Any]]) -> str:
    """Honest caveat about sample size and cost coverage."""
    total = len(clean)
    if total == 0:
        return "No run receipts found — run `onmc loop` or `onmc swarm` first."
    cost_known = sum(1 for c in clean if c["cost_usd"] is not None)
    if total < MIN_SAMPLES:
        return (
            f"Only {total} run(s) recorded — too few to draw model conclusions "
            f"(need >= {MIN_SAMPLES})."
        )
    if cost_known == 0:
        return (
            "Cost is n/a — no receipt reported cost_usd. Verified-rate and "
            "wall-time are real; recommendations rank on verified outcome."
        )
    if cost_known < total:
        return (
            f"Cost is partial — {total - cost_known} of {total} runs had no "
            "cost_usd; averages cover only runs that reported a cost."
        )
    return "Cost reported on all runs."


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


def _fmt_cost(cost: float | None) -> str:
    """Render a cost as ``$X.XXXX`` or ``n/a`` — never a fabricated number."""
    return "n/a" if cost is None else f"${cost:.4f}"


def recommend(report: FlywheelReport) -> list[str]:
    """Return ranked, human-readable recommendations from *report*.

    Below :data:`MIN_SAMPLES` total runs, returns a single explicit
    "insufficient data" line.  Otherwise leads with the overall best model, then
    surfaces per-goal-keyword winners so callers see "for goals like X, model Y
    verified N/M at $Z".
    """
    if report.total < MIN_SAMPLES:
        return [f"insufficient data ({report.total} runs) — need >= {MIN_SAMPLES} to recommend"]

    out: list[str] = []

    if report.best is not None:
        b = report.best
        out.append(
            f"overall: prefer {b.model} — verified {b.verified}/{b.runs} "
            f"({b.verified_rate:.0%}) at avg {_fmt_cost(b.avg_cost)}/run"
        )
    else:
        out.append(
            f"no single model has >= {MIN_SAMPLES} runs yet — "
            "keep running to build a verified track record"
        )

    if (
        report.best is not None
        and report.worst is not None
        and report.worst.model != report.best.model
    ):
        w = report.worst
        out.append(
            f"avoid: {w.model} — verified only {w.verified}/{w.runs} "
            f"({w.verified_rate:.0%})"
        )

    # Per-goal-keyword winners (only keywords with a verified winner and >1 run).
    for kw in report.by_goal_keyword:
        if kw.runs < 2 or kw.best_model is None or kw.best_model_verified == 0:
            continue
        out.append(
            f"for goals like '{kw.keyword}', use {kw.best_model} — verified "
            f"{kw.best_model_verified}/{kw.best_model_runs} at "
            f"{_fmt_cost(kw.best_model_avg_cost)}"
        )
        if len(out) >= 8:
            break

    return out


# ---------------------------------------------------------------------------
# Impure I/O loader (CLI only — reuses the ledger's receipt reader)
# ---------------------------------------------------------------------------


def load_trajectories(repo_root: Path) -> list[dict[str, Any]]:
    """Load all run-receipt trajectory dicts under *repo_root*.

    Thin, impure wrapper that reuses the ledger's on-disk receipt reader
    (:func:`oh_no_my_claudecode.ledger.accounting.load_receipts`) so there is a
    single source of truth for the receipt directory layout and skip-on-corrupt
    behaviour.  Tests inject lists into :func:`summarize` directly instead.
    """
    return load_receipts(repo_root, scope="project")
