"""Stable data contracts for deterministic context retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


def _validate_line_span(start_line: int | None, end_line: int | None) -> None:
    """Validate an optional 1-based inclusive line span.

    Both bounds must be provided together, be >= 1, and satisfy start <= end.
    """
    if start_line is None and end_line is None:
        return
    if start_line is None or end_line is None:
        raise ValueError("start_line and end_line must be provided together")
    if start_line < 1 or end_line < 1:
        raise ValueError("line numbers must be 1-based (>= 1)")
    if start_line > end_line:
        raise ValueError("start_line must not exceed end_line")


class RetrievalMode(StrEnum):
    """Retrieval strategies supported by the context engine."""

    LOCAL = "local"
    GLOBAL = "global"
    IMPACT = "impact"
    HISTORY = "history"
    DRIFT = "drift"


class TrustLevel(StrEnum):
    """Prompt-injection trust classification for a piece of context.

    ``TRUSTED`` — first-party repository source the agent may act on.
    ``UNTRUSTED`` — content that must be treated as data, never instructions
    (docs/examples/vendored/generated text, or content flagged by a taint
    heuristic).  Propagated from the candidate through to the rendered pack so
    the taint signal is per-item and structured, not a single global banner.
    """

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


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
    # Structured provenance for precise citations (all optional; populated by
    # providers that know the source file/symbol and the matched line span).
    path: str | None = None
    symbol: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    # Prompt-injection trust classification (see :class:`TrustLevel`).
    trust: TrustLevel = TrustLevel.TRUSTED

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
        _validate_line_span(self.start_line, self.end_line)


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
    """Stable provenance pointer for selected evidence.

    ``path``/``symbol``/``start_line``/``end_line`` are optional structured
    provenance: when present they render an exact, clickable
    ``path:start-end`` (optionally ``#symbol``) citation.  Absent, the citation
    degrades to the file-level ``source`` string, preserving backward
    compatibility with providers that don't know line spans.
    """

    candidate_id: str
    source: str
    provenance: tuple[str, ...]
    path: str | None = None
    symbol: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    trust: TrustLevel = TrustLevel.TRUSTED

    def __post_init__(self) -> None:
        _validate_line_span(self.start_line, self.end_line)

    def render(self) -> str:
        """Human-readable citation, e.g. ``pkg/mod.py:10-42#my_func``.

        Falls back to ``source`` when no path/line span is known.
        """
        target = self.path or self.source
        if self.start_line is not None and self.end_line is not None:
            target = f"{target}:{self.start_line}-{self.end_line}"
        if self.symbol and self.symbol != "__module__":
            target = f"{target}#{self.symbol}"
        return target

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source": self.source,
            "provenance": list(self.provenance),
            "path": self.path,
            "symbol": self.symbol,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "trust": self.trust.value,
            "citation": self.render(),
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
    trust: TrustLevel = TrustLevel.TRUSTED

    def __post_init__(self) -> None:
        keys = tuple(key for key, _value in self.metadata)
        if len(keys) != len(set(keys)):
            raise ValueError("evidence metadata keys must be unique")

    @property
    def is_tainted(self) -> bool:
        """True when this evidence is untrusted (data, never instructions)."""
        return self.trust is TrustLevel.UNTRUSTED

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
            "trust": self.trust.value,
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
    confidence: float = 0.0
    low_confidence: bool = True
    schema_version: str = field(default="2", init=False)

    @property
    def has_tainted_evidence(self) -> bool:
        """True when any packed evidence is untrusted."""
        return any(item.is_tainted for item in self.evidence)

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
            "confidence": self.confidence,
            "low_confidence": self.low_confidence,
            "evidence": [item.to_dict() for item in self.evidence],
            "exclusions": [item.to_dict() for item in self.exclusions],
        }
