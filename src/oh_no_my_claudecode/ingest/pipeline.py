from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.core.repo import path_bucket
from oh_no_my_claudecode.ingest.docs import discover_doc_paths, extract_doc_memories
from oh_no_my_claudecode.ingest.git_history import (
    GitCommitRecord,
    build_file_stats,
    extract_git_memories,
    load_git_history,
)
from oh_no_my_claudecode.ingest.repo_tree import (
    detect_project_hints,
    infer_repo_shape_memories,
    scan_repository_files,
    scan_selected_files,
)
from oh_no_my_claudecode.models import IngestResult, MemoryEntry, ProjectConfig
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


def run_ingest_files(
    repo_root: Path,
    config: ProjectConfig,
    storage: SQLiteStorage,
    paths: list[str],
) -> IngestResult:
    selected_repo_files, warnings = scan_selected_files(
        repo_root,
        paths=paths,
        exclude_dirs=config.ingest.exclude_dirs,
    )
    commits = load_git_history(repo_root, max_commits=config.ingest.max_git_commits)
    selected_stats = build_file_stats(selected_repo_files, commits)

    relative_paths = [record.path for record in selected_repo_files]
    targeted_docs = _targeted_doc_paths(repo_root, config, relative_paths)
    doc_memories = [
        memory
        for doc_path in targeted_docs
        for memory in extract_doc_memories(
            repo_root,
            doc_path,
            max_chars=config.ingest.max_doc_section_chars,
        )
    ]

    shape_memories = _shape_memories_for_paths(repo_root, config, relative_paths)
    git_memories = _git_memories_for_paths(repo_root, config, storage, commits, relative_paths)
    memories = [*doc_memories, *shape_memories, *git_memories]

    if targeted_docs:
        storage.delete_generated_memories_by_source_refs(
            [path.relative_to(repo_root).as_posix() for path in targeted_docs]
        )
    storage.upsert_repo_files(selected_repo_files)
    storage.upsert_file_stats(selected_stats)
    new_count, updated_count = storage.upsert_memories(memories)

    generated_at = utc_now()
    storage.set_meta("last_ingest_at", isoformat_utc(generated_at))
    storage.set_meta("last_ingest_repo_files", str(len(storage.list_repo_files())))
    storage.set_meta("last_ingest_doc_count", str(len(targeted_docs)))
    storage.set_meta("last_ingest_commit_count", str(len(commits)))

    return IngestResult(
        memory_count=len(memories),
        new_memory_count=new_count,
        updated_memory_count=updated_count,
        repo_file_count=len(selected_repo_files),
        file_stat_count=len(selected_stats),
        doc_count=len(targeted_docs),
        commit_count=len(commits),
        generated_at=generated_at,
        notes=warnings,
    )


def _targeted_doc_paths(
    repo_root: Path,
    config: ProjectConfig,
    relative_paths: list[str],
) -> list[Path]:
    allowed = set(relative_paths)
    return [
        path
        for path in discover_doc_paths(repo_root, globs=config.ingest.doc_globs)
        if path.relative_to(repo_root).as_posix() in allowed
    ]


def _shape_memories_for_paths(
    repo_root: Path,
    config: ProjectConfig,
    relative_paths: list[str],
) -> list[MemoryEntry]:
    if not _needs_shape_refresh(relative_paths):
        return []
    repo_files = scan_repository_files(repo_root, exclude_dirs=config.ingest.exclude_dirs)
    hints = detect_project_hints(repo_root, repo_files)
    shape_memories = infer_repo_shape_memories(repo_root, hints)
    allowed_sources = {"pyproject.toml", "package.json", ".github/workflows", "repo_tree"}
    return [memory for memory in shape_memories if memory.source_ref in allowed_sources]


def _git_memories_for_paths(
    repo_root: Path,
    config: ProjectConfig,
    storage: SQLiteStorage,
    commits: list[GitCommitRecord],
    relative_paths: list[str],
) -> list[MemoryEntry]:
    if not relative_paths:
        return []
    repo_files = storage.list_repo_files()
    if not repo_files:
        repo_files = scan_repository_files(repo_root, exclude_dirs=config.ingest.exclude_dirs)
    for record in scan_repository_files(repo_root, exclude_dirs=config.ingest.exclude_dirs):
        if record.path not in {item.path for item in repo_files}:
            repo_files.append(record)
    file_stats = build_file_stats(repo_files, commits)
    all_git_memories = extract_git_memories(commits, file_stats)
    target_buckets = {path_bucket(path) for path in relative_paths}
    selected = []
    for memory in all_git_memories:
        refs = set(memory.source_ref.split("|"))
        if refs & set(relative_paths):
            selected.append(memory)
            continue
        if refs & target_buckets:
            selected.append(memory)
    return selected


def _needs_shape_refresh(relative_paths: list[str]) -> bool:
    return any(
        path == "pyproject.toml"
        or path == "package.json"
        or path.startswith(".github/workflows/")
        for path in relative_paths
    )
