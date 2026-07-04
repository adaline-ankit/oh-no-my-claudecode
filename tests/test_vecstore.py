"""Tests for the optional sqlite-vec semantic recall backend.

Two classes of tests:

1. **Fallback / gating tests** — run in *every* environment (no sqlite-vec
   required).  They assert that when the package is absent OR the backend is
   not selected, the entry points degrade to the existing hash-embedder path
   with zero behavioural change.

2. **sqlite-vec path tests** — guarded by ``pytest.importorskip("sqlite_vec")``
   so they only execute when the optional extra is installed.  They assert the
   ``vec0`` KNN index builds, matches, and returns semantically ranked results.

The existing recall / embeddings suites must remain green either way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oh_no_my_claudecode.embeddings.core import HashNgramEmbedder
from oh_no_my_claudecode.embeddings.rerank import (
    build_vectors_for_all_memories,
    rerank_with_embeddings,
)
from oh_no_my_claudecode.embeddings.vecstore import (
    SqliteVecStore,
    semantic_search,
    sqlitevec_available,
    sqlitevec_selected,
)
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers (mirrors tests/test_embeddings.py)
# ---------------------------------------------------------------------------


def _memory(mem_id: str, title: str, summary: str, details: str = "") -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=mem_id,
        kind=MemoryKind.DOC_FACT,
        title=title,
        summary=summary,
        details=details or summary,
        source_type=SourceType.DOC,
        source_ref="README.md",
        tags=[],
        confidence=0.9,
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


# ---------------------------------------------------------------------------
# Gating / fallback — always runs (no sqlite-vec required)
# ---------------------------------------------------------------------------


def test_selected_false_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if sqlite-vec were installed, it is off unless configured."""
    monkeypatch.delenv("ONMC_VEC_BACKEND", raising=False)
    assert sqlitevec_selected() is False


def test_selected_false_when_embeddings_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONMC_EMBEDDINGS", "0")
    monkeypatch.setenv("ONMC_VEC_BACKEND", "sqlite-vec")
    assert sqlitevec_selected() is False


def test_selected_respects_prefer_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONMC_VEC_BACKEND", "sqlite-vec")
    assert sqlitevec_selected(prefer=False) is False


def test_semantic_search_returns_none_when_not_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not selected → None (the explicit 'fall back' signal), not an exception."""
    monkeypatch.delenv("ONMC_VEC_BACKEND", raising=False)
    storage = _store(tmp_path, [_memory("m1", "cache", "lru eviction")])
    assert semantic_search(storage, "cache eviction") is None


def test_semantic_search_none_when_unavailable_even_if_preferred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prefer=True still requires the package; when absent → None."""
    if sqlitevec_available():
        pytest.skip("sqlite-vec is installed; this asserts the absent-package path")
    monkeypatch.setenv("ONMC_VEC_BACKEND", "sqlite-vec")
    storage = _store(tmp_path, [_memory("m1", "cache", "lru eviction")])
    assert semantic_search(storage, "cache eviction", prefer=True) is None


def test_rerank_unchanged_without_sqlitevec(tmp_path: Path) -> None:
    """With sqlite-vec unselected, rerank uses the existing cosine blend.

    This is the zero-regression guard: the reranker must still return a
    correctly-ordered, complete list identical to the pre-existing behaviour.
    """
    storage = _store(tmp_path)
    emb = HashNgramEmbedder()
    mems = [
        _memory("m1", "auth flow", "JWT token refresh"),
        _memory("m2", "cache invalidation", "lru eviction ttl expiry"),
    ]
    storage.upsert_memories(mems)
    reranked = rerank_with_embeddings(
        mems, "cache eviction lru", [1.0, 1.0], storage, embedder=emb
    )
    # Complete set preserved; semantically-closer m2 wins the lexical tie.
    assert {m.id for m in reranked} == {"m1", "m2"}
    assert reranked[0].id == "m2"


# ---------------------------------------------------------------------------
# sqlite-vec path — only when the optional extra is installed
# ---------------------------------------------------------------------------


def test_vecstore_knn_ranks_semantically(tmp_path: Path) -> None:
    pytest.importorskip("sqlite_vec")
    emb = HashNgramEmbedder()
    mems = [
        _memory("cache", "cache invalidation", "lru eviction ttl expiry stale refresh purge"),
        _memory("auth", "auth flow", "jwt token refresh oauth login session cookie"),
        _memory("billing", "billing", "stripe webhook invoice payment subscription refund"),
    ]
    storage = _store(tmp_path, mems)

    build_vectors_for_all_memories(storage, embedder=emb)
    store = SqliteVecStore(storage, dim=emb.dim)
    indexed = store.rebuild(embedder=emb)
    assert indexed == 3

    hits = store.knn(emb.embed("cache eviction lru ttl"), k=3)
    assert hits, "expected KNN hits"
    # Nearest memory must be the cache one.
    assert hits[0][0] == "cache"
    # Distances are non-decreasing.
    dists = [d for _, d in hits]
    assert dists == sorted(dists)


def test_semantic_search_returns_ranked_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sqlite_vec")
    monkeypatch.setenv("ONMC_VEC_BACKEND", "sqlite-vec")
    monkeypatch.delenv("ONMC_EMBEDDINGS", raising=False)
    emb = HashNgramEmbedder()
    mems = [
        _memory("cache", "cache invalidation", "lru eviction ttl expiry stale refresh purge"),
        _memory("billing", "billing", "stripe webhook invoice payment subscription refund"),
    ]
    storage = _store(tmp_path, mems)

    ranked = semantic_search(storage, "cache eviction lru ttl", embedder=emb)
    assert ranked is not None
    assert [m.id for m in ranked][0] == "cache"
    assert {m.id for m in ranked} == {"cache", "billing"}


def test_semantic_search_empty_query_returns_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sqlite_vec")
    monkeypatch.setenv("ONMC_VEC_BACKEND", "sqlite-vec")
    storage = _store(tmp_path, [_memory("m1", "cache", "lru eviction")])
    # Selected + available but blank query → [] (not None).
    result = semantic_search(storage, "   ", embedder=HashNgramEmbedder())
    assert result == []


def test_rerank_uses_vecstore_when_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("sqlite_vec")
    monkeypatch.setenv("ONMC_VEC_BACKEND", "sqlite-vec")
    monkeypatch.delenv("ONMC_EMBEDDINGS", raising=False)
    emb = HashNgramEmbedder()
    mems = [
        _memory("auth", "auth flow", "jwt token refresh oauth login"),
        _memory("cache", "cache invalidation", "lru eviction ttl expiry stale refresh purge"),
    ]
    storage = _store(tmp_path, mems)

    reranked = rerank_with_embeddings(
        mems, "cache eviction lru ttl", [1.0, 1.0], storage, embedder=emb
    )
    # Complete set preserved and semantically-close memory surfaces first.
    assert {m.id for m in reranked} == {"auth", "cache"}
    assert reranked[0].id == "cache"
