"""Race — pure, offline model/strategy tournament over run receipts.

``onmc race`` answers a narrower question than ``onmc flywheel``: *for a
specific goal, which model actually won?*  It clusters recorded run receipts
whose ``goal`` shares keywords with a query goal, builds a per-model
leaderboard (runs, verified rate, avg cost, avg wall-time) ranked by verified
rate then cost, and declares a tournament winner — or honestly reports
"insufficient data" when the cluster is too thin to trust.

Data source
-----------
Receipts are the same tamper-evident ``RunReceipt`` JSON files written by
``onmc loop`` / ``onmc swarm`` to ``.agent-memory/receipts/`` and read via
:func:`oh_no_my_claudecode.ledger.accounting.load_receipts`.  No new schema.

Honesty constraints (same methodology as ``ledger`` / ``flywheel``)
---------------------------------------------------------------------
- **Null cost is never faked.**  ``avg_cost`` is ``None`` ("n/a") when *no* run
  in a group reported a cost — never a fabricated ``0.0``.
- **Insufficient data is stated, not smoothed over.**  A goal cluster needs at
  least :data:`MIN_VERIFIED_RUNS` *verified* runs before a winner is declared;
  below that, :func:`race` returns a result with ``winner is None`` and an
  explicit ``note`` explaining why.
- **Corrupt / partial receipts are skipped, never crash.**  Missing keys, wrong
  types, or unreadable files are tolerated.
- **No randomness.**  Ranking is a deterministic, total order: verified rate
  descending, then avg cost ascending (unknown cost sorts last), then more runs,
  then model name for a stable final tie-break.

Everything here is pure over an in-memory ``list[dict]`` so it is fully
testable offline.  The only I/O this package performs is reusing
:func:`oh_no_my_claudecode.ledger.accounting.load_receipts`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: Minimum number of *verified* runs a goal cluster needs before a winner is
#: declared. Below this, results are still shown but the winner is withheld.
MIN_VERIFIED_RUNS = 3

#: Stopwords stripped when deriving goal keywords for clustering, mirroring
#: the flywheel's keyword derivation so the two features stay consistent.
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
class ModelRecord:
    """Leaderboard row for one model within a race.

    Fields
    ------
    model:
        Model name; ``"unknown"`` when the receipt did not surface one.
    runs:
        Number of receipts attributed to this model in the cluster.
    verified:
        Number of those receipts with ``verified=True``.
    verified_rate:
        ``verified / runs`` in ``[0.0, 1.0]`` (``0.0`` when ``runs == 0``).
    avg_cost:
        Mean ``cost_usd`` over runs that *reported* a cost, or ``None`` when no
        run in the group reported one — never a fabricated ``0.0``.
    avg_wall_seconds:
        Mean ``wall_seconds`` over all runs in the group (``0.0`` when empty).
    """

    model: str
    runs: int
    verified: int
    verified_rate: float
    avg_cost: float | None
    avg_wall_seconds: float

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict of this row."""
        return {
            "model": self.model,
            "runs": self.runs,
            "verified": self.verified,
            "verified_rate": self.verified_rate,
            "avg_cost": self.avg_cost,
            "avg_wall_seconds": self.avg_wall_seconds,
        }


@dataclass(frozen=True)
class RaceResult:
    """Outcome of one tournament: a ranked leaderboard plus a declared winner.

    Fields
    ------
    query:
        The goal query the cluster was built from, or ``None`` for
        ``onmc race --all`` (no clustering — every receipt included).
    matched_keywords:
        Keywords extracted from ``query`` used to match receipts, or ``[]``
        for the ``--all`` (unclustered) mode.
    total_runs:
        Total receipts in the cluster (all models combined).
    verified_runs:
        Total verified receipts in the cluster.
    leaderboard:
        :class:`ModelRecord` rows, ranked best-first (see :func:`race`).
    winner:
        The winning :class:`ModelRecord`, or ``None`` when the cluster has
        fewer than :data:`MIN_VERIFIED_RUNS` verified runs.
    note:
        Honest, human-readable caveat — always explains why there is no
        winner when ``winner is None``.
    """

    query: str | None
    matched_keywords: list[str]
    total_runs: int
    verified_runs: int
    leaderboard: list[ModelRecord] = field(default_factory=list)
    winner: ModelRecord | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict of the whole result."""
        return {
            "query": self.query,
            "matched_keywords": self.matched_keywords,
            "total_runs": self.total_runs,
            "verified_runs": self.verified_runs,
            "leaderboard": [row.to_dict() for row in self.leaderboard],
            "winner": self.winner.to_dict() if self.winner is not None else None,
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


def goal_keywords(goal: str) -> list[str]:
    """Derive matchable keywords from a goal string.

    Lower-cases, tokenizes on alphanumerics, drops stopwords and words shorter
    than 3 characters, and de-duplicates while preserving first-seen order.
    Shared by both the query side and the receipt side so matching is
    symmetric.
    """
    words = re.findall(r"[a-z0-9]+", goal.lower())
    out: list[str] = []
    for word in words:
        if len(word) < 3 or word in _GOAL_STOPWORDS:
            continue
        if word not in out:
            out.append(word)
    return out


def _avg_cost(cost_sum: float, cost_n: int) -> float | None:
    """Mean cost over runs that reported one, or ``None`` when none did."""
    if cost_n == 0:
        return None
    return round(cost_sum / cost_n, 4)


def _matches_query(receipt_keywords: set[str], query_keywords: list[str]) -> bool:
    """True when a receipt's goal shares at least one keyword with the query."""
    return any(kw in receipt_keywords for kw in query_keywords)


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def cluster_by_goal(
    receipts: list[dict[str, Any]], query: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return receipts whose goal shares a keyword with *query*, plus the
    keywords used to match.

    Pure and deterministic. Receipts that fail to coerce (see
    :func:`_coerce_receipt`) are dropped silently — they can never match
    anyway. Returns ``([], keywords)`` when *query* yields no keywords (all
    stopwords / too short) rather than matching everything by accident.
    """
    query_keywords = goal_keywords(query)
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


# ---------------------------------------------------------------------------
# Leaderboard + tournament
# ---------------------------------------------------------------------------


def _model_sort_key(row: ModelRecord) -> tuple[float, float, int, str]:
    """Deterministic total order: verified rate desc, cost asc (unknown last),
    more runs first, then model name for a final stable tie-break.
    """
    cost_key = row.avg_cost if row.avg_cost is not None else float("inf")
    return (-row.verified_rate, cost_key, -row.runs, row.model)


def build_leaderboard(clean_receipts: list[dict[str, Any]]) -> list[ModelRecord]:
    """Aggregate already-coerced receipt dicts into a ranked leaderboard.

    Expects receipts already run through :func:`_coerce_receipt` (i.e. the
    output of :func:`cluster_by_goal`, or a caller-cleaned list for the
    ``--all`` mode). Pure and deterministic.
    """
    acc: dict[str, dict[str, float]] = {}
    for c in clean_receipts:
        model = str(c["model"])
        bucket = acc.setdefault(
            model,
            {"runs": 0.0, "verified": 0.0, "wall": 0.0, "cost_sum": 0.0, "cost_n": 0.0},
        )
        bucket["runs"] += 1
        bucket["wall"] += float(c["wall_seconds"])
        if c["verified"]:
            bucket["verified"] += 1
        cost = c["cost_usd"]
        if cost is not None:
            bucket["cost_sum"] += float(cost)
            bucket["cost_n"] += 1

    rows: list[ModelRecord] = []
    for model, bucket in acc.items():
        runs = int(bucket["runs"])
        verified = int(bucket["verified"])
        rows.append(
            ModelRecord(
                model=model,
                runs=runs,
                verified=verified,
                verified_rate=round(verified / runs, 4) if runs else 0.0,
                avg_cost=_avg_cost(bucket["cost_sum"], int(bucket["cost_n"])),
                avg_wall_seconds=round(bucket["wall"] / runs, 3) if runs else 0.0,
            )
        )

    rows.sort(key=_model_sort_key)
    return rows


def _build_note(*, total_runs: int, verified_runs: int, winner: ModelRecord | None) -> str:
    """Honest caveat explaining the result, especially the no-winner case."""
    if total_runs == 0:
        return "No matching run receipts found."
    if winner is None:
        return (
            f"Only {verified_runs} verified run(s) in this cluster — need "
            f">= {MIN_VERIFIED_RUNS} verified runs before declaring a winner."
        )
    return f"Winner declared from {verified_runs} verified run(s) across {total_runs} total."


def race(
    receipts: list[dict[str, Any]],
    *,
    query: str | None = None,
) -> RaceResult:
    """Run a tournament over *receipts*, optionally clustered by *query* goal.

    Parameters
    ----------
    receipts:
        Raw receipt dicts (already loaded / filtered by the caller, e.g. via
        :func:`oh_no_my_claudecode.ledger.accounting.load_receipts`).
    query:
        A goal string to cluster on (keyword overlap). When ``None``, every
        coercible receipt is included — the ``onmc race --all`` mode.

    Returns
    -------
    RaceResult
        Ranked leaderboard plus a declared winner, or ``winner=None`` with an
        honest ``note`` when the cluster has fewer than
        :data:`MIN_VERIFIED_RUNS` verified runs (or no matches at all).
    """
    if query is not None:
        clean, matched_keywords = cluster_by_goal(receipts, query)
    else:
        clean = [c for c in (_coerce_receipt(d) for d in receipts) if c is not None]
        matched_keywords = []

    total_runs = len(clean)
    verified_runs = sum(1 for c in clean if c["verified"])
    leaderboard = build_leaderboard(clean)

    winner: ModelRecord | None = None
    if verified_runs >= MIN_VERIFIED_RUNS and leaderboard:
        # The leaderboard is already ranked best-first; the winner is simply
        # the top row, provided the *cluster* (not just one model) clears the
        # verified-runs bar.
        winner = leaderboard[0]

    note = _build_note(total_runs=total_runs, verified_runs=verified_runs, winner=winner)

    return RaceResult(
        query=query,
        matched_keywords=matched_keywords,
        total_runs=total_runs,
        verified_runs=verified_runs,
        leaderboard=leaderboard,
        winner=winner,
        note=note,
    )


__all__ = [
    "MIN_VERIFIED_RUNS",
    "ModelRecord",
    "RaceResult",
    "build_leaderboard",
    "cluster_by_goal",
    "goal_keywords",
    "race",
]
