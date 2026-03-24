from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.ingest.git_history import (
    build_file_stats,
    extract_git_memories,
    load_git_history,
)
from oh_no_my_claudecode.ingest.repo_tree import scan_repository_files
from oh_no_my_claudecode.models import MemoryKind


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
