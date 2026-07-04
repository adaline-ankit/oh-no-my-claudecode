"""Logseq markdown export for onmc memory.

Produces a deterministic Logseq-compatible knowledge graph from stored
memories and memory-edge relationships.  Each memory becomes one page in
Logseq's ``pages/`` directory, formatted with:

- Page properties in Logseq's ``key:: value`` syntax (type, created).
- Logseq block/bullet formatting (``-`` bullets with indented sub-bullets).
- ``[[wikilinks]]`` for memory edges (supersedes / contradicts / relates /
  duplicate_of), using the page title directly.

No dependency beyond the Python standard library — Logseq markdown is plain
UTF-8 text with a small set of conventions.

Design choices
--------------
- **One page per memory** in ``pages/<slug>.md``.  Logseq reads all files in
  the ``pages/`` directory; the flat structure is canonical.
- **Page names** are derived deterministically from the memory title (slug) and
  a short id digest, so they survive renames without broken links.
- **Page properties** use Logseq's ``key:: value`` notation at the top of the
  file (before any blocks).  ``type::`` and ``created::`` are always present.
- **Wikilinks** inside the body use ``[[page-title]]`` format; Logseq resolves
  these to the page whose *filename without extension* matches (case-sensitive
  on most OS, case-insensitive on macOS).  We use the same slug we write as the
  filename so links always resolve.
- **Determinism** is ensured by sorting all collections (memories by title
  then id, edges by type then from-id) and never reading the wall clock.
  Caller supplies timestamps for any fields that must be stable across runs.
- **Empty store** returns a minimal ``contents.md`` index page so Logseq opens
  cleanly even with no memories.
"""

from __future__ import annotations

import re
from collections import defaultdict
from hashlib import sha256
from typing import Protocol

from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind
from oh_no_my_claudecode.models.memory_edge import EdgeType, MemoryEdge

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EDGE_LABELS: dict[EdgeType, str] = {
    EdgeType.SUPERSEDES: "supersedes",
    EdgeType.CONTRADICTS: "contradicts",
    EdgeType.RELATES: "relates to",
    EdgeType.DUPLICATE_OF: "duplicate of",
}

_KIND_LABELS: dict[MemoryKind, str] = {
    MemoryKind.DECISION: "Decision",
    MemoryKind.INVARIANT: "Invariant",
    MemoryKind.HOTSPOT: "Hotspot",
    MemoryKind.GIT_PATTERN: "Git Pattern",
    MemoryKind.VALIDATION_RULE: "Validation Rule",
    MemoryKind.FAILED_APPROACH: "Failed Approach",
    MemoryKind.DESIGN_CONFLICT: "Design Conflict",
    MemoryKind.GOTCHA: "Gotcha",
    MemoryKind.DOC_FACT: "Doc Fact",
}

# ---------------------------------------------------------------------------
# Storage protocol (structural typing to avoid coupling to SQLiteStorage)
# ---------------------------------------------------------------------------


class _MemoryStore(Protocol):
    """Minimal read surface :func:`build_logseq_vault` needs from storage."""

    def list_memories(self) -> list[MemoryEntry]: ...

    def list_memory_edges(self) -> list[MemoryEdge]: ...


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _page_slug(memory: MemoryEntry) -> str:
    """Return the deterministic Logseq page slug for *memory*.

    The slug is used both as the filename (``pages/<slug>.md``) and in
    ``[[wikilinks]]`` so both always resolve to the same page.

    Format: ``<title-slug>-<id-digest-8>``

    The title slug is lowercased, non-alphanumeric runs replaced by hyphens,
    leading/trailing hyphens stripped, capped at 72 chars before the digest
    suffix. The id digest provides uniqueness when titles collide after
    slugification.
    """
    raw = re.sub(r"[^a-z0-9]+", "-", memory.title.casefold()).strip("-")
    title_part = (raw or "memory")[:72].rstrip("-")
    digest = sha256(memory.id.encode()).hexdigest()[:8]
    return f"{title_part}-{digest}"


def _escape_page_prop_value(value: str) -> str:
    """Escape a value for use in a Logseq page property line.

    Logseq page properties live on lines like ``key:: value``.  Newlines
    inside a value would break the property block, so we collapse them.
    Double-colons are the delimiter and must not appear in the value.
    """
    return value.replace("\n", " ").replace("::", "—")


def _wikilink(slug: str, display: str) -> str:
    """Return a Logseq ``[[slug|display]]`` wikilink.

    Logseq supports the ``[[page|alias]]`` form; we use it so the rendered
    text shows the human-readable title while the link target is the slug.
    """
    escaped_display = display.replace("|", "｜")  # full-width | avoids breaking the link
    return f"[[{slug}|{escaped_display}]]"


def _build_relationships(
    edges: list[MemoryEdge],
) -> dict[str, list[tuple[str, str, str, float]]]:
    """Build a per-memory-id lookup of outgoing and incoming edges.

    Returns a dict where each value is a list of
    ``(direction_label, edge_label, other_memory_id, confidence)`` tuples
    sorted for determinism.
    """
    related: dict[str, list[tuple[str, str, str, float]]] = defaultdict(list)
    for edge in sorted(edges, key=lambda e: (e.edge_type.value, e.from_memory_id)):
        label = _EDGE_LABELS[edge.edge_type]
        related[edge.from_memory_id].append(("outgoing", label, edge.to_memory_id, edge.confidence))
        related[edge.to_memory_id].append(
            ("incoming", f"{label} (incoming)", edge.from_memory_id, edge.confidence)
        )
    return dict(related)


def _build_memory_page(
    memory: MemoryEntry,
    slug: str,
    relationships: list[tuple[str, str, str, float]],
    memories_by_id: dict[str, MemoryEntry],
    slug_by_id: dict[str, str],
) -> str:
    """Render one Logseq page for *memory*.

    Page structure
    --------------
    1. Page properties block (``key:: value`` lines).
    2. Summary as the first top-level block.
    3. Provenance sub-bullets under the summary.
    4. Details block (if different from summary).
    5. Relationships block (wikilinks for each edge).
    6. Tags block.
    """
    lines: list[str] = []

    # 1. Page properties — Logseq reads these from the top of the file.
    kind_label = _KIND_LABELS.get(memory.kind, memory.kind.value)
    created_iso = memory.created_at.strftime("%Y-%m-%d")
    updated_iso = memory.updated_at.strftime("%Y-%m-%d")

    lines.append(f"type:: {_escape_page_prop_value(kind_label)}")
    lines.append(f"kind:: {_escape_page_prop_value(memory.kind.value)}")
    lines.append(f"created:: {created_iso}")
    lines.append(f"updated:: {updated_iso}")
    lines.append(f"source-type:: {_escape_page_prop_value(memory.source_type.value)}")
    if memory.source_ref.strip():
        lines.append(f"source-ref:: {_escape_page_prop_value(memory.source_ref.strip())}")
    lines.append(f"confidence:: {memory.confidence:.0%}")
    lines.append("")

    # 2. Summary block.
    summary_clean = memory.summary.strip().replace("\n", " ")
    lines.append(f"- {summary_clean}")

    # 3. Provenance sub-bullets.
    lines.append(f"\t- **Kind**: {kind_label}")
    lines.append(f"\t- **Source**: `{memory.source_ref.strip() or memory.source_type.value}`")
    lines.append(f"\t- **Confidence**: {memory.confidence:.0%}")

    # 4. Details block (only when it adds information beyond the summary).
    details_clean = memory.details.strip()
    if details_clean and details_clean != summary_clean:
        lines.append("- **Details**")
        for detail_line in details_clean.splitlines():
            lines.append(f"\t- {detail_line.strip()}" if detail_line.strip() else "\t-")

    # 5. Relationships block with wikilinks.
    if relationships:
        lines.append("- **Relationships**")
        for _direction, edge_label, other_id, confidence in sorted(
            relationships, key=lambda t: (t[1], t[2])
        ):
            other = memories_by_id.get(other_id)
            other_slug = slug_by_id.get(other_id)
            if other is None or other_slug is None:
                continue
            link = _wikilink(other_slug, other.title)
            conf_str = f" (confidence {confidence:.0%})" if confidence < 1.0 else ""
            lines.append(f"\t- {edge_label} {link}{conf_str}")

    # 6. Tags block.
    if memory.tags:
        tag_str = " ".join(f"#{t}" for t in sorted(memory.tags))
        lines.append(f"- {tag_str}")

    return "\n".join(lines) + "\n"


def _build_contents_page(
    memories: list[MemoryEntry],
    slug_by_id: dict[str, str],
) -> str:
    """Render ``pages/contents.md`` — the Logseq graph index page.

    Groups memories by kind so the index is navigable.
    """
    lines: list[str] = [
        "type:: onmc-index",
        "",
    ]

    if not memories:
        lines.append("- *No memories stored yet. Run `onmc ingest` to populate.*")
        return "\n".join(lines) + "\n"

    lines.append(f"- **{len(memories)} memories** in this knowledge graph")
    lines.append("")

    # Group by kind, sorted deterministically.
    by_kind: dict[MemoryKind, list[MemoryEntry]] = defaultdict(list)
    for mem in memories:
        by_kind[mem.kind].append(mem)

    for kind in sorted(by_kind, key=lambda k: k.value):
        kind_label = _KIND_LABELS.get(kind, kind.value)
        lines.append(f"- **{kind_label}** ({len(by_kind[kind])})")
        for mem in sorted(by_kind[kind], key=lambda m: (m.title.casefold(), m.id)):
            slug = slug_by_id[mem.id]
            link = _wikilink(slug, mem.title)
            lines.append(f"\t- {link}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_logseq_vault(store: _MemoryStore) -> dict[str, str]:
    """Generate a Logseq-compatible knowledge graph as a mapping of path → content.

    Parameters
    ----------
    store:
        Any object exposing ``list_memories()`` and ``list_memory_edges()``
        (the onmc :class:`~oh_no_my_claudecode.storage.SQLiteStorage` satisfies
        this via structural typing).

    Returns
    -------
    dict[str, str]
        Keys are relative paths like ``"pages/my-decision-a1b2c3d4.md"`` and
        ``"pages/contents.md"``.  Values are the rendered Logseq markdown.

        The output is always non-empty: ``"pages/contents.md"`` is always
        present even when the store is empty.

        Ordering within the dict is deterministic (sorted by path).

    Notes
    -----
    - All file writes are the caller's responsibility.  This function is pure
      string generation with zero side-effects.
    - Timestamps come from the memory entries themselves — the wall clock is
      never read, so output is reproducible for the same store state.
    """
    memories = sorted(store.list_memories(), key=lambda m: (m.title.casefold(), m.id))
    edges = store.list_memory_edges()

    slug_by_id: dict[str, str] = {m.id: _page_slug(m) for m in memories}
    memories_by_id: dict[str, MemoryEntry] = {m.id: m for m in memories}
    relationships = _build_relationships(edges)

    pages: dict[str, str] = {}

    # One page per memory.
    for memory in memories:
        slug = slug_by_id[memory.id]
        page_path = f"pages/{slug}.md"
        pages[page_path] = _build_memory_page(
            memory=memory,
            slug=slug,
            relationships=relationships.get(memory.id, []),
            memories_by_id=memories_by_id,
            slug_by_id=slug_by_id,
        )

    # Index / contents page.
    pages["pages/contents.md"] = _build_contents_page(memories, slug_by_id)

    return dict(sorted(pages.items()))
