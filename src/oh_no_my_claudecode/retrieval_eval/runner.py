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
        }

    def to_markdown_row(self) -> str:
        if self.skipped:
            raw = self.skip_reason
            reason = (raw[:60] + "...") if len(raw) > 60 else raw
            return f"| {self.surface_name} | SKIPPED: {reason} | — | — | — | — | — | — | — |"
        return (
            f"| {self.surface_name} "
            f"| {self.n_cases} "
            f"| {self.mean_recall_at_5:.3f} "
            f"| {self.mean_recall_at_10:.3f} "
            f"| {self.mean_precision_at_5:.3f} "
            f"| {self.mean_mrr_at_10:.3f} "
            f"| {self.mean_ndcg_at_10:.3f} "
            f"| {self.latency_p50_ms:.1f}ms "
            f"| {self.latency_p95_ms:.1f}ms |"
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
            "| Surface | Cases | R@5 | R@10 | P@5 | MRR@10 | nDCG@10 | Lat p50 | Lat p95 |",
            "|---------|-------|-----|------|-----|--------|---------|---------|---------|",
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
            qr = QueryResult(
                query_id=case.query_id,
                query=case.query,
                surface=case.surface,
                ranked_ids=ranked,
                relevant_ids=set(case.relevant_ids),
                graded=case.graded,
                latency_ms=elapsed_ms,
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
