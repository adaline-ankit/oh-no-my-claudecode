"""R3: three interfaces, tagged for attribution, blast radius at the deep level."""

from __future__ import annotations

from pathlib import Path

import pytest

from oh_no_my_claudecode.codeindex.models import IndexChunk, IndexEdge
from oh_no_my_claudecode.codeindex.store import CodeIndexStore
from oh_no_my_claudecode.retrieval.hierarchy import (
    FILE_INTERFACE,
    REPO_INTERFACE,
    SYMBOL_INTERFACE,
    HierarchicalRetriever,
)


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


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
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
    store.upsert_edges([IndexEdge("pkg/api.py", "caller_fn", "pkg/core.py", "target", "callee")])
    return tmp_path


def test_three_interfaces_are_tagged_and_layered(repo: Path) -> None:
    retriever = HierarchicalRetriever(repo)

    top = retriever.repo_map()
    assert top.interface == REPO_INTERFACE
    assert "pkg/core.py" in top.content and "[tests]" in top.content

    middle = retriever.file_view("pkg/core.py")
    assert middle.interface == FILE_INTERFACE
    assert "function target" in middle.content and "def target" not in middle.content

    deep = retriever.symbol_view("target")
    assert deep.interface == SYMBOL_INTERFACE
    assert "def target(): ..." in deep.content
    assert "callers: pkg/api.py:caller_fn" in deep.content  # blast radius attached


def test_missing_index_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="code index missing"):
        HierarchicalRetriever(tmp_path)
