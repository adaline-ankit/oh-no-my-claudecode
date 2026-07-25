"""Retrieval evaluation runner — scores any retrieve() callable over the frozen dataset.

Usage::

    from oh_no_my_claudecode.retrieval_eval.runner import run_evaluation
    from oh_no_my_claudecode.retrieval_eval.adapters import RecallAdapter

    report = run_evaluation([RecallAdapter()])
    print(report.to_markdown())

The runner is offline, deterministic, and requires no LLM calls.  It measures
latency in wall-clock milliseconds using time.perf_counter.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from oh_no_my_claudecode.retrieval_eval.dataset import EvalCase, RetrievalDataset, load_dataset
from oh_no_my_claudecode.retrieval_eval.metrics import (
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

# Protocol for cases accepted by _score_surface — any object with these fields.
# Both EvalCase and CodeEvalCase satisfy this at runtime.
_CaseLike = Any

# Type alias for a retrieve callable: (query: str, k: int) -> list[ranked_ids]
RetrieveFn = Callable[[str, int], list[str]]

# Default k values for aggregate metrics.
_DEFAULT_K_VALUES = (5, 10)
_MRR_K = 10
_NDCG_K = 10
_PRECISION_K = 5


@dataclass
class QueryResult:
    """Metrics for a single evaluation case."""

    query_id: str
    query: str
    surface: str
    ranked_ids: list[str]
    relevant_ids: set[str]
    graded: dict[str, float]
    latency_ms: float
    context_tokens: int = 0

    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    precision_at_5: float = 0.0
    mrr_at_10: float = 0.0
    ndcg_at_10: float = 0.0

    def __post_init__(self) -> None:
        self.recall_at_5 = recall_at_k(self.ranked_ids, self.relevant_ids, 5)
        self.recall_at_10 = recall_at_k(self.ranked_ids, self.relevant_ids, 10)
        self.precision_at_5 = precision_at_k(self.ranked_ids, self.relevant_ids, 5)
        self.mrr_at_10 = mrr_at_k(self.ranked_ids, self.relevant_ids, 10)
        self.ndcg_at_10 = ndcg_at_k(
            self.ranked_ids,
            self.relevant_ids,
            10,
            graded=self.graded or None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "surface": self.surface,
            "recall@5": round(self.recall_at_5, 4),
            "recall@10": round(self.recall_at_10, 4),
            "p@5": round(self.precision_at_5, 4),
            "mrr@10": round(self.mrr_at_10, 4),
            "ndcg@10": round(self.ndcg_at_10, 4),
            "latency_ms": round(self.latency_ms, 2),
            "context_tokens": self.context_tokens,
            "ranked_ids": self.ranked_ids[:10],
            "relevant_ids": sorted(self.relevant_ids),
        }


def _percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile of a sorted list using linear interpolation."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    idx = (n - 1) * p / 100.0
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return sorted_vals[lo]
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


@dataclass
class SurfaceReport:
    """Aggregate metrics for one retrieval surface."""

    surface_name: str
    query_results: list[QueryResult] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    # Aggregate metrics (computed by finalize())
    mean_recall_at_5: float = 0.0
    mean_recall_at_10: float = 0.0
    mean_precision_at_5: float = 0.0
    mean_mrr_at_10: float = 0.0
    mean_ndcg_at_10: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    mean_context_tokens: float = 0.0
    n_cases: int = 0

    def finalize(self) -> None:
        """Compute aggregate metrics from per-query results."""
        qr = self.query_results
        self.n_cases = len(qr)
        if not qr:
            return
        self.mean_recall_at_5 = sum(q.recall_at_5 for q in qr) / len(qr)
        self.mean_recall_at_10 = sum(q.recall_at_10 for q in qr) / len(qr)
        self.mean_precision_at_5 = sum(q.precision_at_5 for q in qr) / len(qr)
        self.mean_mrr_at_10 = sum(q.mrr_at_10 for q in qr) / len(qr)
        self.mean_ndcg_at_10 = sum(q.ndcg_at_10 for q in qr) / len(qr)
        self.mean_context_tokens = sum(q.context_tokens for q in qr) / len(qr)
        latencies = [q.latency_ms for q in qr]
        self.latency_p50_ms = _percentile(latencies, 50)
        self.latency_p95_ms = _percentile(latencies, 95)

    def to_dict(self) -> dict[str, Any]:
        if self.skipped:
            return {
                "surface": self.surface_name,
                "skipped": True,
                "skip_reason": self.skip_reason,
            }
        return {
            "surface": self.surface_name,
            "n_cases": self.n_cases,
            "recall@5": round(self.mean_recall_at_5, 4),
            "recall@10": round(self.mean_recall_at_10, 4),
            "p@5": round(self.mean_precision_at_5, 4),
            "mrr@10": round(self.mean_mrr_at_10, 4),
            "ndcg@10": round(self.mean_ndcg_at_10, 4),
            "latency_p50_ms": round(self.latency_p50_ms, 2),
            "latency_p95_ms": round(self.latency_p95_ms, 2),
            "context_tokens": round(self.mean_context_tokens, 1),
        }

    def to_markdown_row(self) -> str:
        if self.skipped:
            raw = self.skip_reason
            reason = (raw[:60] + "...") if len(raw) > 60 else raw
            return f"| {self.surface_name} | SKIPPED: {reason} | — | — | — | — | — | — | — | — |"
        return (
            f"| {self.surface_name} "
            f"| {self.n_cases} "
            f"| {self.mean_recall_at_5:.3f} "
            f"| {self.mean_recall_at_10:.3f} "
            f"| {self.mean_precision_at_5:.3f} "
            f"| {self.mean_mrr_at_10:.3f} "
            f"| {self.mean_ndcg_at_10:.3f} "
            f"| {self.latency_p50_ms:.1f}ms "
            f"| {self.latency_p95_ms:.1f}ms "
            f"| {self.mean_context_tokens:.0f} |"
        )


@dataclass
class RetrievalReport:
    """Complete evaluation report over all measured surfaces."""

    dataset_sha: str
    surface_reports: list[SurfaceReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_sha": self.dataset_sha,
            "surfaces": [sr.to_dict() for sr in self.surface_reports],
        }

    def to_markdown(self) -> str:
        lines = [
            "## onmc retrieval-eval baseline report",
            "",
            f"Dataset SHA: `{self.dataset_sha}`",
            "",
            "| Surface | Cases | R@5 | R@10 | P@5 | MRR@10 | nDCG@10 "
            "| Lat p50 | Lat p95 | Ctx tok |",
            "|---------|-------|-----|------|-----|--------|---------|---------|---------|---------|",
        ]
        for sr in self.surface_reports:
            lines.append(sr.to_markdown_row())
        lines.append("")
        lines.append(
            "> Metrics are offline and deterministic.  "
            "Baseline established on the frozen dataset v1.  "
            "Do not edit the dataset to improve scores."
        )
        return "\n".join(lines)


@dataclass
class WinLoss:
    """Per-query win/loss comparison of a candidate surface vs a lexical baseline."""

    baseline_surface: str
    candidate_surface: str
    metric: str
    wins: int = 0
    losses: int = 0
    ties: int = 0
    mean_delta: float = 0.0

    @property
    def n(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def verdict(self) -> str:
        if self.wins > self.losses:
            return f"CANDIDATE BEATS {self.baseline_surface.upper()}"
        if self.losses > self.wins:
            return f"{self.baseline_surface.upper()} >= CANDIDATE"
        return "TIE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline_surface,
            "candidate": self.candidate_surface,
            "metric": self.metric,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "mean_delta": round(self.mean_delta, 4),
            "verdict": self.verdict,
        }


def compare_surfaces(
    baseline: SurfaceReport,
    candidate: SurfaceReport,
    *,
    metric: str = "ndcg_at_10",
    epsilon: float = 1e-9,
) -> WinLoss:
    """Count per-query wins/losses of *candidate* vs *baseline* on *metric*.

    Queries are matched by their query **text** (surfaces use independent
    query-id namespaces, but the same query text across surfaces is the natural
    join key); a query is a win when the candidate's metric exceeds the
    baseline's by more than *epsilon*, a loss when lower, a tie otherwise.
    ``mean_delta`` is the mean (candidate - baseline) over the matched queries.
    Deterministic.
    """
    baseline_by_key = {q.query: q for q in baseline.query_results}
    result = WinLoss(
        baseline_surface=baseline.surface_name,
        candidate_surface=candidate.surface_name,
        metric=metric,
    )
    deltas: list[float] = []
    for cand in candidate.query_results:
        base = baseline_by_key.get(cand.query)
        if base is None:
            continue
        delta = getattr(cand, metric) - getattr(base, metric)
        deltas.append(delta)
        if delta > epsilon:
            result.wins += 1
        elif delta < -epsilon:
            result.losses += 1
        else:
            result.ties += 1
    result.mean_delta = sum(deltas) / len(deltas) if deltas else 0.0
    return result


class BaselineAdapter:
    """Protocol for a retrieval surface adapter.

    Subclass and implement ``surface_name``, ``retrieve``, and optionally
    ``setup`` / ``teardown``.
    """

    surface_name: str = "unknown"

    def setup(self, dataset: RetrievalDataset) -> None:
        """Called once before evaluation begins.  Seed the corpus here."""

    def retrieve(self, query: str, k: int) -> list[str]:
        """Return up to k ranked document IDs for the given query."""
        raise NotImplementedError

    def context_tokens(self, ranked_ids: list[str]) -> int:
        """Estimated context-token cost of packing *ranked_ids*.

        Default: the number of retrieved items (a granularity proxy).  Adapters
        that know their corpus should override with a real token estimate so the
        report's context-token column reflects true budget cost.
        """
        return len(ranked_ids)

    def teardown(self) -> None:
        """Called once after evaluation completes.  Clean up resources."""


def _score_surface(
    adapter: BaselineAdapter,
    cases: list[EvalCase],
    dataset: RetrievalDataset,
    k: int,
) -> SurfaceReport:
    """Run the adapter over all cases and return a SurfaceReport."""
    report = SurfaceReport(surface_name=adapter.surface_name)

    try:
        adapter.setup(dataset)
    except Exception as exc:  # noqa: BLE001
        report.skipped = True
        report.skip_reason = f"setup failed: {exc}"
        return report

    try:
        for case in cases:
            t0 = time.perf_counter()
            try:
                ranked = adapter.retrieve(case.query, k)
            except Exception as exc:  # noqa: BLE001
                ranked = []
                _ = exc  # retrieval failure yields empty result, not a crash

            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            try:
                ctx_tokens = adapter.context_tokens(ranked)
            except Exception:  # noqa: BLE001
                ctx_tokens = len(ranked)
            qr = QueryResult(
                query_id=case.query_id,
                query=case.query,
                surface=case.surface,
                ranked_ids=ranked,
                relevant_ids=set(case.relevant_ids),
                graded=case.graded,
                latency_ms=elapsed_ms,
                context_tokens=ctx_tokens,
            )
            report.query_results.append(qr)
    finally:
        with contextlib.suppress(Exception):
            adapter.teardown()

    report.finalize()
    return report


def run_evaluation(
    adapters: list[BaselineAdapter],
    *,
    k: int = 10,
) -> RetrievalReport:
    """Run the full evaluation harness over all provided adapters.

    Args:
        adapters: List of :class:`BaselineAdapter` instances to evaluate.
        k: Maximum rank cutoff for retrieval (used for all metrics).

    Returns:
        A :class:`RetrievalReport` with per-surface aggregate metrics.
    """
    dataset = load_dataset(verify_sha=True)
    surface_reports: list[SurfaceReport] = []

    for adapter in adapters:
        cases = dataset.cases_for_surface(adapter.surface_name)
        if not cases:
            sr = SurfaceReport(
                surface_name=adapter.surface_name,
                skipped=True,
                skip_reason=f"no cases for surface '{adapter.surface_name}' in dataset",
            )
            surface_reports.append(sr)
            continue
        sr = _score_surface(adapter, cases, dataset, k)
        surface_reports.append(sr)

    return RetrievalReport(
        dataset_sha=dataset.dataset_sha,
        surface_reports=surface_reports,
    )


def run_code_evaluation(
    adapters: list[BaselineAdapter],
    *,
    k: int = 10,
) -> RetrievalReport:
    """Run the evaluation harness over the frozen CODE retrieval split.

    Loads ``datasets/retrieval_code_v1.json`` and scores each adapter against
    its surface (``"code-bm25"`` or ``"code-hybrid"``).  Both
    :class:`~oh_no_my_claudecode.retrieval_eval.code_adapters.CodeLexicalAdapter`
    and
    :class:`~oh_no_my_claudecode.retrieval_eval.code_adapters.CodeHybridAdapter`
    implement the same interface as :class:`BaselineAdapter` and can be passed
    here.

    Args:
        adapters: List of :class:`BaselineAdapter` instances to evaluate.
            Typically ``code_adapters()`` from
            :mod:`oh_no_my_claudecode.retrieval_eval.code_adapters`.
        k: Maximum rank cutoff for retrieval (used for all metrics).

    Returns:
        A :class:`RetrievalReport` with per-surface aggregate metrics,
        dataset_sha set to the code dataset SHA.
    """
    from oh_no_my_claudecode.retrieval_eval.code_dataset import load_code_dataset  # noqa: PLC0415

    code_dataset = load_code_dataset(verify_sha=True)
    surface_reports: list[SurfaceReport] = []

    for adapter in adapters:
        cases = code_dataset.cases_for_surface(adapter.surface_name)
        if not cases:
            sr = SurfaceReport(
                surface_name=adapter.surface_name,
                skipped=True,
                skip_reason=f"no cases for surface '{adapter.surface_name}' in code dataset",
            )
            surface_reports.append(sr)
            continue
        # _score_surface works with any cases duck-typed like EvalCase.
        sr = _score_surface(adapter, cases, code_dataset, k)  # type: ignore[arg-type]
        surface_reports.append(sr)

    return RetrievalReport(
        dataset_sha=code_dataset.dataset_sha,
        surface_reports=surface_reports,
    )
