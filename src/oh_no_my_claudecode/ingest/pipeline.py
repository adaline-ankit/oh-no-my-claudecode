from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.ingest.docs import discover_doc_paths, extract_doc_memories
from oh_no_my_claudecode.ingest.git_history import (
    build_file_stats,
    extract_git_memories,
    load_git_history,
)
from oh_no_my_claudecode.ingest.repo_tree import (
    detect_project_hints,
    infer_repo_shape_memories,
    scan_repository_files,
)
from oh_no_my_claudecode.models import IngestResult, ProjectConfig
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now


def run_ingest(repo_root: Path, config: ProjectConfig, storage: SQLiteStorage) -> IngestResult:
    repo_files = scan_repository_files(repo_root, exclude_dirs=config.ingest.exclude_dirs)
    doc_paths = discover_doc_paths(repo_root, globs=config.ingest.doc_globs)
    commits = load_git_history(repo_root, max_commits=config.ingest.max_git_commits)
    file_stats = build_file_stats(repo_files, commits)
    hints = detect_project_hints(repo_root, repo_files)

    memories = []
    for doc_path in doc_paths:
        memories.extend(
            extract_doc_memories(
                repo_root,
                doc_path,
                max_chars=config.ingest.max_doc_section_chars,
            )
        )
    memories.extend(infer_repo_shape_memories(repo_root, hints))
    memories.extend(extract_git_memories(commits, file_stats))

    storage.replace_repo_files(repo_files)
    storage.replace_file_stats(file_stats)
    new_count, updated_count = storage.replace_generated_memories(memories)

    generated_at = utc_now()
    storage.set_meta("last_ingest_at", isoformat_utc(generated_at))
    storage.set_meta("last_ingest_repo_files", str(len(repo_files)))
    storage.set_meta("last_ingest_doc_count", str(len(doc_paths)))
    storage.set_meta("last_ingest_commit_count", str(len(commits)))

    notes: list[str] = []
    if not commits:
        notes.append("No git commits were available; hotspot and git-pattern inference is limited.")
    if not doc_paths:
        notes.append("No markdown docs matched the configured glob set.")

    return IngestResult(
        memory_count=len(memories),
        new_memory_count=new_count,
        updated_memory_count=updated_count,
        repo_file_count=len(repo_files),
        file_stat_count=len(file_stats),
        doc_count=len(doc_paths),
        commit_count=len(commits),
        generated_at=generated_at,
        notes=notes,
    )
