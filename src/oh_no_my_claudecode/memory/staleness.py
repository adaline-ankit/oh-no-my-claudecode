"""Provenance-based staleness detection for ONMC memories.

For each MemoryEntry, classifies whether its file anchor is:
  - "fresh"      : anchor file exists and has not changed since memory.updated_at
  - "stale"      : anchor file exists but changed *after* memory.updated_at
  - "orphaned"   : anchor file no longer exists on disk
  - "unanchored" : no resolvable file anchor — leave untouched

Anchor extraction heuristics
-----------------------------
source_ref formats observed in the wild:
  doc / code    -> bare relative path:            "README.md", "src/cache.py"
  git multi     -> pipe-separated paths:          "src/foo.py|tests/test_foo.py"
  git hotspot   -> directory bucket:              "src"
  special       -> non-path sentinel:             "pyproject.toml", "package.json",
                                                  ".github/workflows", "repo_tree"
  manual        -> "manual:..." or free text:     "manual:one"

We extract the *first* pipe-separated token that looks like a file path (has an
extension or is a known anchor name) and use that as the anchor. If nothing
resolves to an actual path we classify as "unanchored".
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from oh_no_my_claudecode.models.memory import MemoryEntry, StalenessLabel

# source_refs that never correspond to a checkable file path on disk
_NON_PATH_SENTINELS: frozenset[str] = frozenset(
    {
        "repo_tree",
        "manual",
        "pyproject.toml",
        "package.json",
        ".github/workflows",
    }
)


def _looks_like_file_path(token: str) -> bool:
    """Return True when *token* is plausibly a relative file path."""
    if not token or token.startswith("manual:") or ":" in token:
        return False
    p = Path(token)
    # Has an extension (e.g. ".md", ".py") or ends in a known config filename
    if p.suffix:
        return True
    # Bare names that are still valid anchors (directory sentinels are not)
    return token in _NON_PATH_SENTINELS


def extract_anchor_path(source_ref: str) -> str | None:
    """Return the repo-relative file path embedded in *source_ref*, or None.

    Handles:
    - plain paths: "src/cache.py" -> "src/cache.py"
    - pipe-joined: "src/a.py|tests/test_a.py" -> "src/a.py"
    - sentinel values ("repo_tree", "manual:...", ...): None
    - bare directory names ("src"): None  (no extension, not a sentinel)
    """
    if not source_ref:
        return None

    candidates = source_ref.split("|")
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        if candidate in _NON_PATH_SENTINELS:
            # e.g. "pyproject.toml" is a valid anchor (has extension)
            p = Path(candidate)
            if p.suffix:
                return candidate
            return None  # e.g. "repo_tree"
        if candidate.startswith("manual:") or ":" in candidate:
            continue
        p = Path(candidate)
        if p.suffix:
            return candidate
        # No extension and not a sentinel → directory bucket, skip
    return None


def _git_last_commit_time(repo_root: Path, rel_path: str) -> datetime | None:
    """Return the UTC timestamp of the most recent git commit that touched *rel_path*.

    Returns None when git is unavailable, the path has no commits, or any error
    occurs. Never raises.
    """
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%aI", "--", rel_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).astimezone(UTC)
    except ValueError:
        return None


def _file_mtime_utc(abs_path: Path) -> datetime | None:
    """Return the filesystem mtime as UTC datetime, or None on error."""
    try:
        ts = abs_path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=UTC)
    except OSError:
        return None


def classify_staleness(
    repo_root: Path,
    memory: MemoryEntry,
) -> StalenessLabel:
    """Classify the staleness of *memory* relative to its file anchor.

    Algorithm:
      1. Extract the anchor path from source_ref.
      2. If none found → "unanchored".
      3. Resolve to an absolute path under repo_root.
      4. If the file does not exist → "orphaned".
      5. Determine when the file last changed:
           a. try git last-commit time for the path
           b. fall back to filesystem mtime
      6. Compare change time to memory.updated_at:
           - change_time <= updated_at → "fresh"
           - change_time >  updated_at → "stale"
    """
    anchor_rel = extract_anchor_path(memory.source_ref)
    if anchor_rel is None:
        return "unanchored"

    abs_path = repo_root / anchor_rel
    if not abs_path.exists():
        return "orphaned"

    change_time = _git_last_commit_time(repo_root, anchor_rel)
    if change_time is None:
        change_time = _file_mtime_utc(abs_path)
    if change_time is None:
        # Cannot determine change time; conservatively treat as fresh
        return "fresh"

    # Ensure both timestamps are timezone-aware for comparison
    memory_updated = memory.updated_at
    if memory_updated.tzinfo is None:
        memory_updated = memory_updated.replace(tzinfo=UTC)

    if change_time > memory_updated:
        return "stale"
    return "fresh"
