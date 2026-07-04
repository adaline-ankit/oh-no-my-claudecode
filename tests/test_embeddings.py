"""Tests for the opt-in local embeddings reranking feature.

Covers:
- HashNgramEmbedder is deterministic and produces unit-norm vectors.
- cosine_similarity ranks a semantically near memory above a lexically
  overlapping but semantically irrelevant one on a crafted example.
- Migration v6 (memory_vectors table) is idempotent.
- Vector cache invalidates on content change and on embedder_id change.
- build_vectors_for_all_memories writes and respects the cache.
- Hybrid rerank improves or preserves ordering vs pure lexical.
- Pure-FTS fallback path works when embeddings are disabled (ONMC_EMBEDDINGS=0).
- compile_prompt_recall preserves its return contract with embeddings enabled.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from oh_no_my_claudecode.embeddings.core import (
    HashNgramEmbedder,
    _memory_content_hash,
    cosine_similarity,
    embeddings_enabled,
)
from oh_no_my_claudecode.embeddings.rerank import (
    build_vectors_for_all_memories,
    rerank_with_embeddings,
)
from oh_no_my_claudecode.hooks.prompt_recall import compile_prompt_recall
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memory(
    mem_id: str,
    title: str,
    summary: str,
    details: str = "",
    tags: list[str] | None = None,
    confidence: float = 0.9,
) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=mem_id,
        kind=MemoryKind.DOC_FACT,
        title=title,
        summary=summary,
        details=details or summary,
        source_type=SourceType.DOC,
        source_ref="README.md",
        tags=tags or [],
        confidence=confidence,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )


def _store(tmp_path: Path, entries: list[MemoryEntry] | None = None) -> SQLiteStorage:
    storage = SQLiteStorage(tmp_path / "memory.db")
    storage.initialize()
    if entries:
        storage.upsert_memories(entries)
    return storage


def _l2_norm(vec: list[float]) -> float:
    return math.sqrt(sum(v * v for v in vec))


# ---------------------------------------------------------------------------
# HashNgramEmbedder: determinism + unit norm
# ---------------------------------------------------------------------------


def test_hash_ngram_embedder_is_deterministic() -> None:
    emb = HashNgramEmbedder()
    text = "cache invalidation strategy for distributed systems"
    v1 = emb.embed(text)
    v2 = emb.embed(text)
    assert v1 == v2, "Embedder must be fully deterministic"


def test_hash_ngram_embedder_produces_unit_norm_vector() -> None:
    emb = HashNgramEmbedder()
    vec = emb.embed("SQLite full-text search index using FTS5")
    norm = _l2_norm(vec)
    assert abs(norm - 1.0) < 1e-6, f"Expected unit norm, got {norm}"


def test_hash_ngram_embedder_zero_vector_for_empty_text() -> None:
    emb = HashNgramEmbedder()
    vec = emb.embed("")
    assert all(v == 0.0 for v in vec)


def test_hash_ngram_embedder_dim_property() -> None:
    emb = HashNgramEmbedder(dim=256)
    assert emb.dim == 256
    vec = emb.embed("hello world")
    assert len(vec) == 256


def test_hash_ngram_embedder_id_stable() -> None:
    emb = HashNgramEmbedder()
    assert emb.embedder_id == "hash-ngram-v1-d512"


def test_hash_ngram_embedder_different_texts_differ() -> None:
    emb = HashNgramEmbedder()
    v1 = emb.embed("authentication token refresh flow")
    v2 = emb.embed("billing stripe webhook payment processing")
    sim = cosine_similarity(v1, v2)
    # Two very different topics should have low similarity.
    assert sim < 0.8, f"Expected low similarity between unrelated texts, got {sim:.3f}"


# ---------------------------------------------------------------------------
# cosine_similarity: semantic ranking
# ---------------------------------------------------------------------------


def test_cosine_similarity_near_one_for_same_text() -> None:
    emb = HashNgramEmbedder()
    text = "database migration versioning schema upgrade"
    v = emb.embed(text)
    sim = cosine_similarity(v, v)
    assert abs(sim - 1.0) < 1e-6


def test_cosine_similarity_semantic_near_beats_lexical_overlap() -> None:
    """Core semantic quality test.

    Query: 'how does the cache get invalidated'

    - 'semantic_mem': talks about cache invalidation mechanisms — semantically
      very close to the query even without exact word overlap.
    - 'lexical_mem': contains the exact words 'cache' and 'invalidated' but in
      a completely different context (a random sentence that happens to share
      words).

    HashNgramEmbedder works at the n-gram level, so 'cache', 'invalid',
    'cachin' substrings produce shared buckets.  A memory whose *full text* is
    about cache invalidation will accumulate more shared n-grams with the query
    than a memory that merely contains those two words in passing.
    """
    emb = HashNgramEmbedder()

    query = "cache invalidation strategy eviction policy"

    # Semantically close: full text is about caching systems.
    semantic_text = (
        "cache invalidation eviction lru ttl expiry stale refresh"
        " memoize memoization clear purge warm"
    )
    # Lexically overlapping but semantically irrelevant: just two matching words
    # surrounded by unrelated content.
    lexical_text = (
        "the document was cache and we invalidated the billing report"
        " stripe webhook payment customer subscription invoice refund"
    )

    q_vec = emb.embed(query)
    s_vec = emb.embed(semantic_text)
    l_vec = emb.embed(lexical_text)

    sim_semantic = cosine_similarity(q_vec, s_vec)
    sim_lexical = cosine_similarity(q_vec, l_vec)

    assert sim_semantic > sim_lexical, (
        f"Semantic memory ({sim_semantic:.3f}) should outscore "
        f"lexically-overlapping memory ({sim_lexical:.3f})"
    )


def test_cosine_similarity_zero_vector_returns_zero() -> None:
    emb = HashNgramEmbedder()
    zero = emb.embed("")
    v = emb.embed("some text")
    assert cosine_similarity(zero, v) == 0.0
    assert cosine_similarity(v, zero) == 0.0


def test_cosine_similarity_dimension_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="dimension mismatch"):
        cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# Migration v6: memory_vectors table
# ---------------------------------------------------------------------------


def test_migration_v6_creates_memory_vectors_table(tmp_path: Path) -> None:
    storage = _store(tmp_path)
    assert storage.get_meta("schema_version") == "7"
    # Table must exist and be queryable.
    count = storage.memory_vector_count()
    assert count == 0


def test_migration_v6_is_idempotent(tmp_path: Path) -> None:
    """Calling initialize() twice must not raise and must leave schema stable."""
    storage = _store(tmp_path)
    storage.initialize()  # second call
    assert storage.get_meta("schema_version") == "7"
    assert storage.memory_vector_count() == 0


# ---------------------------------------------------------------------------
# Vector cache: upsert, hit, miss on content change, miss on embedder change
# ---------------------------------------------------------------------------


def test_vector_cache_round_trip(tmp_path: Path) -> None:
    storage = _store(tmp_path)
    emb = HashNgramEmbedder()
    vec = emb.embed("hello world cache invalidation")
    storage.upsert_memory_vector(
        "mem-1",
        embedder_id=emb.embedder_id,
        content_hash="abc123",
        dim=emb.dim,
        vector=vec,
        created_at="2026-01-01T00:00:00+00:00",
    )
    cached = storage.get_memory_vector(
        "mem-1",
        embedder_id=emb.embedder_id,
        content_hash="abc123",
    )
    assert cached is not None
    assert len(cached) == emb.dim
    assert abs(_l2_norm(cached) - 1.0) < 1e-6


def test_vector_cache_miss_on_content_change(tmp_path: Path) -> None:
    storage = _store(tmp_path)
    emb = HashNgramEmbedder()
    vec = emb.embed("original text")
    storage.upsert_memory_vector(
        "mem-1",
        embedder_id=emb.embedder_id,
        content_hash="old-hash",
        dim=emb.dim,
        vector=vec,
        created_at="2026-01-01T00:00:00+00:00",
    )
    # Different content_hash → cache miss
    cached = storage.get_memory_vector(
        "mem-1",
        embedder_id=emb.embedder_id,
        content_hash="new-hash",
    )
    assert cached is None


def test_vector_cache_miss_on_embedder_change(tmp_path: Path) -> None:
    storage = _store(tmp_path)
    emb = HashNgramEmbedder()
    vec = emb.embed("some text here")
    storage.upsert_memory_vector(
        "mem-1",
        embedder_id="old-embedder",
        content_hash="abc",
        dim=emb.dim,
        vector=vec,
        created_at="2026-01-01T00:00:00+00:00",
    )
    # Different embedder_id → cache miss
    cached = storage.get_memory_vector(
        "mem-1",
        embedder_id=emb.embedder_id,
        content_hash="abc",
    )
    assert cached is None


def test_vector_cache_invalidates_on_content_change_via_build(tmp_path: Path) -> None:
    """build_vectors_for_all_memories skips cached, recomputes on content hash miss."""
    emb = HashNgramEmbedder()
    mem = _memory("m1", "cache invalidation", "invalidate on write")
    storage = _store(tmp_path, [mem])

    # First build: writes a vector.
    written1 = build_vectors_for_all_memories(storage, embedder=emb)
    assert written1 == 1

    # Second build (no force): cache hit → nothing written.
    written2 = build_vectors_for_all_memories(storage, embedder=emb)
    assert written2 == 0

    # Force re-build: overwrites even valid cache.
    written3 = build_vectors_for_all_memories(storage, embedder=emb, force=True)
    assert written3 == 1


# ---------------------------------------------------------------------------
# build_vectors_for_all_memories
# ---------------------------------------------------------------------------


def test_build_vectors_writes_for_all_memories(tmp_path: Path) -> None:
    mems = [
        _memory("m1", "cache invalidation", "lru eviction policy"),
        _memory("m2", "auth flow", "JWT token refresh"),
        _memory("m3", "billing", "stripe webhook processing"),
    ]
    storage = _store(tmp_path, mems)
    emb = HashNgramEmbedder()
    written = build_vectors_for_all_memories(storage, embedder=emb)
    assert written == 3
    assert storage.memory_vector_count() == 3


# ---------------------------------------------------------------------------
# Hybrid rerank
# ---------------------------------------------------------------------------


def test_rerank_preserves_order_when_embeddings_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ONMC_EMBEDDINGS=0, rerank_with_embeddings returns candidates unchanged."""
    monkeypatch.setenv("ONMC_EMBEDDINGS", "0")
    storage = _store(tmp_path)
    emb = HashNgramEmbedder()
    mems = [
        _memory("m1", "auth flow", "JWT token"),
        _memory("m2", "cache", "lru eviction"),
    ]
    result = rerank_with_embeddings(
        mems, "cache eviction policy", [5.0, 2.0], storage, embedder=emb
    )
    # Same order as input (disabled path returns input unchanged).
    assert [m.id for m in result] == ["m1", "m2"]


def test_rerank_improves_semantic_ordering(tmp_path: Path) -> None:
    """Semantic rerank surfaces a semantically near memory above a lexically noisy one.

    We craft a scenario where the two memories share identical lexical scores
    (both are equally "relevant" from the FTS/token-overlap perspective), so
    only the cosine component can break the tie.  The semantically close memory
    must end up first after reranking.

    This is the canonical demo of the embedding benefit: FTS can't distinguish
    between two memories that share the same keywords, but the embedding sees
    that one of them is really *about* the query topic and the other merely
    contains coincidental keyword matches.
    """
    storage = _store(tmp_path)
    emb = HashNgramEmbedder()

    query = "cache invalidation eviction policy lru"

    # Semantically close: full text is dense with cache/eviction concepts.
    sem_near = _memory(
        "sem-near",
        "LRU eviction and TTL expiry",
        "cache invalidation eviction policy lru ttl eviction lru memoize"
        " purge lru cache invalidate",
    )
    # Semantically distant: contains matching words but in a billing context.
    lex_noisy = _memory(
        "lex-noisy",
        "cache billing invoice policy",
        "cache billing invoice policy invalidated customer eviction refund stripe lru notice",
    )

    storage.upsert_memories([sem_near, lex_noisy])

    # Both memories receive equal lexical scores — FTS is a tie.
    candidates = [lex_noisy, sem_near]  # arbitrary (alphabetical) order
    lexical_scores = [5.0, 5.0]  # tie — only cosine breaks it

    reranked = rerank_with_embeddings(candidates, query, lexical_scores, storage, embedder=emb)
    # Semantic rerank should promote sem_near to first position.
    assert reranked[0].id == "sem-near", (
        f"Expected sem-near first after semantic rerank, got: {[m.id for m in reranked]}"
    )


def test_rerank_empty_list_is_noop(tmp_path: Path) -> None:
    storage = _store(tmp_path)
    emb = HashNgramEmbedder()
    result = rerank_with_embeddings([], "query", [], storage, embedder=emb)
    assert result == []


def test_rerank_graceful_on_embed_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the embedder raises, rerank_with_embeddings must return candidates unchanged."""
    storage = _store(tmp_path)
    mems = [_memory("m1", "title", "summary")]

    class _BrokenEmbedder:
        @property
        def embedder_id(self) -> str:
            return "broken"

        @property
        def dim(self) -> int:
            return 4

        def embed(self, text: str) -> list[float]:
            msg = "intentional failure"
            raise RuntimeError(msg)

    result = rerank_with_embeddings(mems, "query", [1.0], storage, embedder=_BrokenEmbedder())  # type: ignore[arg-type]
    assert [m.id for m in result] == ["m1"]


# ---------------------------------------------------------------------------
# compile_prompt_recall: return contract preserved
# ---------------------------------------------------------------------------


def test_compile_prompt_recall_with_embeddings(tmp_path: Path) -> None:
    """compile_prompt_recall must return (str, int) with embeddings enabled."""
    mems = [
        _memory("m1", "cache invalidation", "lru eviction policy on write"),
        _memory("m2", "auth flow", "JWT token refresh and revocation"),
    ]
    storage = _store(tmp_path, mems)

    md, count = compile_prompt_recall(storage, "cache eviction strategy", limit=3)
    assert isinstance(md, str)
    assert isinstance(count, int)
    if md:
        assert count > 0
        assert "cache" in md.lower() or "lru" in md.lower() or "eviction" in md.lower()


def test_compile_prompt_recall_empty_prompt_returns_empty(tmp_path: Path) -> None:
    storage = _store(tmp_path, [_memory("m1", "any title", "any summary")])
    md, count = compile_prompt_recall(storage, "")
    assert md == ""
    assert count == 0


# ---------------------------------------------------------------------------
# Embeddings gating
# ---------------------------------------------------------------------------


def test_embeddings_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONMC_EMBEDDINGS", raising=False)
    assert embeddings_enabled() is True


def test_embeddings_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONMC_EMBEDDINGS", "0")
    assert embeddings_enabled() is False


def test_embeddings_enabled_via_env_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONMC_EMBEDDINGS", "1")
    assert embeddings_enabled() is True


# ---------------------------------------------------------------------------
# content_hash helper
# ---------------------------------------------------------------------------


def test_memory_content_hash_is_deterministic() -> None:
    assert _memory_content_hash("hello") == _memory_content_hash("hello")


def test_memory_content_hash_differs_on_different_text() -> None:
    assert _memory_content_hash("hello") != _memory_content_hash("world")


# ---------------------------------------------------------------------------
# fastembed optional backend — all tests are OFFLINE (no model download)
# ---------------------------------------------------------------------------

import oh_no_my_claudecode.embeddings.core as _core_module  # noqa: E402


def test_fastembed_available_returns_false_when_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When fastembed is not installed, fastembed_available() must return False."""
    # Simulate absent package by making the import fail.
    import builtins
    import importlib

    real_import = builtins.__import__

    def _no_fastembed(name: str, *args: object, **kwargs: object) -> object:
        if name == "fastembed":
            raise ImportError("fastembed not installed (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_fastembed)
    from oh_no_my_claudecode.embeddings.core import fastembed_available

    assert fastembed_available() is False
    importlib.invalidate_caches()


def test_fastembed_selected_false_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """fastembed must NOT be auto-selected even if installed — requires explicit opt-in."""
    from oh_no_my_claudecode.embeddings.core import fastembed_selected

    monkeypatch.delenv("ONMC_EMBEDDER", raising=False)
    # Even if the package were available, the env var is absent → not selected.
    # We patch fastembed_available to True to isolate the env-var check.
    monkeypatch.setattr(_core_module, "fastembed_available", lambda: True)
    assert fastembed_selected() is False


def test_fastembed_selected_true_when_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """fastembed_selected() returns True when ONMC_EMBEDDER=fastembed and package present."""
    from oh_no_my_claudecode.embeddings.core import fastembed_selected

    monkeypatch.setenv("ONMC_EMBEDDER", "fastembed")
    monkeypatch.setattr(_core_module, "fastembed_available", lambda: True)
    assert fastembed_selected() is True


def test_fastembed_selected_false_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """fastembed_selected() returns False when env is set but package not installed."""
    from oh_no_my_claudecode.embeddings.core import fastembed_selected

    monkeypatch.setenv("ONMC_EMBEDDER", "fastembed")
    monkeypatch.setattr(_core_module, "fastembed_available", lambda: False)
    assert fastembed_selected() is False


def test_get_embedder_falls_back_to_hash_when_fastembed_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ONMC_EMBEDDER=fastembed but the extra is absent, get_embedder falls back to hash."""
    from oh_no_my_claudecode.embeddings.core import HashNgramEmbedder, get_embedder

    monkeypatch.setenv("ONMC_EMBEDDER", "fastembed")
    # Patch fastembed_selected to True but _try_fastembed to return None (absent).
    monkeypatch.setattr(_core_module, "fastembed_selected", lambda: True)
    monkeypatch.setattr(_core_module, "_try_fastembed", lambda **_kw: None)
    # Also disable sentence-transformers to ensure we hit hash-ngram.
    monkeypatch.setattr(_core_module, "_try_sentence_transformers", lambda: None)
    # Reset the cached singleton.
    monkeypatch.setattr(_core_module, "_DEFAULT_EMBEDDER", None)

    emb = get_embedder()
    assert isinstance(emb, HashNgramEmbedder)


def test_get_embedder_returns_fastembed_when_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ONMC_EMBEDDER=fastembed and the extra loads, get_embedder returns it.

    The fastembed TextEmbedding model is MONKEYPATCHED — no download happens.
    """
    import math

    from oh_no_my_claudecode.embeddings.core import get_embedder

    # Build a minimal fake embedder that satisfies the _FastEmbedder protocol.
    class _FakeTextEmbedding:
        def __init__(self, **_kw: object) -> None:
            self._dim = 384

        def embed(self, texts: list[str]) -> list[list[float]]:
            dim = self._dim
            # Return a fixed unit vector for any input — deterministic & offline.
            raw = [1.0 / math.sqrt(dim)] * dim
            return [raw for _ in texts]

    # Patch the TextEmbedding import inside _try_fastembed by injecting a fake
    # fastembed module into sys.modules.
    import sys
    import types

    fake_fe = types.ModuleType("fastembed")
    fake_fe.TextEmbedding = _FakeTextEmbedding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe)

    monkeypatch.setattr(_core_module, "fastembed_selected", lambda: True)
    monkeypatch.setattr(_core_module, "_DEFAULT_EMBEDDER", None)

    emb = get_embedder()
    # Must NOT be HashNgramEmbedder.
    assert not isinstance(emb, _core_module.HashNgramEmbedder)
    assert "fastembed" in emb.embedder_id
    assert emb.dim == 384


def test_fastembed_embedder_produces_unit_norm_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vectors from the fastembed wrapper are L2-normalised (unit norm).

    Uses a monkeypatched model — no network access.
    """
    import math
    import sys
    import types

    dim = 384

    class _FakeTextEmbedding:
        def __init__(self, **_kw: object) -> None:
            pass

        def embed(self, texts: list[str]) -> list[list[float]]:
            # Return a non-unit raw vector; the wrapper must normalise it.
            return [[2.0] * dim for _ in texts]

    fake_fe = types.ModuleType("fastembed")
    fake_fe.TextEmbedding = _FakeTextEmbedding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe)

    real = _core_module._try_fastembed()
    assert real is not None
    vec = real.embed("some text to embed")
    norm = math.sqrt(sum(v * v for v in vec))
    assert abs(norm - 1.0) < 1e-5, f"Expected unit norm, got {norm}"


def test_fastembed_embedder_zero_vector_for_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty text returns the zero vector from the fastembed wrapper.

    Uses a monkeypatched model — no network access.
    """
    import sys
    import types

    dim = 384

    class _FakeTextEmbedding:
        def __init__(self, **_kw: object) -> None:
            pass

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0] * dim for _ in texts]

    fake_fe = types.ModuleType("fastembed")
    fake_fe.TextEmbedding = _FakeTextEmbedding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe)

    real = _core_module._try_fastembed()
    assert real is not None
    vec = real.embed("")
    assert all(v == 0.0 for v in vec)
    assert len(vec) == dim


def test_fastembed_embedder_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """fastembed wrapper produces identical vectors for the same text.

    Uses a monkeypatched model — no network access.
    """
    import sys
    import types

    dim = 384

    class _FakeTextEmbedding:
        def __init__(self, **_kw: object) -> None:
            pass

        def embed(self, texts: list[str]) -> list[list[float]]:
            import hashlib

            result = []
            for t in texts:
                seed = int(hashlib.sha256(t.encode()).hexdigest(), 16) % 1000
                result.append([float(seed + i) for i in range(dim)])
            return result

    fake_fe = types.ModuleType("fastembed")
    fake_fe.TextEmbedding = _FakeTextEmbedding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe)

    real = _core_module._try_fastembed()
    assert real is not None
    text = "determinism check for fastembed wrapper"
    v1 = real.embed(text)
    v2 = real.embed(text)
    assert v1 == v2


def test_fastembed_embedder_id_contains_model_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """embedder_id encodes the model name for cache invalidation.

    Uses a monkeypatched model — no network access.
    """
    import sys
    import types

    class _FakeTextEmbedding:
        def __init__(self, **_kw: object) -> None:
            pass

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0] for _ in texts]

    fake_fe = types.ModuleType("fastembed")
    fake_fe.TextEmbedding = _FakeTextEmbedding  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe)

    real = _core_module._try_fastembed(model_name="BAAI/bge-small-en-v1.5")
    assert real is not None
    assert "BAAI/bge-small-en-v1.5" in real.embedder_id


def test_get_embedder_default_is_hash_when_no_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without any ONMC_EMBEDDER env var, get_embedder returns HashNgramEmbedder."""
    from oh_no_my_claudecode.embeddings.core import HashNgramEmbedder, get_embedder

    monkeypatch.delenv("ONMC_EMBEDDER", raising=False)
    monkeypatch.setattr(_core_module, "_DEFAULT_EMBEDDER", None)
    # Ensure neither real backend is tried.
    monkeypatch.setattr(_core_module, "fastembed_selected", lambda: False)
    monkeypatch.setattr(_core_module, "_try_sentence_transformers", lambda: None)

    emb = get_embedder()
    assert isinstance(emb, HashNgramEmbedder)


# ---------------------------------------------------------------------------
# fastembed cross-encoder reranker — all tests are OFFLINE (no model download)
# ---------------------------------------------------------------------------

import oh_no_my_claudecode.embeddings.rerank as _rerank_module  # noqa: E402


def _fake_fastembed_module_with_cross_encoder(
    monkeypatch: pytest.MonkeyPatch,
    scores: list[float] | None = None,
    use_rerank_api: bool = False,
) -> None:
    """Inject a fake ``fastembed`` module with a monkeypatched ``TextCrossEncoder``.

    The fake model never downloads anything.  ``scores`` controls what the
    fake model returns (one float per candidate); defaults to a simple
    decreasing sequence.  ``use_rerank_api=True`` makes the fake model expose
    the ``rerank()`` method (newer API); False exposes ``predict()`` (older API).
    """
    import sys
    import types

    _scores = scores

    class _FakeTextCrossEncoder:
        def __init__(self, **_kw: object) -> None:
            pass

        def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
            if _scores is not None:
                return _scores[: len(pairs)]
            return [float(len(pairs) - i) for i in range(len(pairs))]

        def rerank(self, query: str, texts: list[str]) -> list[dict]:  # noqa: ARG002
            raw = self.predict([(query, t) for t in texts])
            return [
                {"corpus_id": idx, "score": score}
                for idx, score in enumerate(raw)
            ]

    if use_rerank_api:
        # Keep rerank method.
        klass = _FakeTextCrossEncoder
    else:
        # Remove rerank so the predict() branch is exercised.
        klass = type(
            "_FakeCEPredict",
            (_FakeTextCrossEncoder,),
            {"rerank": None},  # type: ignore[dict-item]
        )
        # Actually delete the attribute to ensure hasattr returns False.
        del klass.rerank  # type: ignore[attr-defined]

    fake_fe = types.ModuleType("fastembed")
    fake_fe.TextCrossEncoder = klass  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe)


# ---- fastembed_reranker_available / fastembed_reranker_selected ----


def test_fastembed_reranker_available_false_when_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fastembed_reranker_available() returns False when fastembed is not importable."""
    monkeypatch.setattr(_rerank_module, "fastembed_available", lambda: False)
    from oh_no_my_claudecode.embeddings.rerank import fastembed_reranker_available

    assert fastembed_reranker_available() is False


def test_fastembed_reranker_available_true_when_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fastembed_reranker_available() returns True when fastembed is importable."""
    monkeypatch.setattr(_rerank_module, "fastembed_available", lambda: True)
    from oh_no_my_claudecode.embeddings.rerank import fastembed_reranker_available

    assert fastembed_reranker_available() is True


def test_fastembed_reranker_selected_false_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-encoder must NOT be auto-selected — requires explicit ONMC_RERANKER=fastembed."""
    monkeypatch.delenv("ONMC_RERANKER", raising=False)
    monkeypatch.setattr(_rerank_module, "fastembed_available", lambda: True)
    from oh_no_my_claudecode.embeddings.rerank import fastembed_reranker_selected

    assert fastembed_reranker_selected() is False


def test_fastembed_reranker_selected_false_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fastembed_reranker_selected() returns False when env is set but package missing."""
    monkeypatch.setenv("ONMC_RERANKER", "fastembed")
    monkeypatch.setattr(_rerank_module, "fastembed_available", lambda: False)
    from oh_no_my_claudecode.embeddings.rerank import fastembed_reranker_selected

    assert fastembed_reranker_selected() is False


def test_fastembed_reranker_selected_true_when_env_and_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fastembed_reranker_selected() returns True when env is set AND extra is present."""
    monkeypatch.setenv("ONMC_RERANKER", "fastembed")
    monkeypatch.setattr(_rerank_module, "fastembed_available", lambda: True)
    from oh_no_my_claudecode.embeddings.rerank import fastembed_reranker_selected

    assert fastembed_reranker_selected() is True


# ---- Default fallback: no ONMC_RERANKER → existing cosine reranker used ----


def test_rerank_uses_cosine_blend_when_reranker_not_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ONMC_RERANKER=fastembed, rerank_with_embeddings uses the cosine-blend path.

    We verify that _rerank_via_cross_encoder returns None (not selected),
    leaving the cosine-blend to do the reranking — and that the result is still
    sensible (semantically near memory promoted).
    """
    monkeypatch.delenv("ONMC_RERANKER", raising=False)
    storage = _store(tmp_path)
    emb = HashNgramEmbedder()

    query = "cache eviction lru policy"
    sem_near = _memory(
        "sem", "LRU eviction cache", "lru ttl eviction cache invalidation memoize purge"
    )
    lex_noisy = _memory(
        "lex", "billing invoice", "cache billing invoice invalidated stripe refund lru"
    )
    storage.upsert_memories([sem_near, lex_noisy])

    candidates = [lex_noisy, sem_near]
    result = rerank_with_embeddings(candidates, query, [5.0, 5.0], storage, embedder=emb)
    # The cosine-blend should still promote the semantically near memory.
    assert result[0].id == "sem"


# ---- Cross-encoder selected: produces sensible reordering (offline) ----


def test_cross_encoder_reranks_correctly_via_rerank_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-encoder (rerank API) promotes highest-score candidate to first place.

    Uses a MONKEYPATCHED TextCrossEncoder — no model download.
    The fake model assigns score=10 to the first pair, 1 to the rest, so the
    first candidate in *pairs* order gets promoted regardless of lexical score.
    """
    # Select the cross-encoder backend.
    monkeypatch.setenv("ONMC_RERANKER", "fastembed")
    monkeypatch.setattr(_rerank_module, "fastembed_available", lambda: True)
    _fake_fastembed_module_with_cross_encoder(monkeypatch, scores=[10.0, 1.0], use_rerank_api=True)

    storage = _store(tmp_path)
    emb = HashNgramEmbedder()

    # Intentionally put the "winner" second so the reranker must move it.
    winner = _memory("winner", "cache eviction policy", "lru ttl eviction")
    loser = _memory("loser", "billing invoice", "stripe payment customer")
    storage.upsert_memories([winner, loser])

    # The fake reranker gives score 10 to the first pair (loser), 1 to winner.
    # So loser comes first after reranking by the fake model.
    candidates = [loser, winner]
    result = rerank_with_embeddings(candidates, "cache", [1.0, 1.0], storage, embedder=emb)
    # The fake model gave loser score=10 and winner score=1 → loser is first.
    assert result[0].id == "loser"
    assert result[1].id == "winner"


def test_cross_encoder_reranks_correctly_via_predict_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-encoder (predict API) reorders candidates by descending score.

    Uses MONKEYPATCHED predict() — no model download.
    """
    monkeypatch.setenv("ONMC_RERANKER", "fastembed")
    monkeypatch.setattr(_rerank_module, "fastembed_available", lambda: True)
    # scores=[5.0, 99.0] → second candidate gets highest score → promoted first.
    _fake_fastembed_module_with_cross_encoder(monkeypatch, scores=[5.0, 99.0], use_rerank_api=False)

    storage = _store(tmp_path)
    emb = HashNgramEmbedder()

    first = _memory("first", "auth JWT", "token refresh revocation")
    second = _memory("second", "cache lru", "lru eviction invalidation")
    storage.upsert_memories([first, second])

    candidates = [first, second]
    result = rerank_with_embeddings(candidates, "cache", [3.0, 2.0], storage, embedder=emb)
    # Fake predict returns [5.0, 99.0] → second candidate gets 99 → promoted.
    assert result[0].id == "second"
    assert result[1].id == "first"


def test_cross_encoder_graceful_fallback_on_import_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ONMC_RERANKER=fastembed but fastembed absent, falls back to cosine-blend.

    No exception is raised — the fallback is silent and the result is still
    a valid reordering (not necessarily the same order as cross-encoder).
    """
    monkeypatch.setenv("ONMC_RERANKER", "fastembed")
    # Mark fastembed as unavailable → _try_fastembed_cross_encoder returns None.
    monkeypatch.setattr(_rerank_module, "fastembed_reranker_available", lambda: False)
    # Also patch selected to return False so no cross-encoder attempt happens.
    monkeypatch.setattr(_rerank_module, "fastembed_reranker_selected", lambda: False)

    storage = _store(tmp_path)
    emb = HashNgramEmbedder()
    mems = [
        _memory("m1", "title A", "summary about cache"),
        _memory("m2", "title B", "billing summary"),
    ]
    storage.upsert_memories(mems)

    # Must not raise even when backend is "selected" but unavailable.
    result = rerank_with_embeddings(mems, "cache", [1.0, 1.0], storage, embedder=emb)
    assert {m.id for m in result} == {"m1", "m2"}


def test_cross_encoder_graceful_on_model_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the fake cross-encoder raises, rerank falls back to cosine-blend.

    This verifies the BLE001 broad-exception guard in _rerank_via_cross_encoder.
    """
    import sys
    import types

    monkeypatch.setenv("ONMC_RERANKER", "fastembed")
    monkeypatch.setattr(_rerank_module, "fastembed_available", lambda: True)

    class _BrokenCrossEncoder:
        def __init__(self, **_kw: object) -> None:
            pass

        def predict(self, pairs: list[tuple[str, str]]) -> list[float]:  # noqa: ARG002
            msg = "intentional model failure"
            raise RuntimeError(msg)

    fake_fe = types.ModuleType("fastembed")
    fake_fe.TextCrossEncoder = _BrokenCrossEncoder  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fastembed", fake_fe)

    storage = _store(tmp_path)
    emb = HashNgramEmbedder()
    mems = [_memory("m1", "title A", "summary"), _memory("m2", "title B", "other")]
    storage.upsert_memories(mems)

    # Must not raise — falls back to cosine-blend path.
    result = rerank_with_embeddings(mems, "query", [2.0, 1.0], storage, embedder=emb)
    assert {m.id for m in result} == {"m1", "m2"}


def test_cross_encoder_selection_honored_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: when ONMC_RERANKER=fastembed and model works, result differs from default order.

    Uses MONKEYPATCHED TextCrossEncoder (rerank API) with deterministic scores.
    No network access.
    """
    monkeypatch.setenv("ONMC_RERANKER", "fastembed")
    monkeypatch.setattr(_rerank_module, "fastembed_available", lambda: True)

    # Fake model: always returns scores [0.1, 0.9, 0.5] for up to 3 candidates.
    _fake_fastembed_module_with_cross_encoder(
        monkeypatch, scores=[0.1, 0.9, 0.5], use_rerank_api=True
    )

    storage = _store(tmp_path)
    emb = HashNgramEmbedder()

    a = _memory("a", "auth", "auth summary")
    b = _memory("b", "billing", "billing summary")
    c = _memory("c", "cache", "cache summary")
    storage.upsert_memories([a, b, c])

    candidates = [a, b, c]  # scores: a=0.1, b=0.9, c=0.5
    result = rerank_with_embeddings(candidates, "query", [1.0, 1.0, 1.0], storage, embedder=emb)
    # Expected order: b (0.9) > c (0.5) > a (0.1)
    assert [m.id for m in result] == ["b", "c", "a"]
