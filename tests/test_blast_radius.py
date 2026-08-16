"""Blast-radius expansion: pass-through without an index, callers+tests with one."""

from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.codeindex.models import IndexChunk, IndexEdge
from oh_no_my_claudecode.codeindex.store import CodeIndexStore
from oh_no_my_claudecode.context_engine.models import Candidate
from oh_no_my_claudecode.harness_run.blast_radius import expand_with_blast_radius


def _chunk(path: str, symbol: str, *, is_test: bool = False) -> IndexChunk:
    return IndexChunk(
        chunk_id=f"{path}:{symbol}",
        blob_sha="b" * 40,
        commit_sha="c" * 40,
        path=path,
        symbol=symbol,
        kind="function",
        start_line=1,
        end_line=9,
        language="python",
        is_test=is_test,
        is_stale=False,
        trust_level="trusted",
        indexed_at="2026-01-01T00:00:00Z",
        content=f"def {symbol}(): ...",
    )


def _seed(tmp_path: Path) -> Candidate:
    db = tmp_path / ".onmc" / "codeindex.db"
    db.parent.mkdir(parents=True)
    store = CodeIndexStore(db)
    store.upsert_chunks(
        [
            _chunk("pkg/core.py", "target"),
            _chunk("pkg/api.py", "caller_fn"),
            _chunk("tests/test_core.py", "test_target", is_test=True),
        ]
    )
    store.upsert_edges(
        [
            IndexEdge("pkg/api.py", "caller_fn", "pkg/core.py", "target", "callee"),
            IndexEdge("tests/test_core.py", "test_target", "pkg/core.py", "target", "callee"),
        ]
    )
    return Candidate(
        id="repo:pkg/core.py",
        content="def target(): ...",
        source="repo",
        token_count=5,
        provenance=("repo",),
    )


def test_no_index_is_pass_through(tmp_path: Path) -> None:
    seed = Candidate(id="repo:a.py", content="x", source="repo", token_count=1, provenance=("r",))
    assert expand_with_blast_radius(tmp_path, (seed,)) == (seed,)


def test_expands_with_caller_and_covering_test_tests_first(tmp_path: Path) -> None:
    seed = _seed(tmp_path)
    out = expand_with_blast_radius(tmp_path, (seed,))
    ids = [c.id for c in out]
    assert ids[0] == "repo:pkg/core.py"  # base ranking untouched
    assert "blast:tests/test_core.py:test_target" in ids
    assert "blast:pkg/api.py:caller_fn" in ids
    # tests-first ordering among extras
    assert ids.index("blast:tests/test_core.py:test_target") < ids.index(
        "blast:pkg/api.py:caller_fn"
    )
    # idempotent ids, capped, and re-running adds no dupes
    assert len(ids) == len(set(ids))
    assert expand_with_blast_radius(tmp_path, (seed,)) == out
