"""Wiki generator for onmc.

Produces a multi-page markdown knowledge base from stored memories and the
memory-edge relationship graph.  All output is deterministic — same inputs
produce byte-identical pages — so the wiki can safely be committed to a repo
or regenerated on demand.

Page layout
-----------
index.md          — overview, counts by kind, danger zone, active tasks,
                    links to all sub-pages
subsystems/<area>.md — per-top-level-dir grouping of decisions, invariants,
                    hotspots, gotchas, validation rules, failed approaches
graph.md          — readable edge list (supersedes / contradicts / relates /
                    duplicate_of) so contradictions are visible at a glance

All prose is cleaned via :func:`strip_markdown_noise` and
:func:`shorten_to_sentence` before inclusion so no stray fences or mid-word
truncation leak into the output.
"""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from pathlib import Path

from oh_no_my_claudecode.models import (
    TERMINAL_TASK_STATUSES,
    FileStat,
    MemoryEntry,
    MemoryKind,
    TaskRecord,
)
from oh_no_my_claudecode.models.memory_edge import EdgeType, MemoryEdge
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import shorten_to_sentence, strip_markdown_noise

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUMMARY_MAX = 200  # characters for one-line bullets in wiki pages
_SUBSYSTEM_LINK_PREFIX = "subsystems/"

# Human-friendly labels for each memory kind
_KIND_LABELS: dict[MemoryKind, str] = {
    MemoryKind.DECISION: "Decisions",
    MemoryKind.INVARIANT: "Invariants",
    MemoryKind.HOTSPOT: "Hotspots",
    MemoryKind.GIT_PATTERN: "Git Patterns",
    MemoryKind.VALIDATION_RULE: "Validation Rules",
    MemoryKind.FAILED_APPROACH: "Failed Approaches",
    MemoryKind.DESIGN_CONFLICT: "Design Conflicts",
    MemoryKind.GOTCHA: "Gotchas",
    MemoryKind.DOC_FACT: "Doc Facts",
}

# Ordered section groups for subsystem pages
_SECTION_ORDER: list[MemoryKind] = [
    MemoryKind.DECISION,
    MemoryKind.INVARIANT,
    MemoryKind.HOTSPOT,
    MemoryKind.GIT_PATTERN,
    MemoryKind.VALIDATION_RULE,
    MemoryKind.FAILED_APPROACH,
    MemoryKind.DESIGN_CONFLICT,
    MemoryKind.GOTCHA,
    MemoryKind.DOC_FACT,
]

# Edge type verbs for graph page
_EDGE_VERBS: dict[EdgeType, str] = {
    EdgeType.SUPERSEDES: "supersedes",
    EdgeType.CONTRADICTS: "contradicts",
    EdgeType.RELATES: "relates to",
    EdgeType.DUPLICATE_OF: "is a duplicate of",
}


class WikiFormat(StrEnum):
    MARKDOWN = "markdown"
    OBSIDIAN = "obsidian"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clean(text: str, max_chars: int = _SUMMARY_MAX) -> str:
    """Strip markdown noise then truncate cleanly at sentence/word boundary."""
    return shorten_to_sentence(strip_markdown_noise(text), max_chars)


def _area_from_memory(memory: MemoryEntry) -> str:
    """Derive a subsystem area slug from the memory's source_ref.

    Uses the top-level directory component of the source_ref path.  Falls back
    to the ``source_type`` when the ref has no directory structure.
    """
    ref = memory.source_ref.strip()
    if not ref:
        return memory.source_type.value
    parts = Path(ref.lstrip("/")).parts
    if len(parts) >= 2:  # noqa: PLR2004
        return parts[0]
    # Single-component path — use source_type as the area
    return memory.source_type.value


def _slugify_area(area: str) -> str:
    """Convert an area name to a safe filename slug."""
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", area.lower()).strip("-")
    return slug or "misc"


def _memory_bullet(memory: MemoryEntry) -> str:
    """Format a memory entry as a clean one-line bullet with provenance."""
    cleaned_summary = _clean(memory.summary)
    ref = memory.source_ref.strip()
    prov = f" `{ref}`" if ref else ""
    return f"- **{memory.title}**: {cleaned_summary}{prov}"


def _group_by_area(memories: list[MemoryEntry]) -> dict[str, list[MemoryEntry]]:
    """Group memories by their derived subsystem area."""
    grouped: dict[str, list[MemoryEntry]] = defaultdict(list)
    for mem in memories:
        grouped[_area_from_memory(mem)].append(mem)
    return dict(grouped)


def _group_by_kind(memories: list[MemoryEntry]) -> dict[MemoryKind, list[MemoryEntry]]:
    """Group memories by kind."""
    grouped: dict[MemoryKind, list[MemoryEntry]] = defaultdict(list)
    for mem in memories:
        grouped[mem.kind].append(mem)
    return dict(grouped)


def _hotspot_area_ranking(file_stats: list[FileStat], top_n: int = 10) -> list[FileStat]:
    """Return the top-N most-changed files as hotspot candidates."""
    return sorted(file_stats, key=lambda s: (s.change_count, s.recent_change_count), reverse=True)[
        :top_n
    ]


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------


def _build_index(
    *,
    repo_root: Path,
    memories: list[MemoryEntry],
    file_stats: list[FileStat],
    active_tasks: list[TaskRecord],
    area_slugs: list[tuple[str, str]],
) -> str:
    """Build ``index.md`` — the wiki landing page."""
    lines: list[str] = []
    repo_name = repo_root.name

    lines.append(f"# {repo_name} — Knowledge Wiki")
    lines.append("")
    lines.append(
        "Auto-generated from [onmc](https://github.com/oh-no-my-claudecode) provenance-tracked"
        " memory.  Do not edit by hand — run `onmc wiki` to regenerate."
    )
    lines.append("")

    # ----- Summary counts -----
    lines.append("## Memory Summary")
    lines.append("")
    if not memories:
        lines.append("_No memories stored yet. Run `onmc ingest` to populate._")
    else:
        kind_counts = _group_by_kind(memories)
        lines.append(f"Total memories: **{len(memories)}**")
        lines.append("")
        lines.append("| Kind | Count |")
        lines.append("| ---- | ----- |")
        for kind in _SECTION_ORDER:
            count = len(kind_counts.get(kind, []))
            if count:
                lines.append(f"| {_KIND_LABELS[kind]} | {count} |")
    lines.append("")

    # ----- Sub-pages -----
    lines.append("## Pages")
    lines.append("")
    lines.append("- [graph.md](graph.md) — memory relationship graph")
    for area, slug in sorted(area_slugs):
        lines.append(f"- [{area}]({_SUBSYSTEM_LINK_PREFIX}{slug}.md)")
    lines.append("")

    # ----- Danger zone: top hotspots -----
    hotspots = _hotspot_area_ranking(file_stats)
    if hotspots:
        lines.append("## Danger Zone (top hotspots by churn)")
        lines.append("")
        for stat in hotspots:
            recent = f", {stat.recent_change_count} recent" if stat.recent_change_count else ""
            lines.append(f"- `{stat.path}` — {stat.change_count} changes{recent}")
        lines.append("")

    # ----- Active tasks -----
    if active_tasks:
        lines.append("## Active Tasks")
        lines.append("")
        for task in active_tasks:
            desc_clean = _clean(task.description, 120)
            lines.append(f"- **{task.title}** ({task.status.value}): {desc_clean}")
        lines.append("")

    return "\n".join(lines)


def _build_subsystem_page(
    *,
    area: str,
    memories: list[MemoryEntry],
) -> str:
    """Build a subsystem page for one top-level area."""
    lines: list[str] = []

    lines.append(f"# {area}")
    lines.append("")
    lines.append(
        f"Memories sourced from the `{area}` subsystem."
        " Generated by `onmc wiki` — do not edit by hand."
    )
    lines.append("")
    lines.append("[← Back to index](../index.md)")
    lines.append("")

    by_kind = _group_by_kind(memories)

    any_section = False
    for kind in _SECTION_ORDER:
        kind_memories = by_kind.get(kind, [])
        if not kind_memories:
            continue
        any_section = True
        lines.append(f"## {_KIND_LABELS[kind]}")
        lines.append("")
        for mem in sorted(kind_memories, key=lambda m: m.title):
            lines.append(_memory_bullet(mem))
        lines.append("")

    if not any_section:
        lines.append("_No memories in this subsystem._")
        lines.append("")

    return "\n".join(lines)


def _build_graph_page(
    *,
    memories: list[MemoryEntry],
    edges: list[MemoryEdge],
) -> str:
    """Build ``graph.md`` — the memory-edge relationship page."""
    lines: list[str] = []

    lines.append("# Memory Relationship Graph")
    lines.append("")
    lines.append(
        "Directed edges between memories extracted during consolidation."
        " `contradicts` edges highlight conflicting knowledge."
    )
    lines.append("")
    lines.append("[← Back to index](index.md)")
    lines.append("")

    if not edges:
        lines.append("_No memory edges recorded yet._")
        lines.append("")
        return "\n".join(lines)

    # Build lookup: id → title
    id_to_title: dict[str, str] = {m.id: m.title for m in memories}

    def _mem_ref(mem_id: str) -> str:
        title = id_to_title.get(mem_id, mem_id)
        return f"**{title}**"

    # Group edges by type so contradictions are visually prominent
    by_type: dict[EdgeType, list[MemoryEdge]] = defaultdict(list)
    for edge in edges:
        by_type[edge.edge_type].append(edge)

    # Show contradicts first (most operationally important)
    type_order = [
        EdgeType.CONTRADICTS,
        EdgeType.SUPERSEDES,
        EdgeType.DUPLICATE_OF,
        EdgeType.RELATES,
    ]

    for edge_type in type_order:
        type_edges = by_type.get(edge_type, [])
        if not type_edges:
            continue
        verb = _EDGE_VERBS[edge_type]
        lines.append(f"## {verb.capitalize()}")
        lines.append("")
        for edge in sorted(type_edges, key=lambda e: e.from_memory_id):
            from_ref = _mem_ref(edge.from_memory_id)
            to_ref = _mem_ref(edge.to_memory_id)
            conf = f" (confidence: {edge.confidence:.2f})" if edge.confidence < 1.0 else ""  # noqa: PLR2004
            lines.append(f"- {from_ref} {verb} {to_ref}{conf}")
        lines.append("")

    lines.append(f"Total edges: {len(edges)}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_wiki(storage: SQLiteStorage, repo_root: Path) -> dict[str, str]:
    """Generate the full wiki as a mapping of relative page path → markdown content.

    Parameters
    ----------
    storage:
        An initialised :class:`SQLiteStorage` instance for the repo.
    repo_root:
        Absolute path to the repository root — used for the repo name and to
        resolve file-stat top-level directories.

    Returns
    -------
    dict[str, str]
        Keys are relative paths like ``"index.md"`` or
        ``"subsystems/src.md"``; values are the rendered markdown.
        The dict is always non-empty: ``"index.md"`` and ``"graph.md"`` are
        always present even when the store is empty.
    """
    memories = storage.list_memories()
    edges = storage.list_memory_edges()
    file_stats = storage.list_file_stats()
    tasks = storage.list_tasks()
    active_tasks = [t for t in tasks if t.status not in TERMINAL_TASK_STATUSES]

    pages: dict[str, str] = {}

    # ----- Subsystem pages -----
    area_slugs: list[tuple[str, str]] = []
    area_groups = _group_by_area(memories)
    for area, area_memories in sorted(area_groups.items()):
        slug = _slugify_area(area)
        page_path = f"{_SUBSYSTEM_LINK_PREFIX}{slug}.md"
        pages[page_path] = _build_subsystem_page(area=area, memories=area_memories)
        area_slugs.append((area, slug))

    # ----- Graph page -----
    pages["graph.md"] = _build_graph_page(memories=memories, edges=edges)

    # ----- Index page (built last so it can list all subsystem pages) -----
    pages["index.md"] = _build_index(
        repo_root=repo_root,
        memories=memories,
        file_stats=file_stats,
        active_tasks=active_tasks,
        area_slugs=area_slugs,
    )

    return pages
