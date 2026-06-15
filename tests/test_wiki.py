"""Tests for ``onmc wiki`` — wiki generator, service method, and CLI command."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.models.memory_edge import EdgeType, MemoryEdge
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now
from oh_no_my_claudecode.wiki.generator import build_wiki

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mem(
    *,
    title: str,
    summary: str,
    kind: MemoryKind = MemoryKind.DECISION,
    source_ref: str = "src/cache.py",
) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=str(uuid.uuid4()),
        kind=kind,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.CODE,
        source_ref=source_ref,
        tags=[],
        confidence=0.9,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )


def _edge(from_id: str, to_id: str, edge_type: EdgeType) -> MemoryEdge:
    return MemoryEdge(
        id=str(uuid.uuid4()),
        from_memory_id=from_id,
        to_memory_id=to_id,
        edge_type=edge_type,
        confidence=1.0,
        created_at=utc_now(),
    )


def _seeded_storage(tmp_path: Path) -> tuple[SQLiteStorage, list[MemoryEntry]]:
    """Return an initialised store with a small set of seed memories."""
    db = tmp_path / ".onmc" / "memory.db"
    storage = SQLiteStorage(db)
    storage.initialize()

    memories = [
        _mem(
            title="Cache boundary invariant",
            summary="Workers must not bypass the cache boundary.",
            kind=MemoryKind.INVARIANT,
            source_ref="src/cache.py",
        ),
        _mem(
            title="Cache invalidation strategy",
            summary="We centralise invalidation in one module to reduce duplication.",
            kind=MemoryKind.DECISION,
            source_ref="src/cache.py",
        ),
        _mem(
            title="Worker retry gotcha",
            summary="Retrying without back-off causes thundering-herd on the cache.",
            kind=MemoryKind.GOTCHA,
            source_ref="src/worker.py",
        ),
        _mem(
            title="Direct DB writes failed approach",
            summary="Attempted direct DB writes from workers; caused data races.",
            kind=MemoryKind.FAILED_APPROACH,
            source_ref="docs/architecture.md",
        ),
    ]
    storage.upsert_memories(memories)
    return storage, memories


# ---------------------------------------------------------------------------
# Unit tests: build_wiki
# ---------------------------------------------------------------------------


def test_build_wiki_always_returns_index_and_graph(tmp_path: Path, sample_repo: Path) -> None:
    """Empty store should still produce index.md and graph.md."""
    db = tmp_path / ".onmc" / "memory.db"
    storage = SQLiteStorage(db)
    storage.initialize()

    pages = build_wiki(storage, sample_repo)

    assert "index.md" in pages
    assert "graph.md" in pages


def test_build_wiki_seeded_produces_subsystem_pages(tmp_path: Path, sample_repo: Path) -> None:
    """Seeded store with memories in src/ and docs/ produces subsystem pages."""
    storage, _ = _seeded_storage(tmp_path)

    pages = build_wiki(storage, sample_repo)

    # Must have index, graph, and at least one subsystem page
    assert "index.md" in pages
    assert "graph.md" in pages
    subsystem_pages = [k for k in pages if k.startswith("subsystems/")]
    assert len(subsystem_pages) >= 1


def test_build_wiki_index_links_to_subsystems(tmp_path: Path, sample_repo: Path) -> None:
    """Index page must contain relative links to every subsystem page."""
    storage, _ = _seeded_storage(tmp_path)

    pages = build_wiki(storage, sample_repo)

    index = pages["index.md"]
    for page_path in pages:
        if page_path == "index.md":
            continue
        # Link appears somewhere in index.md
        assert page_path in index or Path(page_path).name in index, (
            f"index.md does not link to {page_path}"
        )


def test_build_wiki_subsystem_links_back_to_index(tmp_path: Path, sample_repo: Path) -> None:
    """Every subsystem page must contain a back-link to index.md."""
    storage, _ = _seeded_storage(tmp_path)

    pages = build_wiki(storage, sample_repo)

    for page_path, content in pages.items():
        if page_path == "index.md":
            continue
        assert "index.md" in content, (
            f"{page_path} does not contain a back-link to index.md"
        )


def test_build_wiki_graph_page_lists_edges(tmp_path: Path, sample_repo: Path) -> None:
    """Graph page must list memory edges when they exist."""
    storage, memories = _seeded_storage(tmp_path)

    edge = _edge(memories[0].id, memories[1].id, EdgeType.SUPERSEDES)
    storage.upsert_memory_edge(edge)

    pages = build_wiki(storage, sample_repo)
    graph_content = pages["graph.md"]

    assert "supersedes" in graph_content.lower()
    assert memories[0].title in graph_content or memories[1].title in graph_content


def test_build_wiki_graph_page_contradicts_visible(tmp_path: Path, sample_repo: Path) -> None:
    """Contradicts edges must be present and prominently placed in graph page."""
    storage, memories = _seeded_storage(tmp_path)

    edge = _edge(memories[0].id, memories[2].id, EdgeType.CONTRADICTS)
    storage.upsert_memory_edge(edge)

    pages = build_wiki(storage, sample_repo)
    graph_content = pages["graph.md"]

    assert "contradicts" in graph_content.lower()


def test_build_wiki_no_stray_fences(tmp_path: Path, sample_repo: Path) -> None:
    """Wiki prose must not contain raw triple-backtick fences."""
    import re

    # Seed with a summary that contains a markdown fence
    storage, _ = _seeded_storage(tmp_path)
    noisy_mem = _mem(
        title="Noisy fact",
        summary="Use this pattern:\n```python\nx = 1\n```\nfor initialization.",
        kind=MemoryKind.DOC_FACT,
        source_ref="src/cache.py",
    )
    storage.upsert_memories([noisy_mem])

    pages = build_wiki(storage, sample_repo)

    fence_re = re.compile(r"```")
    for page_path, content in pages.items():
        # Strip lines that are part of markdown code blocks intentionally
        # written by the generator itself (e.g. none — we don't write any).
        # Any ``` that leaks from memory summaries is a bug.
        assert not fence_re.search(content), (
            f"Stray ``` fence found in {page_path}"
        )


def test_build_wiki_no_mid_word_truncation(tmp_path: Path, sample_repo: Path) -> None:
    """Truncated summaries must end at word/sentence boundaries, not mid-word."""
    # Build a very long summary to force truncation
    long_summary = "The system uses a shared cache boundary " + ("word " * 60)
    storage, _ = _seeded_storage(tmp_path)
    long_mem = _mem(
        title="Long fact",
        summary=long_summary,
        kind=MemoryKind.DECISION,
        source_ref="src/cache.py",
    )
    storage.upsert_memories([long_mem])

    pages = build_wiki(storage, sample_repo)

    # If truncated, the bullet must end with "..." preceded by a word character,
    # never a partial word like "word..." inside a longer token.
    for content in pages.values():
        for line in content.splitlines():
            if "Long fact" in line and "..." in line:
                # The character before "..." should be a word character or space
                idx = line.rfind("...")
                if idx > 0:
                    char_before = line[idx - 1]
                    assert char_before.isalnum() or char_before in " .,!?)", (
                        f"Mid-word truncation detected in: {line!r}"
                    )


def test_build_wiki_empty_store_honest_index(tmp_path: Path, sample_repo: Path) -> None:
    """Empty store produces an honest minimal index (no hallucinated data)."""
    db = tmp_path / ".onmc" / "memory.db"
    storage = SQLiteStorage(db)
    storage.initialize()

    pages = build_wiki(storage, sample_repo)
    index = pages["index.md"]

    assert "No memories" in index or "0" in index or "ingest" in index.lower()
    # Must not contain any memory titles (there are none)
    assert "Cache boundary" not in index


# ---------------------------------------------------------------------------
# Service method tests
# ---------------------------------------------------------------------------


def _init_service(repo: Path) -> OnmcService:
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest(no_llm=True)
    return svc


def test_generate_wiki_writes_files(sample_repo: Path) -> None:
    """generate_wiki() should write at least index.md and graph.md."""
    svc = _init_service(sample_repo)

    _, written = svc.generate_wiki()

    assert len(written) >= 2  # noqa: PLR2004
    names = [p.name for p in written]
    assert "index.md" in names
    assert "graph.md" in names


def test_generate_wiki_default_output_dir(sample_repo: Path) -> None:
    """Default output should land under .onmc/wiki/."""
    svc = _init_service(sample_repo)

    _, written = svc.generate_wiki()

    wiki_dir = sample_repo / ".onmc" / "wiki"
    assert all(str(p).startswith(str(wiki_dir)) for p in written)


def test_generate_wiki_custom_output_dir(sample_repo: Path, tmp_path: Path) -> None:
    """Custom --output dir should be used instead of the default."""
    svc = _init_service(sample_repo)
    custom_out = tmp_path / "docs" / "wiki"

    _, written = svc.generate_wiki(output_dir=custom_out)

    assert all(str(p).startswith(str(custom_out)) for p in written)
    assert (custom_out / "index.md").exists()


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_wiki_cli_exits_0(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc wiki`` should exit 0 after writing pages."""
    monkeypatch.chdir(sample_repo)
    svc = OnmcService(sample_repo)
    svc.init_project()
    svc.ingest(no_llm=True)

    result = runner.invoke(app, ["wiki"], catch_exceptions=False)

    assert result.exit_code == 0, result.output


def test_wiki_cli_writes_pages(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc wiki`` should create .onmc/wiki/index.md on disk."""
    monkeypatch.chdir(sample_repo)
    svc = OnmcService(sample_repo)
    svc.init_project()
    svc.ingest(no_llm=True)

    runner.invoke(app, ["wiki"], catch_exceptions=False)

    assert (sample_repo / ".onmc" / "wiki" / "index.md").exists()


def test_wiki_cli_custom_output(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``onmc wiki --output <dir>`` should write to the specified directory."""
    monkeypatch.chdir(sample_repo)
    svc = OnmcService(sample_repo)
    svc.init_project()
    svc.ingest(no_llm=True)
    out_dir = tmp_path / "my-wiki"

    result = runner.invoke(
        app, ["wiki", "--output", str(out_dir)], catch_exceptions=False
    )

    assert result.exit_code == 0
    assert (out_dir / "index.md").exists()


def test_wiki_cli_output_mentions_index(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI output should include the index path so the user knows where to look."""
    monkeypatch.chdir(sample_repo)
    svc = OnmcService(sample_repo)
    svc.init_project()
    svc.ingest(no_llm=True)

    result = runner.invoke(app, ["wiki"], catch_exceptions=False)

    assert "index.md" in result.output or "Index" in result.output


def test_wiki_cli_fails_without_init(tmp_path: Path) -> None:
    """``onmc wiki`` on an uninitialised repo should exit non-zero."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "oh_no_my_claudecode", "wiki"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    # Without a git repo / init, it should fail
    assert proc.returncode != 0
