"""Tests for ``onmc blame`` — governance map for a file's regions."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.blame.compiler import (
    blame_result_to_markdown,
    compile_blame,
)
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryKind

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_service(repo: Path) -> OnmcService:
    svc = OnmcService(repo)
    svc.init_project()
    svc.ingest(no_llm=True)
    return svc


def _add_memory(
    svc: OnmcService,
    *,
    kind: MemoryKind = MemoryKind.INVARIANT,
    title: str,
    summary: str,
    source_ref: str = "",
) -> None:
    svc.add_manual_memory(
        kind=kind,
        title=title,
        summary=summary,
        source_ref=source_ref or "manual:test",
    )


# ---------------------------------------------------------------------------
# Symbol-level attachment
# ---------------------------------------------------------------------------


def test_blame_attaches_memory_to_named_function(sample_repo: Path) -> None:
    """A memory mentioning 'invalidate_cache' must attach to that symbol anchor."""
    svc = _init_service(sample_repo)
    _add_memory(
        svc,
        kind=MemoryKind.INVARIANT,
        title="invalidate_cache must not skip keys",
        summary="Every call to invalidate_cache must pass a non-empty key.",
        source_ref="src/cache.py",
    )

    _, _, storage = svc._load_context()
    result = compile_blame(sample_repo, storage, "src/cache.py")

    assert result.has_data
    # The function 'invalidate_cache' should appear as an anchor.
    anchor_names = [a.anchor for a in result.anchors]
    assert "invalidate_cache" in anchor_names, f"anchors: {anchor_names}"
    matching = next(a for a in result.anchors if a.anchor == "invalidate_cache")
    assert matching.line is not None
    assert any(
        "invalidate_cache must not skip keys" in m.title for m in matching.memories
    )


def test_blame_file_level_bucket_for_unmatched_memory(sample_repo: Path) -> None:
    """A memory that names no symbol lands in file_level_memories."""
    svc = _init_service(sample_repo)
    _add_memory(
        svc,
        kind=MemoryKind.HOTSPOT,
        title="cache.py changes break workers",
        summary="Any change here ripples to worker.py immediately.",
        source_ref="src/cache.py",
    )

    _, _, storage = svc._load_context()
    result = compile_blame(sample_repo, storage, "src/cache.py")

    assert result.has_data
    # "cache.py changes break workers" doesn't mention any specific symbol.
    file_titles = [m.title for m in result.file_level_memories]
    assert "cache.py changes break workers" in file_titles


def test_blame_unknown_file_returns_empty(sample_repo: Path) -> None:
    """No memories → has_data=False and honest empty result."""
    svc = _init_service(sample_repo)
    _, _, storage = svc._load_context()

    result = compile_blame(sample_repo, storage, "no/such/file.py")

    assert not result.has_data
    assert result.anchors == []
    assert result.file_level_memories == []


def test_blame_markdown_unknown_file_says_nothing_known(sample_repo: Path) -> None:
    """Markdown for an unknown file must include the 'no recorded knowledge' notice."""
    svc = _init_service(sample_repo)
    _, _, storage = svc._load_context()

    result = compile_blame(sample_repo, storage, "no/such/file.py")
    md = blame_result_to_markdown(result)

    assert "No recorded knowledge" in md or "no recorded knowledge" in md.lower()


# ---------------------------------------------------------------------------
# Markdown headings (.md files)
# ---------------------------------------------------------------------------


def test_blame_md_file_maps_to_headings(sample_repo: Path) -> None:
    """Memories naming a markdown section attach to the heading anchor."""
    svc = _init_service(sample_repo)
    _add_memory(
        svc,
        kind=MemoryKind.DECISION,
        title="Architecture heading describes cache boundary",
        summary="The Architecture section describes the shared cache boundary decision.",
        source_ref="README.md",
    )

    _, _, storage = svc._load_context()
    result = compile_blame(sample_repo, storage, "README.md")

    assert result.has_data
    # README.md has "## Architecture" heading — memory mentions "Architecture".
    anchor_names = [a.anchor for a in result.anchors]
    assert "Architecture" in anchor_names, f"anchors: {anchor_names}"
    matching = next(a for a in result.anchors if a.anchor == "Architecture")
    assert matching.line is not None


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_blame_missing_file_degrades_gracefully(sample_repo: Path, tmp_path: Path) -> None:
    """compile_blame on a file that exists in the store but not on disk still works."""
    svc = _init_service(sample_repo)
    _add_memory(
        svc,
        kind=MemoryKind.INVARIANT,
        title="ghost_func is critical",
        summary="Do not remove ghost_func.",
        source_ref="src/ghost.py",
    )

    _, _, storage = svc._load_context()
    result = compile_blame(sample_repo, storage, "src/ghost.py")

    # File doesn't exist, so symbols can't be extracted → all memories go file-level.
    assert result.has_data
    assert result.parse_skipped
    assert not result.file_exists
    file_titles = [m.title for m in result.file_level_memories]
    assert "ghost_func is critical" in file_titles


def test_blame_binary_file_degrades_gracefully(sample_repo: Path) -> None:
    """A binary .py file (NUL bytes) must not crash symbol extraction."""
    binary_file = sample_repo / "src" / "binary_module.py"
    binary_file.write_bytes(b"\x00\x01\x02\x03" * 100)

    svc = _init_service(sample_repo)
    _add_memory(
        svc,
        kind=MemoryKind.GOTCHA,
        title="binary_module gotcha",
        summary="This file is actually binary data, not real Python.",
        source_ref="src/binary_module.py",
    )

    _, _, storage = svc._load_context()
    result = compile_blame(sample_repo, storage, "src/binary_module.py")

    # Must not raise; memories fall back to file-level.
    assert result.has_data
    assert result.parse_skipped


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_blame_cli_command(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    svc = _init_service(sample_repo)
    _add_memory(
        svc,
        kind=MemoryKind.INVARIANT,
        title="invalidate_cache key must be non-empty",
        summary="Passing empty string to invalidate_cache breaks the cache layer.",
        source_ref="src/cache.py",
    )

    result = runner.invoke(app, ["blame", "src/cache.py"])

    assert result.exit_code == 0, result.output
    assert "onmc blame" in result.output
    assert "Wrote blame report" in result.output


def test_blame_cli_unknown_path_succeeds(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    _init_service(sample_repo)

    result = runner.invoke(app, ["blame", "totally/nonexistent.py"])

    assert result.exit_code == 0, result.output
    assert "no" in result.output.lower() or "nothing" in result.output.lower()


def test_blame_cli_terse_flag(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    svc = _init_service(sample_repo)
    _add_memory(
        svc,
        kind=MemoryKind.HOTSPOT,
        title="cache.py is high-churn",
        summary="This file changes on every release.",
        source_ref="src/cache.py",
    )

    result = runner.invoke(app, ["blame", "src/cache.py", "--terse"])

    assert result.exit_code == 0, result.output
    assert "blame:" in result.output


# ---------------------------------------------------------------------------
# Service integration
# ---------------------------------------------------------------------------


def test_blame_service_writes_artifact(sample_repo: Path) -> None:
    svc = _init_service(sample_repo)
    _add_memory(
        svc,
        kind=MemoryKind.INVARIANT,
        title="invalidate_cache contract",
        summary="Always call invalidate_cache after a write.",
        source_ref="src/cache.py",
    )

    _, result = svc.blame("src/cache.py")

    assert result.output_path, "service.blame must write a markdown artifact"
    artifact = Path(result.output_path)
    assert artifact.is_file()
    assert "blame" in artifact.name
    content = artifact.read_text(encoding="utf-8")
    assert "Blame map" in content
