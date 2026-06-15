"""Diff `.agent-memory/` JSON exports between two git commits.

Approach chosen: **committed-snapshot diff**.

For each commit, we run ``git show <commit>:.agent-memory/memories/<kind>/<id>.json``
to read memory entries as they existed in `.agent-memory/` at that commit.  We then
compare the two sets by memory id, reporting:

- **added** — present at commit_b but not commit_a
- **removed** — present at commit_a but not commit_b
- **changed** — present at both but with a different ``summary`` (title changes
  are also reported)

If `.agent-memory/` is not committed at *either* commit, we fall back to a
git-fact diff: report which files were changed between the two commits and note
clearly that memory-snapshot data is unavailable.

All subprocess calls use argument-list form (no ``shell=True``).  Commit-ish
values are never interpolated into shell strings.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class MemoryEntry:
    """Minimal representation of a memory entry from a committed snapshot."""

    id: str
    kind: str
    title: str
    summary: str


@dataclass
class ChangedMemory:
    """A memory that exists at both commits but whose content changed."""

    memory_id: str
    kind: str
    old_title: str
    new_title: str
    old_summary: str
    new_summary: str


@dataclass
class MemoryDiffResult:
    """Structured result of ``onmc memory-diff <commitA> <commitB>``."""

    commit_a: str
    commit_b: str
    short_a: str
    short_b: str
    date_a: str
    date_b: str

    added: list[MemoryEntry] = field(default_factory=list)
    removed: list[MemoryEntry] = field(default_factory=list)
    changed: list[ChangedMemory] = field(default_factory=list)

    # When .agent-memory/ is missing at one or both commits, we fall back to
    # a simple git-fact diff and set this flag.
    fallback_mode: bool = False
    # Files changed between commit_a and commit_b (fallback only)
    files_changed: list[str] = field(default_factory=list)
    fallback_reason: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
        return hash_result.stdout.strip(), date_result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "", ""


def _git_show_text(repo_root: Path, commit: str, rel_path: str) -> str | None:
    """Return the text content of *rel_path* at *commit*, or ``None`` if absent."""
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:{rel_path}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _ls_tree_paths(repo_root: Path, commit: str, prefix: str) -> list[str]:
    """List all blob paths under *prefix* at *commit* (e.g. ``.agent-memory/memories``)."""
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", commit, "--", prefix],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def _load_memories_at(repo_root: Path, commit: str) -> dict[str, MemoryEntry]:
    """Load all memory entries from ``.agent-memory/`` at *commit*.

    Returns an empty dict if the snapshot is absent at that commit.
    """
    paths = _ls_tree_paths(repo_root, commit, ".agent-memory/memories")
    result: dict[str, MemoryEntry] = {}
    for path in paths:
        if not path.endswith(".json"):
            continue
        text = _git_show_text(repo_root, commit, path)
        if text is None:
            continue
        try:
            data = json.loads(text)
            mem = data.get("memory", data)
            entry = MemoryEntry(
                id=str(mem.get("id", "")),
                kind=str(mem.get("kind", "")),
                title=str(mem.get("title", "")),
                summary=str(mem.get("summary", "")),
            )
            if entry.id:
                result[entry.id] = entry
        except (json.JSONDecodeError, KeyError):
            continue
    return result


def _git_diff_files(repo_root: Path, commit_a: str, commit_b: str) -> list[str]:
    """Return list of files changed between *commit_a* and *commit_b*."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", commit_a, commit_b],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diff_memory_at_commits(
    repo_root: Path,
    commit_a: str,
    commit_b: str,
) -> MemoryDiffResult:
    """Diff committed ``.agent-memory/`` snapshots between two commits.

    **What is time-bounded:** The memory entries as captured in the
    ``.agent-memory/`` directory at each commit.  Added/removed/changed entries
    represent what the agent's exported knowledge changed between those two
    commits.

    **What is NOT time-bounded:** Live SQLite storage is never read — this
    function is purely git-based.

    **Fallback:** When ``.agent-memory/memories`` is absent from the git tree at
    *either* commit, the function falls back to a plain ``git diff --name-only``
    between the two commits and sets ``fallback_mode=True`` on the result.
    """
    short_a, date_a = _resolve_commit(repo_root, commit_a)
    short_b, date_b = _resolve_commit(repo_root, commit_b)

    base_result = MemoryDiffResult(
        commit_a=commit_a,
        commit_b=commit_b,
        short_a=short_a,
        short_b=date_a,  # will be corrected below
        date_a=date_a,
        date_b=date_b,
    )
    # Correct the short hashes (copied wrong above — fix)
    base_result.short_a = short_a
    base_result.short_b = short_b

    memories_a = _load_memories_at(repo_root, commit_a)
    memories_b = _load_memories_at(repo_root, commit_b)

    snapshot_present = bool(memories_a or memories_b)
    # Distinguish "snapshot absent" from "snapshot present but empty"
    paths_a = _ls_tree_paths(repo_root, commit_a, ".agent-memory/memories")
    paths_b = _ls_tree_paths(repo_root, commit_b, ".agent-memory/memories")

    if not paths_a and not paths_b:
        # Fallback: no committed snapshot at either commit
        files_changed = _git_diff_files(repo_root, commit_a, commit_b)
        base_result.fallback_mode = True
        base_result.files_changed = files_changed
        base_result.fallback_reason = (
            f".agent-memory/ is not committed at {short_a or commit_a} "
            f"or {short_b or commit_b}. "
            "Run `onmc sync --commit` and commit .agent-memory/ to enable memory diffs."
        )
        return base_result

    _ = snapshot_present  # used implicitly by paths_a/paths_b check above

    ids_a = set(memories_a)
    ids_b = set(memories_b)

    added = [memories_b[mid] for mid in sorted(ids_b - ids_a)]
    removed = [memories_a[mid] for mid in sorted(ids_a - ids_b)]
    changed: list[ChangedMemory] = []
    for mid in sorted(ids_a & ids_b):
        ea = memories_a[mid]
        eb = memories_b[mid]
        if ea.summary != eb.summary or ea.title != eb.title:
            changed.append(
                ChangedMemory(
                    memory_id=mid,
                    kind=eb.kind,
                    old_title=ea.title,
                    new_title=eb.title,
                    old_summary=ea.summary,
                    new_summary=eb.summary,
                )
            )

    base_result.added = added
    base_result.removed = removed
    base_result.changed = changed
    return base_result


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def memory_diff_to_markdown(result: MemoryDiffResult) -> str:
    """Render a :class:`MemoryDiffResult` as a markdown string."""
    label_a = f"{result.short_a} ({result.date_a})" if result.short_a else result.commit_a
    label_b = f"{result.short_b} ({result.date_b})" if result.short_b else result.commit_b

    lines: list[str] = [
        f"# Memory diff: `{result.commit_a}` → `{result.commit_b}`",
        "",
        f"- **From:** {label_a}",
        f"- **To:** {label_b}",
        "",
    ]

    if result.fallback_mode:
        lines += [
            "> **Fallback mode** — `.agent-memory/` snapshot not found at these commits.",
            f"> {result.fallback_reason}",
            "",
            "## Files changed between commits",
            "",
        ]
        if result.files_changed:
            for path in result.files_changed:
                lines.append(f"- `{path}`")
        else:
            lines.append("_(no file changes detected)_")
        lines.append("")
        return "\n".join(lines)

    total = len(result.added) + len(result.removed) + len(result.changed)
    lines += [
        f"**Summary:** {len(result.added)} added, "
        f"{len(result.removed)} removed, "
        f"{len(result.changed)} changed "
        f"(of {total} total changes)",
        "",
    ]

    if result.added:
        lines += ["## Added knowledge", ""]
        for entry in result.added:
            lines.append(f"### + {entry.title} `[{entry.kind}]`")
            lines.append(f"_id: {entry.id}_")
            lines.append("")
            lines.append(entry.summary)
            lines.append("")

    if result.removed:
        lines += ["## Removed / invalidated knowledge", ""]
        for entry in result.removed:
            lines.append(f"### - {entry.title} `[{entry.kind}]`")
            lines.append(f"_id: {entry.id}_")
            lines.append("")
            lines.append(entry.summary)
            lines.append("")

    if result.changed:
        lines += ["## Changed knowledge", ""]
        for change in result.changed:
            lines.append(f"### ~ {change.new_title} `[{change.kind}]`")
            lines.append(f"_id: {change.memory_id}_")
            lines.append("")
            if change.old_title != change.new_title:
                lines.append(f"**Title:** `{change.old_title}` → `{change.new_title}`")
                lines.append("")
            lines.append("**Before:**")
            lines.append(f"> {change.old_summary}")
            lines.append("")
            lines.append("**After:**")
            lines.append(f"> {change.new_summary}")
            lines.append("")

    if not result.added and not result.removed and not result.changed:
        lines += ["_(no differences in committed memory snapshots)_", ""]

    return "\n".join(lines)
