"""Optional reranker contract for measured retrieval candidates.

ONMC does not install or download a reranker implicitly.  A caller may inject an
already-available implementation; the measured policy records its backend ID
and refuses outputs that invent or duplicate corpus IDs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class Reranker(Protocol):
    """An already-initialized, side-effect-free candidate reranker."""

    @property
    def reranker_id(self) -> str:
        """Stable backend/model identifier for provenance."""
        ...

    def rerank(
        self,
        query: str,
        ranking: list[tuple[str, float]],
        documents: Mapping[str, str],
    ) -> list[tuple[str, float]]:
        """Return a reordered/scored subset of ``ranking``."""
        ...


def apply_reranker(
    reranker: Reranker,
    query: str,
    ranking: list[tuple[str, float]],
    documents: Mapping[str, str],
) -> list[tuple[str, float]]:
    """Apply an injected reranker while enforcing corpus/provenance integrity."""
    reranked = reranker.rerank(query, list(ranking), documents)
    allowed = {doc_id for doc_id, _score in ranking}
    seen: set[str] = set()
    for doc_id, _score in reranked:
        if doc_id not in allowed:
            raise ValueError(f"reranker returned unknown document id: {doc_id}")
        if doc_id in seen:
            raise ValueError(f"reranker returned duplicate document id: {doc_id}")
        seen.add(doc_id)
    return reranked


__all__ = ["Reranker", "apply_reranker"]
