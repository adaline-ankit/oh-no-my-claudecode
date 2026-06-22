"""PreToolUse hook: warn before edits land on a dangerous file.

Fires before the agent edits/writes a file and surfaces high-signal danger
from the memory store — hotspots, invariants, and recorded failed approaches.

Design contract
---------------
- Pure and testable: ``compile_pretool_warning`` takes storage + paths, no I/O.
- Tiny output: this fires on EVERY edit; markdown must be ≤ ~200 tokens.
- Empty output: unknown / untracked file → emit nothing (no noise).
- Never block: any error → empty string (caller exits 0 unconditionally).
"""

from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.models import FileStat, MemoryEntry, MemoryKind
from oh_no_my_claudecode.storage import SQLiteStorage

# Churn thresholds — mirror why/compiler.py _HIGH_CHURN_THRESHOLD
_HIGH_CHURN_TOTAL = 3
_HIGH_CHURN_RECENT = 2

# Memory kinds that signal "danger before editing"
_DANGER_KINDS = frozenset(
    {
        MemoryKind.INVARIANT,
        MemoryKind.HOTSPOT,
        MemoryKind.GIT_PATTERN,
        MemoryKind.FAILED_APPROACH,
    }
)

# Max items surfaced per section (keep output tiny)
_MAX_ITEMS = 3


def _normalize_path(repo_root: Path, raw_path: str) -> str:
    """Return repo-relative POSIX string, tolerating absolute or relative input."""
    candidate = Path(raw_path)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(repo_root).as_posix()
        except ValueError:
            return raw_path
    return candidate.as_posix()


def _memory_matches_path(memory: MemoryEntry, rel_path: str) -> bool:
    """Return True if the memory plausibly references *rel_path*."""
    base = Path(rel_path).name
    return any(
        rel_path in field or base in field
        for field in (memory.source_ref, memory.title, memory.summary, memory.details)
        if field
    )


def compile_pretool_warning(
    storage: SQLiteStorage,
    repo_root: Path,
    file_path: str,
) -> tuple[str, int]:
    """Build a terse danger-warning for *file_path* from existing memory.

    Args:
        storage: Initialised SQLiteStorage instance.
        repo_root: Absolute path to the git repository root.
        file_path: The file about to be edited (absolute or repo-relative).

    Returns:
        ``(markdown, n)`` where *n* is the count of signals found.
        Returns ``("", 0)`` when nothing notable is known.
    """
    rel_path = _normalize_path(repo_root, file_path)

    # ── file stat → hotspot churn check ─────────────────────────────────
    file_stat: FileStat | None = None
    try:
        stats = storage.list_file_stats()
        file_stat = next((s for s in stats if s.path == rel_path), None)
    except Exception:  # noqa: BLE001, S110
        pass

    is_high_churn = (
        file_stat is not None
        and (
            file_stat.change_count >= _HIGH_CHURN_TOTAL
            or file_stat.recent_change_count >= _HIGH_CHURN_RECENT
        )
    )

    # ── memories matching this path ──────────────────────────────────────
    invariants: list[MemoryEntry] = []
    failed_approaches: list[MemoryEntry] = []
    hotspot_memories: list[MemoryEntry] = []

    try:
        memories = storage.list_memories()
    except Exception:  # noqa: BLE001
        memories = []

    for memory in memories:
        if memory.kind not in _DANGER_KINDS:
            continue
        if not _memory_matches_path(memory, rel_path):
            continue
        if memory.kind == MemoryKind.INVARIANT:
            invariants.append(memory)
        elif memory.kind == MemoryKind.FAILED_APPROACH:
            failed_approaches.append(memory)
        else:
            hotspot_memories.append(memory)

    n = (
        (1 if is_high_churn else 0)
        + len(invariants)
        + len(failed_approaches)
        + len(hotspot_memories)
    )
    if n == 0:
        return "", 0

    # ── render ────────────────────────────────────────────────────────────
    lines: list[str] = [f"**onmc: editing `{rel_path}` — danger signals**", ""]

    if is_high_churn and file_stat is not None:
        lines.append(
            f"- HIGH-CHURN: {file_stat.change_count} commits total, "
            f"{file_stat.recent_change_count} in the last 30 days — edit carefully."
        )

    for m in hotspot_memories[:_MAX_ITEMS]:
        lines.append(f"- HOTSPOT: {m.title} — {m.summary}")

    for m in invariants[:_MAX_ITEMS]:
        lines.append(f"- INVARIANT: {m.title} — {m.summary}")

    for m in failed_approaches[:_MAX_ITEMS]:
        lines.append(f"- FAILED BEFORE: {m.title} — {m.summary}")

    return "\n".join(lines), n
