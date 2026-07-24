"""Deterministic hybrid retrieval, graph expansion, and token packing."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.context_engine.models import (
    Candidate,
    Citation,
    Evidence,
    EvidencePacket,
    Exclusion,
    RetrievalMode,
    ScoreSignals,
)
from oh_no_my_claudecode.context_engine.providers import CandidateProvider, GraphProvider

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

_WEIGHTS: Mapping[RetrievalMode, tuple[float, float, float, float, float]] = {
    RetrievalMode.LOCAL: (0.65, 0.20, 0.03, 0.07, 0.05),
    RetrievalMode.GLOBAL: (0.25, 0.15, 0.15, 0.30, 0.15),
    RetrievalMode.IMPACT: (0.20, 0.60, 0.10, 0.05, 0.05),
    RetrievalMode.HISTORY: (0.15, 0.05, 0.65, 0.10, 0.05),
    RetrievalMode.DRIFT: (0.30, 0.35, 0.10, 0.15, 0.10),
}


@dataclass(frozen=True, slots=True)
class PlannerConfig:
    """Bounds and quality gates for context planning."""

    min_context_roi: float = 0.005
    min_freshness: float = 0.2
    max_graph_depth: int = 2
    max_graph_nodes: int = 32
    freshness_weight: float = 0.2
    min_confidence: float = 0.0
    utility_first: bool = False

    def __post_init__(self) -> None:
        if self.min_context_roi < 0:
            raise ValueError("min_context_roi must be non-negative")
        if not 0.0 <= self.min_freshness <= 1.0:
            raise ValueError("min_freshness must be between 0 and 1")
        if self.max_graph_depth < 0 or self.max_graph_nodes < 1:
            raise ValueError("graph bounds must be non-negative and non-zero")
        if not 0.0 <= self.freshness_weight <= 1.0:
            raise ValueError("freshness_weight must be between 0 and 1")
        if self.min_confidence < 0:
            raise ValueError("min_confidence must be non-negative")


@dataclass(frozen=True, slots=True)
class _Ranked:
    candidate: Candidate
    score: float
    roi: float
    depth: int | None
    signals: ScoreSignals
    citations: tuple[Citation, ...]


class ContextEngine:
    """Plans minimal, cited context from injected or directly supplied candidates."""

    def __init__(
        self,
        config: PlannerConfig | None = None,
        *,
        candidate_providers: Sequence[CandidateProvider] = (),
        graph_provider: GraphProvider | None = None,
    ) -> None:
        self.config = config or PlannerConfig()
        self.candidate_providers = tuple(candidate_providers)
        self.graph_provider = graph_provider

    def plan(
        self,
        query: str,
        *,
        candidates: Iterable[Candidate] = (),
        mode: RetrievalMode | str = RetrievalMode.LOCAL,
        token_budget: int,
    ) -> EvidencePacket:
        """Rank, expand, deduplicate, and pack candidates into a stable packet."""
        resolved_mode = RetrievalMode(mode)
        if token_budget < 0:
            raise ValueError("token_budget must be non-negative")

        supplied = list(candidates)
        for provider in self.candidate_providers:
            supplied.extend(provider.candidates(query, resolved_mode))
        ordered = _unique_candidates(sorted(supplied, key=_candidate_order))

        exclusions: dict[str, Exclusion] = {}
        valid: dict[str, Candidate] = {}
        for item in ordered:
            if not item.provenance:
                exclusions[item.id] = Exclusion(item.id, "missing_provenance")
                continue
            if item.freshness < self.config.min_freshness:
                exclusions[item.id] = Exclusion(item.id, "stale")
                continue
            valid[item.id] = item

        depths = self._scope(query, resolved_mode, valid)
        scope_reason = (
            "graph_scope"
            if resolved_mode in {RetrievalMode.IMPACT, RetrievalMode.DRIFT}
            else "mode_scope"
        )
        for candidate_id in sorted(set(valid) - set(depths)):
            exclusions[candidate_id] = Exclusion(candidate_id, scope_reason)

        deduped, duplicate_citations = self._dedupe(
            [valid[candidate_id] for candidate_id in sorted(depths)], query, resolved_mode, depths
        )
        for duplicate_id, winner_id in sorted(duplicate_citations.duplicates.items()):
            exclusions[duplicate_id] = Exclusion(duplicate_id, "duplicate", f"same as {winner_id}")

        ranked: list[_Ranked] = []
        for item in deduped:
            depth = depths[item.id]
            signals = self._signals(item, query, depth)
            score = self._score(signals, resolved_mode)
            roi = score / max(item.token_count, 1)
            if roi < self.config.min_context_roi:
                exclusions[item.id] = Exclusion(item.id, "below_roi")
                continue
            citations = duplicate_citations.by_winner[item.id]
            ranked.append(_Ranked(item, score, roi, depth, signals, citations))

        # Packing order. Default: relevance-first (absolute score), ROI as
        # tiebreak — preserves historical behaviour.  ``utility_first`` selects
        # a marginal-utility (utility-per-token) greedy knapsack: highest ROI
        # first, so the budget buys the most relevance per token.  Both are
        # deterministic (candidate id breaks ties).
        if self.config.utility_first:
            ranked.sort(key=lambda item: (-item.roi, -item.score, item.candidate.id))
        else:
            ranked.sort(key=lambda item: (-item.score, -item.roi, item.candidate.id))
        packed: list[Evidence] = []
        used = 0
        for ranked_item in ranked:
            if used + ranked_item.candidate.token_count > token_budget:
                exclusions[ranked_item.candidate.id] = Exclusion(
                    ranked_item.candidate.id, "token_budget"
                )
                continue
            used += ranked_item.candidate.token_count
            packed.append(
                Evidence(
                    candidate_id=ranked_item.candidate.id,
                    content=ranked_item.candidate.content,
                    token_count=ranked_item.candidate.token_count,
                    score=_stable_float(ranked_item.score),
                    context_roi=_stable_float(ranked_item.roi),
                    graph_depth=ranked_item.depth,
                    signals=ranked_item.signals,
                    citations=ranked_item.citations,
                    metadata=ranked_item.candidate.metadata,
                    trust=ranked_item.candidate.trust,
                )
            )

        # Confidence = strongest packed relevance score; low_confidence gates an
        # explicit "weak evidence" result even when some context was packed.
        confidence = _stable_float(max((item.score for item in packed), default=0.0))
        low_confidence = not packed or confidence < self.config.min_confidence

        return EvidencePacket(
            query=query,
            mode=resolved_mode,
            token_budget=token_budget,
            used_tokens=used,
            evidence=tuple(packed),
            exclusions=tuple(exclusions[key] for key in sorted(exclusions)),
            no_op=not packed,
            confidence=confidence,
            low_confidence=low_confidence,
        )

    def _scope(
        self, query: str, mode: RetrievalMode, candidates: Mapping[str, Candidate]
    ) -> dict[str, int | None]:
        lexical = {
            candidate_id: _lexical_score(query, item)
            for candidate_id, item in candidates.items()
        }
        if mode == RetrievalMode.GLOBAL:
            return dict.fromkeys(candidates)
        if mode == RetrievalMode.HISTORY:
            return {
                candidate_id: None
                for candidate_id, item in candidates.items()
                if lexical[candidate_id] > 0 or item.history_score > 0
            }
        seeds = sorted(candidate_id for candidate_id, score in lexical.items() if score > 0)
        if mode == RetrievalMode.LOCAL or self.graph_provider is None:
            return dict.fromkeys(seeds)
        if mode == RetrievalMode.DRIFT and seeds:
            strongest = max(lexical[candidate_id] for candidate_id in seeds)
            seeds = [candidate_id for candidate_id in seeds if lexical[candidate_id] == strongest]
        return self._expand(seeds, candidates)

    def _expand(
        self, seeds: Sequence[str], candidates: Mapping[str, Candidate]
    ) -> dict[str, int | None]:
        graph_provider = self.graph_provider
        if graph_provider is None:
            return dict.fromkeys(seeds)
        depths: dict[str, int | None] = {}
        queue: deque[tuple[str, int]] = deque((candidate_id, 0) for candidate_id in seeds)
        queued = set(seeds)
        while queue and len(depths) < self.config.max_graph_nodes:
            candidate_id, depth = queue.popleft()
            if candidate_id not in candidates:
                continue
            depths[candidate_id] = depth
            if depth >= self.config.max_graph_depth:
                continue
            neighbors = sorted(set(graph_provider.neighbors(candidate_id)))
            for neighbor in neighbors:
                if neighbor in candidates and neighbor not in queued:
                    queued.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return depths

    def _signals(self, item: Candidate, query: str, depth: int | None) -> ScoreSignals:
        graph_score = 0.0 if depth is None else 1.0 / (depth + 1)
        return ScoreSignals(
            lexical=_stable_float(_lexical_score(query, item)),
            structural=_stable_float(max(item.structural_score, graph_score)),
            history=item.history_score,
            memory=item.memory_score,
            semantic=item.semantic_score,
            freshness=item.freshness,
        )

    def _score(self, signals: ScoreSignals, mode: RetrievalMode) -> float:
        lexical, structural, history, memory, semantic = _WEIGHTS[mode]
        relevance = (
            lexical * signals.lexical
            + structural * signals.structural
            + history * signals.history
            + memory * signals.memory
            + semantic * (signals.semantic or 0.0)
        )
        freshness_multiplier = 1.0 - self.config.freshness_weight * (1.0 - signals.freshness)
        return relevance * freshness_multiplier

    def _dedupe(
        self,
        candidates: Sequence[Candidate],
        query: str,
        mode: RetrievalMode,
        depths: Mapping[str, int | None],
    ) -> tuple[list[Candidate], _CitationGroups]:
        groups: dict[str, list[Candidate]] = {}
        for item in candidates:
            key = item.dedupe_key or " ".join(item.content.lower().split())
            groups.setdefault(key, []).append(item)

        winners: list[Candidate] = []
        by_winner: dict[str, tuple[Citation, ...]] = {}
        duplicates: dict[str, str] = {}
        for key in sorted(groups):
            group = groups[key]
            group.sort(
                key=lambda item: (
                    -self._score(self._signals(item, query, depths[item.id]), mode),
                    item.id,
                )
            )
            winner = group[0]
            winners.append(winner)
            citations = [
                Citation(
                    candidate_id=item.id,
                    source=item.source,
                    provenance=item.provenance,
                    path=item.path,
                    symbol=item.symbol,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    trust=item.trust,
                )
                for item in group
            ]
            by_winner[winner.id] = tuple(
                sorted(citations, key=lambda citation: (citation.source, citation.candidate_id))
            )
            for duplicate in group[1:]:
                duplicates[duplicate.id] = winner.id
        return winners, _CitationGroups(by_winner, duplicates)


@dataclass(frozen=True, slots=True)
class _CitationGroups:
    by_winner: Mapping[str, tuple[Citation, ...]]
    duplicates: Mapping[str, str]


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token.lower() for token in _TOKEN_RE.findall(value))


def _lexical_score(query: str, candidate: Candidate) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    haystack = " ".join((candidate.source, candidate.content)).lower()
    normalized_query = " ".join(query_tokens)
    if normalized_query in " ".join(_tokens(haystack)):
        return 1.0
    haystack_tokens = set(_tokens(haystack))
    return len(set(query_tokens) & haystack_tokens) / len(set(query_tokens))


def _candidate_order(item: Candidate) -> tuple[str, str, str]:
    return (item.id, item.source, item.content)


def _unique_candidates(candidates: Sequence[Candidate]) -> list[Candidate]:
    unique: list[Candidate] = []
    by_id: dict[str, Candidate] = {}
    for item in candidates:
        previous = by_id.get(item.id)
        if previous is None:
            by_id[item.id] = item
            unique.append(item)
        elif previous != item:
            raise ValueError(f"conflicting candidates share id: {item.id}")
    return unique


def _stable_float(value: float) -> float:
    return round(value, 12)
