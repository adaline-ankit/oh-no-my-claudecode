"""Injectable, side-effect-free provider interfaces."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from oh_no_my_claudecode.context_engine.models import Candidate, RetrievalMode


class CandidateProvider(Protocol):
    """Supplies already-built candidates; implementations control their own storage."""

    def candidates(self, query: str, mode: RetrievalMode) -> Iterable[Candidate]: ...


class GraphProvider(Protocol):
    """Returns structural neighbor ids for bounded expansion."""

    def neighbors(self, candidate_id: str) -> Iterable[str]: ...


@dataclass(frozen=True, slots=True)
class StaticCandidateProvider:
    """In-memory provider useful for adapters and tests."""

    items: Sequence[Candidate]

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))

    def candidates(self, query: str, mode: RetrievalMode) -> Iterable[Candidate]:
        del query, mode
        return self.items


class StaticGraphProvider:
    """Deterministic graph adapter over an id-to-neighbors mapping."""

    def __init__(self, edges: Mapping[str, Iterable[str]]) -> None:
        self._edges = {node: tuple(sorted(set(neighbors))) for node, neighbors in edges.items()}

    def neighbors(self, candidate_id: str) -> Iterable[str]:
        return self._edges.get(candidate_id, ())
