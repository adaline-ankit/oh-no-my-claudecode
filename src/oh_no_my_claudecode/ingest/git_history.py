from __future__ import annotations

import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from itertools import combinations
from pathlib import Path

from oh_no_my_claudecode.core.repo import is_test_path, path_bucket
from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind, RepoFileRecord, SourceType
from oh_no_my_claudecode.utils.text import shorten, stable_id, tokenize, unique_preserve
from oh_no_my_claudecode.utils.time import parse_datetime, utc_now


@dataclass(slots=True)
class GitCommitRecord:
    commit_hash: str
    authored_at: str
    subject: str
    files: list[str]


def load_git_history(repo_root: Path, *, max_commits: int) -> list[GitCommitRecord]:
    marker = "__ONMC_COMMIT__"
    format_string = f"{marker}%n%H%x1f%ad%x1f%s"
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"--max-count={max_commits}",
                "--date=iso-strict",
                f"--pretty=format:{format_string}",
                "--name-only",
                "--",
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return []

    commits: list[GitCommitRecord] = []
    for raw_record in result.stdout.split(marker):
        raw_record = raw_record.strip("\n")
        if not raw_record:
            continue
        lines = raw_record.splitlines()
        header = lines[0].split("\x1f")
        if len(header) < 3:
            continue
        commit_hash, authored_at, subject = header[:3]
        files = [line.strip() for line in lines[1:] if line.strip()]
        commits.append(
            GitCommitRecord(
                commit_hash=commit_hash,
                authored_at=authored_at,
                subject=subject.strip(),
                files=files,
            )
        )
    return commits


def build_file_stats(
    repo_files: list[RepoFileRecord],
    commits: list[GitCommitRecord],
) -> list[FileStat]:
    stats = {
        record.path: FileStat(
            path=record.path,
            change_count=0,
            recent_change_count=0,
            last_modified_at=None,
            is_test=record.is_test,
            top_level_dir=path_bucket(record.path),
        )
        for record in repo_files
    }
    recent_cutoff = utc_now() - timedelta(days=30)

    for commit in commits:
        authored_at = parse_datetime(commit.authored_at)
        touched_files = unique_preserve(path for path in commit.files if path in stats)
        for path in touched_files:
            stat = stats[path]
            stat.change_count += 1
            if authored_at and authored_at >= recent_cutoff:
                stat.recent_change_count += 1
            if authored_at and (
                stat.last_modified_at is None or authored_at > stat.last_modified_at
            ):
                stat.last_modified_at = authored_at

    ordered = sorted(
        stats.values(),
        key=lambda item: (-item.change_count, -item.recent_change_count, item.path),
    )
    return ordered


def extract_git_memories(
    commits: list[GitCommitRecord],
    file_stats: list[FileStat],
) -> list[MemoryEntry]:
    if not commits:
        return []

    now = utc_now()
    memories: list[MemoryEntry] = []

    for stat in file_stats[:4]:
        if stat.change_count <= 1:
            continue
        details = (
            f"Observed {stat.change_count} modifying commits "
            f"in the last {len(commits)} analyzed commits for {stat.path}. "
            f"Recent churn count in the last 30 days: {stat.recent_change_count}."
        )
        memories.append(
            MemoryEntry(
                id=stable_id(stat.path, "hotspot", prefix=MemoryKind.HOTSPOT.value),
                kind=MemoryKind.HOTSPOT,
                title=f"High-churn file: {stat.path}",
                summary=shorten(details),
                details=details,
                source_type=SourceType.GIT,
                source_ref=stat.path,
                tags=tokenize(stat.top_level_dir)[:6],
                confidence=min(0.55 + (stat.change_count * 0.05), 0.9),
                created_at=now,
                updated_at=now,
            )
        )

    directory_counts: Counter[str] = Counter()
    co_modified_pairs: Counter[tuple[str, str]] = Counter()
    source_to_tests: Counter[tuple[str, str]] = Counter()

    current_paths = {stat.path for stat in file_stats}
    for commit in commits:
        touched = unique_preserve(path for path in commit.files if path in current_paths)
        buckets = sorted({path_bucket(path) for path in touched if path_bucket(path) != "."})
        for bucket in buckets:
            directory_counts[bucket] += 1
        for left, right in combinations(buckets, 2):
            co_modified_pairs[(left, right)] += 1

        source_dirs = {path_bucket(path) for path in touched if not is_test_path(path)}
        test_dirs = {path_bucket(path) for path in touched if is_test_path(path)}
        for source_dir in source_dirs:
            for test_dir in test_dirs:
                if source_dir != test_dir:
                    source_to_tests[(source_dir, test_dir)] += 1

    for directory, count in directory_counts.most_common(3):
        if count <= 1:
            continue
        memories.append(
            MemoryEntry(
                id=stable_id(directory, "dir-hotspot", prefix=MemoryKind.HOTSPOT.value),
                kind=MemoryKind.HOTSPOT,
                title=f"Hotspot subsystem: {directory}",
                summary=(
                    f"{directory} shows repeated churn across {count} commits "
                    "in the analyzed history."
                ),
                details=(
                    f"Git history suggests {directory} changes frequently. "
                    "Treat this as a risk hint and inspect recent commits "
                    "before editing."
                ),
                source_type=SourceType.GIT,
                source_ref=directory,
                tags=tokenize(directory)[:6],
                confidence=min(0.5 + (count * 0.04), 0.85),
                created_at=now,
                updated_at=now,
            )
        )

    for (left, right), count in co_modified_pairs.most_common(3):
        if count <= 1:
            continue
        memories.append(
            MemoryEntry(
                id=stable_id(left, right, "co-modified", prefix=MemoryKind.GIT_PATTERN.value),
                kind=MemoryKind.GIT_PATTERN,
                title=f"Co-modified areas: {left} + {right}",
                summary=f"{left} and {right} were changed together in {count} commits.",
                details=(
                    "Git history suggests these areas often move together. "
                    "Use this as a review hint, not an architectural rule."
                ),
                source_type=SourceType.GIT,
                source_ref=f"{left}|{right}",
                tags=tokenize(left)[:3] + tokenize(right)[:3],
                confidence=min(0.45 + (count * 0.05), 0.8),
                created_at=now,
                updated_at=now,
            )
        )

    for (source_dir, test_dir), count in source_to_tests.most_common(3):
        if count <= 1:
            continue
        memories.append(
            MemoryEntry(
                id=stable_id(
                    source_dir,
                    test_dir,
                    "tests",
                    prefix=MemoryKind.VALIDATION_RULE.value,
                ),
                kind=MemoryKind.VALIDATION_RULE,
                title=f"Tests often accompany {source_dir}",
                summary=(
                    f"Changes under {source_dir} frequently land with {test_dir} ({count} commits)."
                ),
                details=(
                    f"History suggests reviewing or updating tests in {test_dir} "
                    f"when touching {source_dir}. This is a heuristic from "
                    "git co-change patterns."
                ),
                source_type=SourceType.GIT,
                source_ref=f"{source_dir}|{test_dir}",
                tags=tokenize(source_dir)[:3] + ["tests"] + tokenize(test_dir)[:3],
                confidence=min(0.5 + (count * 0.05), 0.82),
                created_at=now,
                updated_at=now,
            )
        )

    return memories
