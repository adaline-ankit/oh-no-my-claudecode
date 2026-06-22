"""Compile a knowledge changelog for memories learned since a git ref.

Two data-source strategy (preferred first):
1. **Committed-export diff** — if ``.agent-memory/memories/`` is present in the
   git tree at *since_ref*, diff it against the current HEAD snapshot via
   :func:`oh_no_my_claudecode.timetravel.memory_diff.diff_memory_at_commits`.
   ``added`` entries are "learned since"; ``changed`` entries are "updated since".
   This is the most accurate source because it reflects exactly what was
   committed at each point in time.

2. **created_at fallback** — when ``.agent-memory/`` is not committed at
   *since_ref*, resolve the ref's commit timestamp via ``git log -1 --format=%cI``
   and return all live-storage memories whose ``created_at`` is after that
   timestamp, grouped by kind.  Less precise (does not capture changed entries)
   but always works.

All subprocess calls use argument-list form (no ``shell=True``).
The ref is never interpolated into a shell string.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from oh_no_my_claudecode.models import MemoryKind
from oh_no_my_claudecode.storage.sqlite import SQLiteStorage
from oh_no_my_claudecode.timetravel.memory_diff import (
    _ls_tree_paths,
    _resolve_commit,
    diff_memory_at_commits,
)

if TYPE_CHECKING:
    from oh_no_my_claudecode.timetravel.memory_diff import MemoryEntry as DiffMemoryEntry

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

# Human-readable section headers ordered for a digest report.
_KIND_LABELS: dict[MemoryKind, str] = {
    MemoryKind.DECISION: "Decisions",
    MemoryKind.INVARIANT: "Invariants",
    MemoryKind.GOTCHA: "Gotchas",
    MemoryKind.FAILED_APPROACH: "Failed Approaches",
    MemoryKind.VALIDATION_RULE: "Validation Rules",
    MemoryKind.DESIGN_CONFLICT: "Design Conflicts",
    MemoryKind.HOTSPOT: "Hotspots",
    MemoryKind.GIT_PATTERN: "Git Patterns",
    MemoryKind.DOC_FACT: "Doc Facts",
}

_SECTION_ORDER: list[MemoryKind] = [
    MemoryKind.DECISION,
    MemoryKind.INVARIANT,
    MemoryKind.GOTCHA,
    MemoryKind.FAILED_APPROACH,
    MemoryKind.VALIDATION_RULE,
    MemoryKind.DESIGN_CONFLICT,
    MemoryKind.HOTSPOT,
    MemoryKind.GIT_PATTERN,
    MemoryKind.DOC_FACT,
]


@dataclass
class DigestEntry:
    """A single memory entry included in the digest."""

    id: str
    kind: MemoryKind
    title: str
    summary: str
    # "added" = new since ref; "changed" = existed but content changed.
    change_type: str  # "added" | "changed"


@dataclass
class DigestResult:
    """Structured result of ``onmc digest --since <ref>``."""

    since_ref: str
    since_short: str  # short hash of the resolved ref
    since_date: str  # ISO date of the ref's commit
    head_short: str  # short hash of current HEAD
    head_date: str  # ISO date of HEAD

    # Entries grouped by kind (same ordering as _SECTION_ORDER).
    by_kind: dict[MemoryKind, list[DigestEntry]] = field(default_factory=dict)

    # Which data source was used.
    source: str = "committed_export"  # "committed_export" | "created_at_fallback"
    # Set when committed export is absent at since_ref.
    fallback_reason: str = ""

    @property
    def total(self) -> int:
        return sum(len(entries) for entries in self.by_kind.values())


# ---------------------------------------------------------------------------
# Internal git helpers
# ---------------------------------------------------------------------------


def _resolve_ref_timestamp(repo_root: Path, ref: str) -> datetime | None:
    """Return the commit timestamp for *ref* as an aware UTC datetime, or None."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cI", ref],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        raw = result.stdout.strip()
        if not raw:
            return None
        # %cI gives ISO 8601 with offset (e.g. 2026-01-15T10:00:00+00:00)
        dt = datetime.fromisoformat(raw)
        return dt.astimezone(UTC)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return None


def _has_committed_export_at(repo_root: Path, ref: str) -> bool:
    """Return True if ``.agent-memory/memories/`` exists in the tree at *ref*."""
    paths = _ls_tree_paths(repo_root, ref, ".agent-memory/memories")
    return bool(paths)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_digest(
    repo_root: Path,
    storage: SQLiteStorage,
    since_ref: str,
) -> DigestResult:
    """Build a knowledge changelog for everything learned since *since_ref*.

    Prefers the committed-export diff path; falls back to ``created_at`` when
    ``.agent-memory/`` is not committed at *since_ref*.

    Args:
        repo_root: Absolute path to the git repository root.
        storage: Live SQLite storage (used for the created_at fallback path only).
        since_ref: A git ref (tag, branch, commit hash) marking the starting point.

    Returns:
        A :class:`DigestResult` grouped by :class:`MemoryKind`.

    Raises:
        ValueError: When *since_ref* cannot be resolved to a commit.
    """
    since_short, since_date = _resolve_commit(repo_root, since_ref)
    if not since_short:
        msg = f"Cannot resolve git ref: {since_ref!r}"
        raise ValueError(msg)

    head_short, head_date = _resolve_commit(repo_root, "HEAD")

    result = DigestResult(
        since_ref=since_ref,
        since_short=since_short,
        since_date=since_date,
        head_short=head_short,
        head_date=head_date,
    )

    # --- Preferred path: committed .agent-memory/ diff ---
    if _has_committed_export_at(repo_root, since_ref):
        result.source = "committed_export"
        diff = diff_memory_at_commits(repo_root, since_ref, "HEAD")
        entries: list[DigestEntry] = []
        for mem in diff.added:
            entries.append(_from_diff_entry(mem, "added"))
        for change in diff.changed:
            # Represent a changed memory as a DigestEntry with the new content.
            kind = _parse_kind(change.kind)
            if kind is not None:
                entries.append(
                    DigestEntry(
                        id=change.memory_id,
                        kind=kind,
                        title=change.new_title,
                        summary=change.new_summary,
                        change_type="changed",
                    )
                )
        result.by_kind = _group_by_kind(entries)
        return result

    # --- Fallback path: filter by created_at > ref commit timestamp ---
    ref_ts = _resolve_ref_timestamp(repo_root, since_ref)
    if ref_ts is None:
        # Should not happen — we already resolved the short hash above.
        result.source = "created_at_fallback"
        result.fallback_reason = (
            f".agent-memory/ is not committed at {since_short}. "
            "Could not read ref timestamp — returning empty digest."
        )
        return result

    result.source = "created_at_fallback"
    result.fallback_reason = (
        f".agent-memory/ is not committed at {since_short} ({since_date}). "
        "Showing memories whose created_at is after that commit timestamp. "
        "Run `onmc sync --commit` and commit .agent-memory/ for precise diffs."
    )

    new_entries: list[DigestEntry] = []
    for live_mem in storage.list_memories():
        mem_ts: datetime = live_mem.created_at
        if mem_ts.tzinfo is None:
            mem_ts = mem_ts.replace(tzinfo=UTC)
        if mem_ts > ref_ts:
            new_entries.append(
                DigestEntry(
                    id=live_mem.id,
                    kind=live_mem.kind,
                    title=live_mem.title,
                    summary=live_mem.summary,
                    change_type="added",
                )
            )

    result.by_kind = _group_by_kind(new_entries)
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_kind(kind_str: str) -> MemoryKind | None:
    try:
        return MemoryKind(kind_str)
    except ValueError:
        return None


def _from_diff_entry(entry: DiffMemoryEntry, change_type: str) -> DigestEntry:
    kind = _parse_kind(entry.kind)
    return DigestEntry(
        id=entry.id,
        kind=kind if kind is not None else MemoryKind.DOC_FACT,
        title=entry.title,
        summary=entry.summary,
        change_type=change_type,
    )


def _group_by_kind(entries: list[DigestEntry]) -> dict[MemoryKind, list[DigestEntry]]:
    """Return entries grouped by kind, in _SECTION_ORDER, newest-change-type first."""
    grouped: dict[MemoryKind, list[DigestEntry]] = {}
    for kind in _SECTION_ORDER:
        bucket = [e for e in entries if e.kind == kind]
        if bucket:
            # added entries first, then changed; within each group preserve order
            added = [e for e in bucket if e.change_type == "added"]
            changed = [e for e in bucket if e.change_type == "changed"]
            grouped[kind] = [*added, *changed]
    return grouped


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def digest_to_markdown(result: DigestResult) -> str:
    """Render *result* as a markdown knowledge-changelog artifact."""
    since_label = (
        f"`{result.since_ref}` ({result.since_short}, {result.since_date})"
        if result.since_short != result.since_ref
        else f"`{result.since_ref}`"
    )

    lines: list[str] = [
        f"# Knowledge changelog since {since_label}",
        "",
        f"- **Since:** {result.since_short} — {result.since_date}",
        f"- **As of:** {result.head_short} — {result.head_date}",
        f"- **Source:** {result.source}",
        "",
    ]

    if result.fallback_reason:
        lines += [
            "> **Note (fallback mode):** " + result.fallback_reason,
            "",
        ]

    if result.total == 0:
        lines += ["_Nothing new learned since this ref._", ""]
        return "\n".join(lines)

    lines += [f"**{result.total} entr{'y' if result.total == 1 else 'ies'} learned.**", ""]

    for kind in _SECTION_ORDER:
        bucket = result.by_kind.get(kind)
        if not bucket:
            continue
        section_label = _KIND_LABELS.get(kind, kind.value.replace("_", " ").title())
        lines += [f"## {section_label}", ""]
        for entry in bucket:
            badge = "+" if entry.change_type == "added" else "~"
            lines.append(f"### {badge} {entry.title}")
            if entry.change_type == "changed":
                lines.append("_(updated since ref)_")
            lines.append("")
            lines.append(entry.summary)
            lines.append("")

    return "\n".join(lines)
