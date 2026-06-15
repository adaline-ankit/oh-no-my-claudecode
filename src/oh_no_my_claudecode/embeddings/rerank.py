"""Hybrid lexical + semantic reranking for memory retrieval.

This module provides ``rerank_with_embeddings``, which takes a list of
``MemoryEntry`` candidates (already retrieved by FTS/lexical search), a
query string, and a storage instance, and returns the candidates reordered
by a blend of lexical score and cosine similarity to the query embedding.

The function is designed to be called *after* the FTS/lexical retrieval step —
it refines the ranking, it does not replace it.

Gating
------
All entry-points check ``embeddings_enabled()`` first.  When disabled, the
input list is returned unchanged so all call-sites degrade gracefully.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from oh_no_my_claudecode.embeddings.core import (
    Embedder,
    EmbeddingVector,
    _memory_content_hash,
    cosine_similarity,
    embeddings_enabled,
    get_embedder,
)
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now

if TYPE_CHECKING:
    from oh_no_my_claudecode.models import MemoryEntry
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage


def _memory_text(memory: MemoryEntry) -> str:
    """Concatenate the fields we embed for a memory entry."""
    return " ".join(
        [
            memory.title,
            memory.summary,
            memory.details,
            " ".join(memory.tags),
        ]
    )


def _get_or_compute_vector(
    memory: MemoryEntry,
    embedder: Embedder,
    storage: SQLiteStorage,
) -> EmbeddingVector:
    """Return the cached vector for *memory*, computing and caching if needed."""
    text = _memory_text(memory)
    content_hash = _memory_content_hash(text)

    cached = storage.get_memory_vector(
        memory.id,
        embedder_id=embedder.embedder_id,
        content_hash=content_hash,
    )
    if cached is not None and len(cached) == embedder.dim:
        return cached

    vec = embedder.embed(text)
    storage.upsert_memory_vector(
        memory.id,
        embedder_id=embedder.embedder_id,
        content_hash=content_hash,
        dim=embedder.dim,
        vector=vec,
        created_at=isoformat_utc(utc_now()),
    )
    return vec


def _softmax_normalize(scores: list[float]) -> list[float]:
    """Return softmax-normalised values for a list of raw scores.

    Uses the max-subtraction trick for numerical stability.
    Returns a uniform distribution when all scores are equal.
    """
    if not scores:
        return []
    max_s = max(scores)
    exps = [math.exp(s - max_s) for s in scores]
    total = sum(exps)
    if total == 0.0:
        n = len(scores)
        return [1.0 / n] * n
    return [e / total for e in exps]


# Blend weight: cosine gets this share, lexical score gets (1 - _ALPHA).
# 0.4 gives cosine meaningful influence while keeping lexical dominant.
_ALPHA = 0.4


def rerank_with_embeddings(
    candidates: list[MemoryEntry],
    query: str,
    lexical_scores: list[float],
    storage: SQLiteStorage,
    *,
    embedder: Embedder | None = None,
    alpha: float = _ALPHA,
) -> list[MemoryEntry]:
    """Rerank *candidates* by blending lexical and cosine similarity scores.

    Args:
        candidates: Memories in their current (lexical) order.
        query: The raw search/task query string.
        lexical_scores: Per-memory lexical scores aligned with *candidates*.
          Must have the same length as *candidates*.
        storage: SQLiteStorage instance for vector cache reads/writes.
        embedder: Embedder to use; defaults to ``get_embedder()``.
        alpha: Weight of the cosine component in [0, 1].  ``alpha=0`` → pure
          lexical; ``alpha=1`` → pure semantic.

    Returns:
        A new list with the same entries reordered by the blended score.
        On any embedding error the original order is returned unchanged.
    """
    if not embeddings_enabled():
        return candidates

    if not candidates:
        return candidates

    if len(lexical_scores) != len(candidates):
        return candidates

    if embedder is None:
        try:
            embedder = get_embedder()
        except Exception:  # noqa: BLE001
            return candidates

    try:
        query_vec = embedder.embed(query)
    except Exception:  # noqa: BLE001
        return candidates

    # Embed memories (uses cache).
    mem_vecs: list[EmbeddingVector | None] = []
    for memory in candidates:
        try:
            mem_vecs.append(_get_or_compute_vector(memory, embedder, storage))
        except Exception:  # noqa: BLE001
            mem_vecs.append(None)

    # Compute cosine similarities.
    cosines: list[float] = []
    for vec in mem_vecs:
        if vec is None or len(vec) != len(query_vec):
            cosines.append(0.0)
        else:
            try:
                cosines.append(cosine_similarity(query_vec, vec))
            except Exception:  # noqa: BLE001
                cosines.append(0.0)

    # Normalise both score lists so they live on the same scale.
    norm_lex = _softmax_normalize(lexical_scores)
    norm_cos = _softmax_normalize(cosines)

    blended = [
        (1.0 - alpha) * lex + alpha * cos
        for lex, cos in zip(norm_lex, norm_cos, strict=True)
    ]

    # Sort by blended score descending, then original title for tie-breaking.
    paired = list(zip(blended, candidates, strict=True))
    paired.sort(key=lambda item: (-item[0], item[1].title))
    return [m for _, m in paired]


def build_vectors_for_all_memories(
    storage: SQLiteStorage,
    *,
    embedder: Embedder | None = None,
    force: bool = False,
) -> int:
    """Pre-compute and cache vectors for all memories in *storage*.

    This is the backing function for ``onmc memory embed``.

    Args:
        storage: Initialised SQLiteStorage instance.
        embedder: Embedder to use; defaults to ``get_embedder()``.
        force: When True, recompute even if a cached vector already exists.

    Returns:
        Number of vectors written (new or refreshed).
    """
    if embedder is None:
        embedder = get_embedder()

    memories = storage.list_memories()
    written = 0
    for memory in memories:
        text = _memory_text(memory)
        content_hash = _memory_content_hash(text)
        if not force:
            cached = storage.get_memory_vector(
                memory.id,
                embedder_id=embedder.embedder_id,
                content_hash=content_hash,
            )
            if cached is not None and len(cached) == embedder.dim:
                continue
        vec = embedder.embed(text)
        storage.upsert_memory_vector(
            memory.id,
            embedder_id=embedder.embedder_id,
            content_hash=content_hash,
            dim=embedder.dim,
            vector=vec,
            created_at=isoformat_utc(utc_now()),
        )
        written += 1
    return written
