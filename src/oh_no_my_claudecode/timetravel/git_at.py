"""Time-bounded git history helpers for `onmc why --at <commit>`."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Commit subject max length for display — mirrors why/compiler.py constant
_MAX_SUBJECT_LEN = 72
# Maximum recent commit subjects to surface
_MAX_RECENT_SUBJECTS = 5


@dataclass
class GitHistoryAt:
    """Git history for a file, bounded to a specific commit-ish."""

    commit_count: int
    recent_subjects: list[str] = field(default_factory=list)
    # The resolved short hash of the boundary commit (for labelling)
    at_short: str = ""
    # Human-readable date of the boundary commit
    at_date: str = ""


def _resolve_commit(repo_root: Path, commit: str) -> tuple[str, str]:
    """Return (short_hash, date_str) for *commit*, or ("", "") on failure."""
    try:
        hash_result = subprocess.run(
            ["git", "rev-parse", "--short", commit],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        date_result = subprocess.run(
            ["git", "log", "-1", "--format=%ci", commit],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        short = hash_result.stdout.strip()
        date = date_result.stdout.strip()
        return short, date
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "", ""


def fetch_git_history_at(
    repo_root: Path,
    rel_path: str,
    at_commit: str,
) -> GitHistoryAt | None:
    """Return git log for *rel_path* bounded at *at_commit*.

    Uses ``git log <commit> -- <path>`` so only commits reachable from
    *at_commit* are returned.  This is fully deterministic and offline.

    Returns ``None`` when git is unavailable or the path has no history
    at that commit.
    """
    short, date = _resolve_commit(repo_root, at_commit)
    if not short:
        return None

    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "--follow",
                "--oneline",
                at_commit,
                "--",
                rel_path,
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        return GitHistoryAt(commit_count=0, at_short=short, at_date=date)

    subjects: list[str] = []
    for line in lines[:_MAX_RECENT_SUBJECTS]:
        parts = line.split(" ", 1)
        subject = parts[1] if len(parts) == 2 else line
        subject = subject[:_MAX_SUBJECT_LEN]
        subjects.append(subject)

    return GitHistoryAt(
        commit_count=len(lines),
        recent_subjects=subjects,
        at_short=short,
        at_date=date,
    )
