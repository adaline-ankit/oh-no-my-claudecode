"""Core embedder abstractions and implementations.

The ``HashNgramEmbedder`` is the default: it builds a 512-dimensional hashed
character n-gram term-frequency vector that is L2-normalised and fully
deterministic.  No ML dependencies are required.

Pluggable real embedders (``sentence-transformers``, ``voyageai``) are detected
at runtime when available — their imports are wrapped in try/except so the
package never fails to import on a fresh install.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

_VEC_DIM = 512  # default hash-embedder dimensionality

EmbeddingVector = list[float]


@runtime_checkable
class Embedder(Protocol):
    """Protocol for an embedding provider.

    Implementors must be deterministic for the same ``text`` input and the same
    ``embedder_id`` value — this is relied on by the vector cache invalidation
    logic.
    """

    @property
    def embedder_id(self) -> str:
        """Stable identifier for cache invalidation (e.g. "hash-ngram-v1")."""
        ...

    @property
    def dim(self) -> int:
        """Dimensionality of the output vectors."""
        ...

    def embed(self, text: str) -> EmbeddingVector:
        """Return an L2-normalised float vector of length ``self.dim``.

        The vector must sum-of-squares to ≈ 1.0 (unit norm).  The zero vector
        (empty text) is returned as ``[0.0] * dim``.
        """
        ...


# ---------------------------------------------------------------------------
# Default: HashNgramEmbedder
# ---------------------------------------------------------------------------

# Regex to extract alphanumeric tokens for n-gram generation.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class HashNgramEmbedder:
    """Deterministic, zero-dependency hashed character n-gram TF embedder.

    Algorithm
    ---------
    1. Lowercase the input; extract alphanumeric tokens with a regex.
    2. For each token, generate overlapping character n-grams of sizes
       ``ngram_sizes`` (default ``(2, 3)``).
    3. Hash each n-gram with SHA-256; take the first 8 bytes as an unsigned
       int; modulo ``dim`` to get a bucket index.
    4. Accumulate counts per bucket (term-frequency vector).
    5. L2-normalise the result; return ``[0.0] * dim`` for empty text.

    The resulting vector is a bag-of-n-grams TF representation suitable for
    cosine-similarity comparison.  It captures morphological overlap and
    partial sub-word matches (e.g. "cache" and "caching" share n-grams).

    Determinism: SHA-256 is deterministic; the modulo bucketing is stable;
    there is no randomness anywhere.

    Performance: O(tokens × max_ngram_len) — negligible for memory titles
    and summaries (typically < 200 chars).
    """

    def __init__(
        self,
        dim: int = _VEC_DIM,
        ngram_sizes: tuple[int, ...] = (2, 3),
    ) -> None:
        self._dim = dim
        self._ngram_sizes = ngram_sizes
        self._id = f"hash-ngram-v1-d{dim}"

    @property
    def embedder_id(self) -> str:
        return self._id

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> EmbeddingVector:
        vec = [0.0] * self._dim
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            for n in self._ngram_sizes:
                for i in range(len(token) - n + 1):
                    ngram = token[i : i + n]
                    h = hashlib.sha256(ngram.encode("utf-8")).digest()
                    bucket = int.from_bytes(h[:8], "little") % self._dim
                    vec[bucket] += 1.0
        # L2-normalise
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0.0:
            inv = 1.0 / norm
            return [v * inv for v in vec]
        return vec  # zero vector for empty text


# ---------------------------------------------------------------------------
# Optional real-model embedders (guarded imports)
# ---------------------------------------------------------------------------

def _try_sentence_transformers() -> Embedder | None:
    """Attempt to load ``sentence-transformers`` and return an embedder.

    Returns None when the library is not installed.  The import error is
    silently swallowed so the package stays dependency-free by default.
    """
    try:
        from sentence_transformers import (  # type: ignore[import-not-found]  # noqa: PLC0415
            SentenceTransformer,
        )
    except ImportError:
        return None

    class _STEmbedder:
        def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
            self._model = SentenceTransformer(model_name)
            self._dim = int(self._model.get_sentence_embedding_dimension())
            self._id = f"sentence-transformers/{model_name}"

        @property
        def embedder_id(self) -> str:
            return self._id

        @property
        def dim(self) -> int:
            return self._dim

        def embed(self, text: str) -> EmbeddingVector:
            vec = self._model.encode(text, normalize_embeddings=True)
            return [float(v) for v in vec]

    try:
        return _STEmbedder()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_DEFAULT_EMBEDDER: Embedder | None = None


def get_embedder(*, force_default: bool = False) -> Embedder:
    """Return the best available embedder as a process-wide singleton.

    Resolution order:
    1. If ``ONMC_EMBEDDER=default`` or *force_default* is True → always return
       ``HashNgramEmbedder``.
    2. If ``sentence-transformers`` is installed → use it.
    3. Fallback: ``HashNgramEmbedder``.

    The singleton is cached after first resolution so model loading happens at
    most once per process.
    """
    global _DEFAULT_EMBEDDER  # noqa: PLW0603

    if _DEFAULT_EMBEDDER is not None and not force_default:
        return _DEFAULT_EMBEDDER

    if force_default or os.environ.get("ONMC_EMBEDDER", "").lower() == "default":
        _DEFAULT_EMBEDDER = HashNgramEmbedder()
        return _DEFAULT_EMBEDDER

    # Try real embedders in preference order.
    real = _try_sentence_transformers()
    if real is not None:
        _DEFAULT_EMBEDDER = real
        return _DEFAULT_EMBEDDER

    _DEFAULT_EMBEDDER = HashNgramEmbedder()
    return _DEFAULT_EMBEDDER


# ---------------------------------------------------------------------------
# Cosine similarity (pure Python, no NumPy)
# ---------------------------------------------------------------------------

def cosine_similarity(a: EmbeddingVector, b: EmbeddingVector) -> float:
    """Return cosine similarity in [-1, 1] between two L2-normalised vectors.

    If both vectors were produced by an ``Embedder`` (which guarantees unit
    norm), this is simply the dot product.  We compute the full formula anyway
    so the function works correctly with unnormalised vectors too.

    Returns 0.0 when either vector is the zero vector.
    """
    if len(a) != len(b):
        msg = f"Vector dimension mismatch: {len(a)} vs {len(b)}"
        raise ValueError(msg)
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Gating helper
# ---------------------------------------------------------------------------

def embeddings_enabled() -> bool:
    """Return True when embeddings reranking is active.

    Gating rules (in priority order):
    1. ``ONMC_EMBEDDINGS=0`` → always disabled.
    2. ``ONMC_EMBEDDINGS=1`` → always enabled.
    3. Default (env var absent or any other value) → **enabled** because the
       built-in ``HashNgramEmbedder`` is cheap, deterministic, and zero-dep.
       Set ``ONMC_EMBEDDINGS=0`` to opt out.
    """
    raw = os.environ.get("ONMC_EMBEDDINGS", "").strip().lower()
    return raw != "0"


def _memory_content_hash(text: str) -> str:
    """Return a short SHA-256 hex digest of *text* for cache-invalidation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
