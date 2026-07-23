"""Dense retrieval using the existing embedder infrastructure.

Resolution order for the backing embedder (handled by
:func:`~oh_no_my_claudecode.embeddings.core.get_embedder`):

1. ``ONMC_EMBEDDER=fastembed`` **and** the ``fastembed`` extra is installed
   → FastEmbed ONNX CPU embedder (local, no API key).
2. ``sentence-transformers`` installed → all-MiniLM-L6-v2.
3. Default fallback → :class:`~oh_no_my_claudecode.embeddings.core.HashNgramEmbedder`
   (zero dependencies, fully deterministic, 512-dimensional n-gram TF vectors).

Corpus embeddings are pre-computed at construction time.  Repeated queries
are O(n × dim) where n is corpus size and dim is vector dimensionality.
"""

from __future__ import annotations

from oh_no_my_claudecode.embeddings.core import (
    Embedder,
    EmbeddingVector,
    cosine_similarity,
    get_embedder,
)


class DenseRetriever:
    """Pre-computed dense embeddings for a fixed corpus.

    Parameters
    ----------
    doc_ids:
        Ordered document identifiers.
    texts:
        Parallel document texts to embed (one per doc_id).
    embedder:
        Explicit embedder override.  If ``None``, resolved via
        :func:`~oh_no_my_claudecode.embeddings.core.get_embedder`.
    """

    def __init__(
        self,
        doc_ids: list[str],
        texts: list[str],
        embedder: Embedder | None = None,
    ) -> None:
        if len(doc_ids) != len(texts):
            msg = (
                f"doc_ids and texts must be the same length; "
                f"got {len(doc_ids)} vs {len(texts)}"
            )
            raise ValueError(msg)

        self._embedder: Embedder = embedder if embedder is not None else get_embedder()
        self._doc_ids: list[str] = list(doc_ids)

        # Pre-compute corpus embeddings once at construction time.
        self._embeddings: list[EmbeddingVector] = [
            self._embedder.embed(text) for text in texts
        ]

    @property
    def embedder_id(self) -> str:
        """Stable identifier of the backing embedder for provenance and logging."""
        return self._embedder.embedder_id

    @property
    def dim(self) -> int:
        """Dimensionality of the embedding vectors."""
        return self._embedder.dim

    def retrieve(self, query: str, k: int) -> list[tuple[str, float]]:
        """Return up to *k* ``(doc_id, cosine_similarity)`` pairs, ranked descending.

        Returns an empty list when the query embeds to the zero vector (empty
        text or purely stopword input).  Ties are broken by doc_id
        lexicographic order for determinism.
        """
        q_vec = self._embedder.embed(query)

        # Guard: zero vector (empty text) → no meaningful similarity.
        if all(v == 0.0 for v in q_vec):
            return []

        scores: list[tuple[str, float]] = [
            (self._doc_ids[i], cosine_similarity(q_vec, self._embeddings[i]))
            for i in range(len(self._doc_ids))
        ]
        # Primary: similarity descending.  Secondary: doc_id ascending.
        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores[:k]
