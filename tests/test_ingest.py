from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.ingest.docs import discover_doc_paths
from oh_no_my_claudecode.ingest.git_history import (
    build_file_stats,
    extract_git_memories,
    load_git_history,
)
from oh_no_my_claudecode.ingest.pipeline import deduplicate_memories
from oh_no_my_claudecode.ingest.repo_tree import scan_repository_files
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.utils.time import utc_now


def test_hotspot_detection_and_git_patterns(sample_repo: Path) -> None:
    repo_files = scan_repository_files(
        sample_repo,
        exclude_dirs=[".git", ".onmc", ".venv", "node_modules", "__pycache__"],
    )
    commits = load_git_history(sample_repo, max_commits=50)
    stats = build_file_stats(repo_files, commits)
    memories = extract_git_memories(commits, stats)

    assert commits
    assert stats[0].path == "src/cache.py"
    assert any(
        memory.kind == MemoryKind.HOTSPOT and memory.source_ref == "src/cache.py"
        for memory in memories
    )
    assert any(memory.kind == MemoryKind.VALIDATION_RULE for memory in memories)


def test_translated_readmes_and_output_docs_are_excluded(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Primary\n", encoding="utf-8")
    (repo_root / "README.de.md").write_text("# Deutsch\n", encoding="utf-8")
    (repo_root / "CLAUDE.md").write_text("# Generated\n", encoding="utf-8")
    (repo_root / "AGENTS.md").write_text("# Agent output\n", encoding="utf-8")

    discovered = discover_doc_paths(
        repo_root,
        globs=["README*", "CLAUDE.md", "AGENTS.md"],
    )

    assert [path.name for path in discovered] == ["README.md"]


def test_deduplicate_memories_preserves_higher_confidence_record() -> None:
    now = utc_now()
    stronger = MemoryEntry(
        id="decision-strong",
        kind=MemoryKind.DECISION,
        title="Shared cache boundary",
        summary="Keep the shared cache boundary.",
        details="Keep the shared cache boundary.",
        source_type=SourceType.LLM_EXTRACTED,
        source_ref="pr:42",
        tags=["cache"],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    weaker = stronger.model_copy(
        update={
            "id": "decision-weak",
            "title": "Cache shared boundary",
            "confidence": 0.4,
        }
    )

    deduped, removed = deduplicate_memories([weaker, stronger])

    assert removed == 1
    assert [memory.id for memory in deduped] == ["decision-strong"]
