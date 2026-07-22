"""Stable data contracts for deterministic context retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RetrievalMode(StrEnum):
    """Retrieval strategies supported by the context engine."""

    LOCAL = "local"
    GLOBAL = "global"
    IMPACT = "impact"
    HISTORY = "history"
    DRIFT = "drift"


@dataclass(frozen=True, slots=True)
class Candidate:
    """One caller-provided context candidate and its precomputed signals."""

    id: str
    content: str
    source: str
    token_count: int
    provenance: tuple[str, ...]
    freshness: float = 1.0
    structural_score: float = 0.0
    history_score: float = 0.0
    memory_score: float = 0.0
    semantic_score: float | None = None
    dedupe_key: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("candidate id must not be empty")
        if self.token_count < 0:
            raise ValueError("token_count must be non-negative")
        for name in (
            "freshness",
            "structural_score",
            "history_score",
            "memory_score",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.semantic_score is not None and not 0.0 <= self.semantic_score <= 1.0:
            raise ValueError("semantic_score must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ScoreSignals:
    """Auditable normalized signals used to rank a candidate."""

    lexical: float
    structural: float
    history: float
    memory: float
    semantic: float | None
    freshness: float

    def to_dict(self) -> dict[str, float | None]:
        return {
            "lexical": self.lexical,
            "structural": self.structural,
            "history": self.history,
            "memory": self.memory,
            "semantic": self.semantic,
            "freshness": self.freshness,
        }


@dataclass(frozen=True, slots=True)
class Citation:
    """Stable provenance pointer for selected evidence."""

    candidate_id: str
    source: str
    provenance: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source": self.source,
            "provenance": list(self.provenance),
        }


@dataclass(frozen=True, slots=True)
class Evidence:
    """A packed context item with its ranking explanation."""

    candidate_id: str
    content: str
    token_count: int
    score: float
    context_roi: float
    graph_depth: int | None
    signals: ScoreSignals
    citations: tuple[Citation, ...]
    metadata: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "content": self.content,
            "token_count": self.token_count,
            "score": self.score,
            "context_roi": self.context_roi,
            "graph_depth": self.graph_depth,
            "signals": self.signals.to_dict(),
            "citations": [citation.to_dict() for citation in self.citations],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class Exclusion:
    """Why a candidate was not included in the packet."""

    candidate_id: str
    reason: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"candidate_id": self.candidate_id, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    """Deterministic output of a retrieval plan."""

    query: str
    mode: RetrievalMode
    token_budget: int
    used_tokens: int
    evidence: tuple[Evidence, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    no_op: bool = True
    schema_version: str = field(default="1", init=False)

    def evidence_by_id(self, candidate_id: str) -> Evidence:
        return next(item for item in self.evidence if item.candidate_id == candidate_id)

    def exclusion_for(self, candidate_id: str) -> Exclusion:
        return next(item for item in self.exclusions if item.candidate_id == candidate_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "query": self.query,
            "mode": self.mode.value,
            "token_budget": self.token_budget,
            "used_tokens": self.used_tokens,
            "no_op": self.no_op,
            "evidence": [item.to_dict() for item in self.evidence],
            "exclusions": [item.to_dict() for item in self.exclusions],
        }
