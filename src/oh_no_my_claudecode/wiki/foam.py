"""Foam markdown export for onmc memory.

Produces a deterministic Foam-compatible knowledge graph from stored memories
and memory-edge relationships.  Foam is a VS Code-based markdown knowledge
graph that reads a flat directory of markdown notes connected by ``[[wikilinks]]``.

Each memory becomes one note in the ``notes/`` directory, formatted with:

- YAML frontmatter (``---`` fenced, standard ``key: value`` syntax) containing
  ``type``, ``kind``, ``created``, ``updated``, ``source_type``, ``source_ref``,
  ``confidence``, and ``tags``.
- A ``# Title`` heading.
- A prose body with summary and provenance section.
- ``[[wikilinks]]`` for memory edges (supersedes / contradicts / relates /
  duplicate_of).  Foam resolves wikilinks by matching the bare filename stem,
  so we use the note slug (no extension) as the link target.
- An optional evidence section when details differ from summary.

Key differences from the sibling Logseq exporter
-------------------------------------------------
- **YAML frontmatter** (``---`` / ``key: value``) instead of Logseq's
  ``key:: value`` property block.
- **Standard ``[[wikilinks]]``** — Foam links use ``[[slug]]`` or
  ``[[slug|display text]]``; there is no block/bullet indentation requirement.
- **Flat ``notes/`` directory** — Foam reads all ``.md`` files recursively;
  we use a single flat layer to keep links simple.
- **``index.md``** at the root (not ``pages/contents.md``) serves as the
  graph entry point that Foam opens by default.

No dependency beyond the Python standard library — Foam markdown is plain
UTF-8 text with a small set of conventions.

Design choices
--------------
- **One note per memory** in ``notes/<slug>.md``.  The flat layout is canonical
  for Foam workspaces.
- **Note slugs** are derived deterministically from the memory title and a short
  SHA-256 digest of the id, so they survive renames without broken links.
- **YAML frontmatter** always starts the file.  The ``tags`` list always
  contains at least ``onmc-memory`` and ``onmc/<kind>``.
- **Wikilinks** use ``[[slug|display text]]`` so the rendered text is
  human-readable while the link target is the slug.
- **Determinism** is ensured by sorting all collections and never reading the
  wall clock.  Timestamps come from the memory entries themselves.
- **Empty store** returns a minimal ``index.md`` so the workspace opens cleanly.
"""

from __future__ import annotations

import json
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
# Storage protocol (structural typing — same surface as logseq.py)
# ---------------------------------------------------------------------------


class _MemoryStore(Protocol):
    """Minimal read surface :func:`build_foam_vault` needs from storage."""

    def list_memories(self) -> list[MemoryEntry]: ...

    def list_memory_edges(self) -> list[MemoryEdge]: ...


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _note_slug(memory: MemoryEntry) -> str:
    """Return the deterministic Foam note slug for *memory*.

    The slug is used both as the filename stem (``notes/<slug>.md``) and in
    ``[[wikilinks]]`` so both always resolve to the same note.

    Format: ``<title-slug>-<id-digest-8>``

    Lowercased, non-alphanumeric runs replaced by hyphens, leading/trailing
    hyphens stripped, capped at 72 chars before the digest suffix.
    """
    raw = re.sub(r"[^a-z0-9]+", "-", memory.title.casefold()).strip("-")
    title_part = (raw or "memory")[:72].rstrip("-")
    digest = sha256(memory.id.encode()).hexdigest()[:8]
    return f"{title_part}-{digest}"


def _yaml_str(value: str) -> str:
    """Serialise *value* as a YAML scalar safe for a frontmatter ``key: value`` line.

    Uses JSON encoding (double-quoted) to handle special characters, newlines,
    and YAML-reserved tokens without pulling in the ``yaml`` module.
    """
    return json.dumps(value, ensure_ascii=False)


def _wikilink(slug: str, display: str) -> str:
    """Return a Foam ``[[slug|display]]`` wikilink.

    Foam (and Obsidian) support the ``[[page|alias]]`` form so rendered text
    shows the human-readable title while the link target is the slug.
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


def _build_note(
    memory: MemoryEntry,
    slug: str,
    relationships: list[tuple[str, str, str, float]],
    memories_by_id: dict[str, MemoryEntry],
    slug_by_id: dict[str, str],
) -> str:
    """Render one Foam note for *memory*.

    Note structure
    --------------
    1. YAML frontmatter (``---`` fenced).
    2. ``# Title`` heading.
    3. Summary paragraph.
    4. ``## Provenance`` section.
    5. ``## Details`` section (only when details differ from summary).
    6. ``## Relationships`` section with ``[[wikilinks]]`` per edge.
    7. ``## Tags`` section.
    """
    lines: list[str] = []

    kind_label = _KIND_LABELS.get(memory.kind, memory.kind.value)
    created_iso = memory.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    updated_iso = memory.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Compile tags list — always include onmc-memory and onmc/<kind>.
    fm_tags: list[str] = ["onmc-memory", f"onmc/{memory.kind.value}"]
    fm_tags.extend(sorted(memory.tags))

    # 1. YAML frontmatter.
    lines.append("---")
    lines.append(f"id: {_yaml_str(memory.id)}")
    lines.append(f"type: {_yaml_str(kind_label)}")
    lines.append(f"kind: {_yaml_str(memory.kind.value)}")
    lines.append(f"created: {_yaml_str(created_iso)}")
    lines.append(f"updated: {_yaml_str(updated_iso)}")
    lines.append(f"source_type: {_yaml_str(memory.source_type.value)}")
    lines.append(f"source_ref: {_yaml_str(memory.source_ref.strip())}")
    lines.append(f"confidence: {memory.confidence:.2f}")
    lines.append("tags:")
    for tag in fm_tags:
        lines.append(f"  - {_yaml_str(tag)}")
    lines.append("---")
    lines.append("")

    # 2. Title heading.
    lines.append(f"# {memory.title}")
    lines.append("")

    # 3. Summary paragraph.
    summary_clean = memory.summary.strip()
    lines.append(summary_clean)
    lines.append("")

    # 4. Provenance section.
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- **Kind**: {kind_label}")
    lines.append(f"- **Source**: `{memory.source_ref.strip() or memory.source_type.value}`")
    lines.append(f"- **Confidence**: {memory.confidence:.0%}")
    lines.append("")

    # 5. Details section (only when it adds information beyond the summary).
    details_clean = memory.details.strip()
    if details_clean and details_clean != summary_clean:
        lines.append("## Details")
        lines.append("")
        lines.append(details_clean)
        lines.append("")

    # 6. Relationships section with wikilinks.
    if relationships:
        lines.append("## Relationships")
        lines.append("")
        for _direction, edge_label, other_id, confidence in sorted(
            relationships, key=lambda t: (t[1], t[2])
        ):
            other = memories_by_id.get(other_id)
            other_slug = slug_by_id.get(other_id)
            if other is None or other_slug is None:
                continue
            link = _wikilink(other_slug, other.title)
            conf_str = f" (confidence {confidence:.0%})" if confidence < 1.0 else ""
            lines.append(f"- {edge_label} {link}{conf_str}")
        lines.append("")

    # 7. Tags section (inline hashtag style, mirrors Logseq convention).
    if memory.tags:
        tag_str = " ".join(f"#{t}" for t in sorted(memory.tags))
        lines.append(tag_str)
        lines.append("")

    lines.append("---")
    lines.append("*Generated by `onmc wiki foam`.*")
    lines.append("")

    return "\n".join(lines)


def _build_index(
    memories: list[MemoryEntry],
    slug_by_id: dict[str, str],
) -> str:
    """Render ``index.md`` — the Foam workspace entry point.

    Groups memories by kind so the index is navigable.  Empty store produces
    a minimal page with a helpful message.
    """
    lines: list[str] = [
        "---",
        'type: "onmc-index"',
        "tags:",
        '  - "onmc-vault"',
        "---",
        "",
        "# onmc Memory Graph",
        "",
    ]

    if not memories:
        lines.append("*No memories stored yet. Run `onmc ingest` to populate.*")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"**{len(memories)} memories** in this Foam knowledge graph.")
    lines.append("")
    lines.append("Open the Foam Graph View in VS Code to explore links.")
    lines.append("")

    # Group by kind, sorted deterministically.
    by_kind: dict[MemoryKind, list[MemoryEntry]] = defaultdict(list)
    for mem in memories:
        by_kind[mem.kind].append(mem)

    for kind in sorted(by_kind, key=lambda k: k.value):
        kind_label = _KIND_LABELS.get(kind, kind.value)
        lines.append(f"## {kind_label} ({len(by_kind[kind])})")
        lines.append("")
        for mem in sorted(by_kind[kind], key=lambda m: (m.title.casefold(), m.id)):
            slug = slug_by_id[mem.id]
            link = _wikilink(slug, mem.title)
            lines.append(f"- {link}")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by `onmc wiki foam`.*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_foam_vault(store: _MemoryStore) -> dict[str, str]:
    """Generate a Foam-compatible knowledge graph as a mapping of path → content.

    Parameters
    ----------
    store:
        Any object exposing ``list_memories()`` and ``list_memory_edges()``
        (the onmc :class:`~oh_no_my_claudecode.storage.SQLiteStorage` satisfies
        this via structural typing).

    Returns
    -------
    dict[str, str]
        Keys are relative paths like ``"notes/my-decision-a1b2c3d4.md"`` and
        ``"index.md"``.  Values are the rendered Foam markdown.

        The output is always non-empty: ``"index.md"`` is always present even
        when the store is empty.

        Ordering within the dict is deterministic (sorted by path).

    Notes
    -----
    - All file writes are the caller's responsibility.  This function is pure
      string generation with zero side-effects.
    - Timestamps come from the memory entries themselves — the wall clock is
      never read, so output is reproducible for the same store state.
    - Foam wikilinks use the bare filename stem (no extension), so
      ``[[my-decision-a1b2c3d4]]`` resolves to ``notes/my-decision-a1b2c3d4.md``.
    """
    memories = sorted(store.list_memories(), key=lambda m: (m.title.casefold(), m.id))
    edges = store.list_memory_edges()

    slug_by_id: dict[str, str] = {m.id: _note_slug(m) for m in memories}
    memories_by_id: dict[str, MemoryEntry] = {m.id: m for m in memories}
    relationships = _build_relationships(edges)

    pages: dict[str, str] = {}

    # One note per memory.
    for memory in memories:
        slug = slug_by_id[memory.id]
        note_path = f"notes/{slug}.md"
        pages[note_path] = _build_note(
            memory=memory,
            slug=slug,
            relationships=relationships.get(memory.id, []),
            memories_by_id=memories_by_id,
            slug_by_id=slug_by_id,
        )

    # Index page.
    pages["index.md"] = _build_index(memories, slug_by_id)

    return dict(sorted(pages.items()))
