"""Deterministic query planning for measured repository retrieval.

The planner is deliberately small and inspectable.  It does not predict that a
retrieval technique is good; it decides which techniques are eligible to be
measured for this query while preserving BM25 as the lexical production floor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

_VALID_MODES = frozenset({"bm25", "dense", "hybrid"})
_ERROR_RE = re.compile(
    r"\b(?:error|exception|traceback|failed|failure|errno|panic|segfault)\b|"
    r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)\b",
    re.IGNORECASE,
)
_SYMBOL_RE = re.compile(
    r"(?:`[^`\n]+`)|"
    r"(?:\b[A-Za-z_][A-Za-z0-9_]*(?:(?:::|\.)[A-Za-z_][A-Za-z0-9_]*)+\b)|"
    r"(?:\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b)"
)


class QueryIntent(StrEnum):
    """Stable intent classes that affect candidate-stage eligibility."""

    SYMBOL = "symbol"
    ERROR = "error"
    CONCEPTUAL = "conceptual"


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """Auditable retrieval stages considered for one query."""

    query: str
    intent: QueryIntent
    requested_mode: str
    k: int
    token_budget: int
    baseline_stage: str
    candidate_stages: tuple[str, ...]
    suppressed_stages: tuple[tuple[str, str], ...]
    lexical_floor: bool = True
    schema_version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "query": self.query,
            "intent": self.intent.value,
            "requested_mode": self.requested_mode,
            "k": self.k,
            "token_budget": self.token_budget,
            "baseline_stage": self.baseline_stage,
            "candidate_stages": list(self.candidate_stages),
            "suppressed_stages": [
                {"stage": stage, "reason": reason}
                for stage, reason in self.suppressed_stages
            ],
            "lexical_floor": self.lexical_floor,
        }


def classify_query_intent(query: str) -> QueryIntent:
    """Classify exact diagnostic queries before broader conceptual queries."""
    if _ERROR_RE.search(query):
        return QueryIntent.ERROR
    if _SYMBOL_RE.search(query):
        return QueryIntent.SYMBOL
    return QueryIntent.CONCEPTUAL


def build_query_plan(
    query: str,
    *,
    requested_mode: str,
    k: int,
    token_budget: int,
    dense_available: bool,
    reranker_available: bool,
) -> QueryPlan:
    """Return a deterministic BM25-floor plan for one query.

    Dense and reranking stages are candidates only.  Exact symbol and diagnostic
    queries stay lexical even when optional stages are installed.  Conceptual
    queries may explore installed stages, but runtime selection is a separate
    confidence and promotion decision made by ``HybridRetriever``.
    """
    if requested_mode not in _VALID_MODES:
        raise ValueError(
            f"Unknown mode {requested_mode!r}; expected one of {sorted(_VALID_MODES)}"
        )
    if k < 1:
        raise ValueError("k must be positive")
    if token_budget < 0:
        raise ValueError("token_budget must be non-negative")

    intent = classify_query_intent(query)
    requested_candidates: list[str] = []
    if requested_mode in {"dense", "hybrid"}:
        requested_candidates.append("dense")
    if requested_mode == "hybrid":
        requested_candidates.append("rrf")
    if requested_candidates and reranker_available:
        requested_candidates.append("rerank")

    candidates: list[str] = []
    suppressed: list[tuple[str, str]] = []
    if intent in {QueryIntent.SYMBOL, QueryIntent.ERROR}:
        suppressed.extend(
            (stage, "lexical_dominant_query") for stage in requested_candidates
        )
        if reranker_available and "rerank" not in requested_candidates:
            suppressed.append(("rerank", "lexical_dominant_query"))
    else:
        for stage in requested_candidates:
            if stage in {"dense", "rrf"} and not dense_available:
                suppressed.append((stage, "dependency_unavailable"))
            else:
                candidates.append(stage)
        if requested_candidates and not reranker_available:
            suppressed.append(("rerank", "dependency_unavailable"))

    return QueryPlan(
        query=query,
        intent=intent,
        requested_mode=requested_mode,
        k=k,
        token_budget=token_budget,
        baseline_stage="bm25",
        candidate_stages=tuple(candidates),
        suppressed_stages=tuple(suppressed),
    )


__all__ = [
    "QueryIntent",
    "QueryPlan",
    "build_query_plan",
    "classify_query_intent",
]
