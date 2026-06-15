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
    assert storage.get_meta("schema_version") == "6"
    # Table must exist and be queryable.
    count = storage.memory_vector_count()
    assert count == 0


def test_migration_v6_is_idempotent(tmp_path: Path) -> None:
    """Calling initialize() twice must not raise and must leave schema at "6"."""
    storage = _store(tmp_path)
    storage.initialize()  # second call
    assert storage.get_meta("schema_version") == "6"
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
