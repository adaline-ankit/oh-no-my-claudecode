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

Optional fastembed cross-encoder backend
----------------------------------------
When the optional ``fastembed`` extra is installed (``pip install
oh-no-my-claudecode[fastembed]``) **and** the reranker is selected
(``ONMC_RERANKER=fastembed``), :func:`rerank_with_embeddings` uses
``fastembed.TextCrossEncoder`` as a **cross-encoder** re-scorer instead of
the default bi-encoder cosine blend.  A cross-encoder scores (query, document)
pairs jointly, typically producing sharper relevance discrimination.

Selection rules:
- ``ONMC_RERANKER=fastembed`` **and** fastembed extra installed → cross-encoder
- Anything else (env absent, ``default``, extra missing) → existing cosine blend

The cross-encoder is **never auto-selected** — it must be explicitly opted in,
mirroring the ``ONMC_EMBEDDER=fastembed`` convention for the bi-encoder.
Tests MUST monkeypatch ``TextCrossEncoder`` so no model is downloaded.
"""

from __future__ import annotations

import math
import os
from typing import TYPE_CHECKING, Any

from oh_no_my_claudecode.embeddings.core import (
    Embedder,
    EmbeddingVector,
    _memory_content_hash,
    cosine_similarity,
    embeddings_enabled,
    fastembed_available,
    get_embedder,
)
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now

if TYPE_CHECKING:
    from oh_no_my_claudecode.models import MemoryEntry
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage


# ---------------------------------------------------------------------------
# Optional fastembed cross-encoder reranker (guarded import)
# ---------------------------------------------------------------------------

_DEFAULT_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def fastembed_reranker_available() -> bool:
    """Return True when the optional ``fastembed`` package is importable.

    Does NOT load a model.  The cross-encoder shares the same ``fastembed``
    extra as the bi-encoder — no separate install is required.
    """
    return fastembed_available()


def fastembed_reranker_selected() -> bool:
    """Return True when the fastembed cross-encoder reranker is configured.

    Requires **both** availability and opt-in:
    - ``ONMC_RERANKER=fastembed`` environment variable (case-insensitive).
    - The ``fastembed`` extra must be installed.

    When absent or not selected, :func:`rerank_with_embeddings` falls back to
    the existing cosine-blend heuristic without error.
    """
    if not fastembed_reranker_available():
        return False
    raw = os.environ.get("ONMC_RERANKER", "").strip().lower()
    return raw == "fastembed"


def _try_fastembed_cross_encoder(
    model_name: str = _DEFAULT_CROSS_ENCODER_MODEL,
) -> Any | None:  # noqa: ANN401
    """Attempt to load the fastembed ``TextCrossEncoder`` and return it.

    Returns the loaded model object on success, or ``None`` when:
    - ``fastembed`` is not installed, or
    - the model cannot be loaded (any exception).

    The import error is silently swallowed so the package never fails to import
    on a fresh install.  Tests MUST monkeypatch this function or inject a fake
    ``fastembed`` module into ``sys.modules`` — no network is ever hit.

    The return type is ``Any`` because ``TextCrossEncoder`` is a third-party
    class not available at type-check time (import-guarded).
    """
    try:
        from fastembed import TextCrossEncoder  # noqa: PLC0415
    except ImportError:
        return None

    try:
        return TextCrossEncoder(model_name=model_name)
    except Exception:  # noqa: BLE001
        return None


def _rerank_via_cross_encoder(
    candidates: list[MemoryEntry],
    query: str,
) -> list[MemoryEntry] | None:
    """Reorder *candidates* using the fastembed ``TextCrossEncoder``.

    Scores each (query, candidate_text) pair jointly, sorts descending by
    score, and returns the reordered list.  Returns ``None`` when the
    cross-encoder backend is unavailable or not selected, or on any error —
    signalling the caller to fall back to the cosine-blend path.  Never raises.
    """
    if not fastembed_reranker_selected():
        return None

    model = _try_fastembed_cross_encoder()
    if model is None:
        return None

    try:
        texts = [_memory_text(m) for m in candidates]
        pairs = [(query, t) for t in texts]
        # TextCrossEncoder.rerank returns an iterable of (score, index) or a
        # list of scores depending on the fastembed version.  We call
        # ``rerank`` when available (preferred), else ``predict`` on pairs.
        if hasattr(model, "rerank"):
            results = list(model.rerank(query, texts))
            # rerank() returns dicts with 'score' and 'index' keys.
            scored: list[tuple[float, MemoryEntry]] = []
            for item in results:
                if isinstance(item, dict):
                    raw_idx = item.get("corpus_id") or item.get("index") or 0
                    idx = int(raw_idx)
                    score = float(item.get("score") or 0.0)
                else:
                    # Fallback: treat as (score, index) tuple.
                    score, idx = float(item[0]), int(item[1])
                if 0 <= idx < len(candidates):
                    scored.append((score, candidates[idx]))
        else:
            # Older fastembed: predict() returns a list of float scores
            # aligned with *pairs*.
            raw_model: Any = model
            scores = list(raw_model.predict(pairs))
            scored = [(float(s), m) for s, m in zip(scores, candidates, strict=True)]

        scored.sort(key=lambda item: (-item[0], item[1].title))
        return [m for _, m in scored]
    except Exception:  # noqa: BLE001
        return None


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


def _rerank_via_sqlitevec(
    candidates: list[MemoryEntry],
    query: str,
    storage: SQLiteStorage,
    embedder: Embedder,
) -> list[MemoryEntry] | None:
    """Reorder *candidates* using the optional sqlite-vec KNN backend.

    Returns a reordered list restricted to the input *candidates* (semantic
    nearest first, with any candidates missing from the KNN result appended in
    their original order), or ``None`` when the backend is unavailable / not
    selected / errors — signalling the caller to fall back to the pure-Python
    cosine blend.  Never raises.
    """
    try:
        from oh_no_my_claudecode.embeddings.vecstore import (  # noqa: PLC0415
            semantic_search,
            sqlitevec_selected,
        )

        if not sqlitevec_selected():
            return None

        ranked = semantic_search(
            storage, query, limit=len(candidates), embedder=embedder
        )
    except Exception:  # noqa: BLE001
        return None

    if ranked is None:
        return None

    candidate_ids = {m.id for m in candidates}
    by_id = {m.id: m for m in candidates}
    ordered: list[MemoryEntry] = []
    seen: set[str] = set()
    for memory in ranked:
        if memory.id in candidate_ids and memory.id not in seen:
            ordered.append(by_id[memory.id])
            seen.add(memory.id)
    # Preserve any candidates the KNN didn't surface, in original order.
    for memory in candidates:
        if memory.id not in seen:
            ordered.append(memory)
            seen.add(memory.id)
    return ordered


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

    # Optional fastembed cross-encoder: when installed AND ONMC_RERANKER=fastembed,
    # use a cross-encoder to jointly score (query, document) pairs for sharper
    # relevance discrimination.  Any miss returns None and we fall through to
    # the existing paths (zero regression).
    ce_ordered = _rerank_via_cross_encoder(candidates, query)
    if ce_ordered is not None:
        return ce_ordered

    # Optional sqlite-vec backend: when installed AND selected, use its indexed
    # KNN to reorder the candidate set semantically.  Any miss returns None and
    # we fall through to the pure-Python cosine blend below (zero regression).
    vec_ordered = _rerank_via_sqlitevec(candidates, query, storage, embedder)
    if vec_ordered is not None:
        return vec_ordered

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
