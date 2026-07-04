"""Opt-in local semantic embeddings for memory reranking.

Design
------
- ``Embedder`` — a ``Protocol`` defining the embedding interface.
- ``HashNgramEmbedder`` — the **default**, fully deterministic, zero-dependency
  embedder based on hashed character n-gram term-frequency vectors.  Works
  out-of-the-box in CI with no extra installs; produces a 512-dimensional
  L2-normalised float vector.
- ``get_embedder()`` — factory that returns the best available embedder:
  first checks for a real model (``sentence-transformers`` or ``voyageai``),
  then falls back to ``HashNgramEmbedder``.  Real models are **never required**
  — their imports are guarded so the package stays dependency-free by default.
- ``cosine_similarity(a, b)`` — pure-Python cosine, used by the hybrid reranker.
- Gating: embeddings reranking is enabled when ``ONMC_EMBEDDINGS=1`` is set
  **or** always (default) when using the zero-dep ``HashNgramEmbedder`` because
  it is cheap and deterministic.  Set ``ONMC_EMBEDDINGS=0`` to disable
  completely (pure FTS/lexical fallback).

Vector cache
------------
Vectors are cached in the SQLite ``memory_vectors`` table (migration v6).
Each row stores ``(memory_id, embedder_id, content_hash, vector_json,
created_at)``.  Vectors are recomputed lazily when the content hash changes.

Optional sqlite-vec backend
---------------------------
When the optional ``sqlite-vec`` extra is installed (``pip install
oh-no-my-claudecode[sqlitevec]``) **and** selected (``ONMC_VEC_BACKEND=sqlite-vec``),
:func:`semantic_search` builds a ``vec0`` KNN index derived from the
``memory_vectors`` cache and performs indexed nearest-neighbour search instead
of the O(n) Python cosine loop.  It is entirely optional — when the package is
absent or unselected the reranker falls back to the default hash embedder with
zero behavioural change.  See :mod:`oh_no_my_claudecode.embeddings.vecstore`.
"""

from __future__ import annotations

from oh_no_my_claudecode.embeddings.core import (
    Embedder,
    HashNgramEmbedder,
    cosine_similarity,
    get_embedder,
)
from oh_no_my_claudecode.embeddings.vecstore import (
    SqliteVecStore,
    semantic_search,
    sqlitevec_available,
    sqlitevec_selected,
)

__all__ = [
    "Embedder",
    "HashNgramEmbedder",
    "SqliteVecStore",
    "cosine_similarity",
    "get_embedder",
    "semantic_search",
    "sqlitevec_available",
    "sqlitevec_selected",
]
