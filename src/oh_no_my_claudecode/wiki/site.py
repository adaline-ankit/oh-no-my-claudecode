"""Static HTML site export for onmc memory.

Produces a self-contained, browsable static HTML site from stored memories and
memory-edge relationships.  Unlike the vault exporters (logseq/foam/obsidian,
which need those apps), this produces a standalone site you can open directly
in any web browser — no external app, no JS framework, no network required.

Output layout
-------------
index.html          — landing page listing all memories grouped by kind, with
                      counts per kind and links to per-memory pages.
<slug>.html         — one detail page per memory with its full body, provenance,
                      and resolved ``<a href>`` links for memory edges.

Design choices
--------------
- **Pure stdlib** — ``html.escape`` for XSS-safe rendering, ``json`` for the
  ``--json`` envelope, ``hashlib.sha256`` for slug derivation.  No dependency
  beyond the Python standard library.
- **Inline CSS** — a single ``<style>`` block in every page; no external
  stylesheets, no CDN, no fonts from the network.  Files open correctly even
  when the directory is moved or the site is opened as a local file.
- **Deterministic** — stable ordering (sorted by title then id), timestamps from
  memory entries only (wall clock never read), so two calls with the same store
  produce byte-identical output.
- **Self-contained ``<a href>`` links** — each edge renders as a real hyperlink
  to the target memory's ``.html`` file, resolved relative to the same directory.
  Links that reference unknown memory ids are silently omitted.
- **HTML-escaped content** — all user-supplied strings (title, summary, tags,
  source_ref) pass through ``html.escape`` before inclusion.
- **Empty store** — ``index.html`` is always generated with a helpful message;
  no per-memory pages are written.

Key differences from vault exporters
-------------------------------------
- **No app dependency** — no VS Code + Foam, no Logseq, no Obsidian needed.
- **``<a href>`` hyperlinks** instead of ``[[wikilinks]]`` — resolves in any
  browser without a plugin.
- **HTML output** — ``.html`` files instead of ``.md`` files.
- **Single flat directory** — all files in the root output dir (no ``notes/``
  subdirectory) so relative links like ``<a href="slug.html">`` always work.
"""

from __future__ import annotations

import html
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

# Inline CSS shared by every page — no external assets, no network.
_CSS = """
    *, *::before, *::after { box-sizing: border-box; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        font-size: 15px; line-height: 1.6;
        max-width: 860px; margin: 0 auto; padding: 2rem 1.5rem;
        background: #fafafa; color: #1a1a1a;
    }
    a { color: #0066cc; text-decoration: none; }
    a:hover { text-decoration: underline; }
    h1 { font-size: 1.7rem; margin: 0 0 1.2rem; }
    h2 { font-size: 1.2rem; margin: 2rem 0 0.5rem;
         border-bottom: 1px solid #ddd; padding-bottom: 0.3rem; }
    h3 { font-size: 1rem; margin: 1.2rem 0 0.3rem; }
    .kind-badge {
        display: inline-block; padding: 0.15rem 0.5rem;
        border-radius: 3px; font-size: 0.75rem; font-weight: 600;
        background: #e8f0fe; color: #1a56db; margin-right: 0.5rem;
    }
    .memory-card {
        border: 1px solid #e0e0e0; border-radius: 6px;
        padding: 0.8rem 1rem; margin: 0.5rem 0;
        background: #fff;
    }
    .memory-card .title { font-weight: 600; }
    .memory-card .summary { color: #444; margin-top: 0.3rem; font-size: 0.9rem; }
    .tag { display: inline-block; background: #f0f0f0; border-radius: 3px;
           padding: 0.1rem 0.4rem; font-size: 0.75rem; margin: 0.1rem; }
    .edge-list { list-style: none; padding: 0; margin: 0.4rem 0; }
    .edge-list li { padding: 0.2rem 0; }
    .edge-label { font-size: 0.8rem; color: #666; margin-right: 0.4rem; }
    .provenance { font-size: 0.85rem; color: #555; margin: 0.5rem 0; }
    code { background: #f4f4f4; border-radius: 3px; padding: 0.1rem 0.3rem; font-size: 0.85rem; }
    .nav { font-size: 0.85rem; margin-bottom: 1.5rem; color: #666; }
    .nav a { color: #0066cc; }
    .empty-notice { color: #888; font-style: italic; }
    .confidence { font-size: 0.8rem; color: #888; margin-left: 0.3rem; }
    footer { margin-top: 3rem; font-size: 0.8rem; color: #aaa;
             border-top: 1px solid #eee; padding-top: 1rem; }
""".strip()


# ---------------------------------------------------------------------------
# Storage protocol (structural typing — same surface as sibling exporters)
# ---------------------------------------------------------------------------


class _MemoryStore(Protocol):
    """Minimal read surface :func:`build_site` needs from storage."""

    def list_memories(self) -> list[MemoryEntry]: ...

    def list_memory_edges(self) -> list[MemoryEdge]: ...


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _page_slug(memory: MemoryEntry) -> str:
    """Return the deterministic HTML page slug for *memory*.

    Format: ``<title-slug>-<id-digest-8>``

    The slug is used as both the ``.html`` filename and in ``<a href>`` links,
    so links always resolve.  Lowercased, non-alphanumeric runs become hyphens,
    capped at 72 chars before the digest suffix.
    """
    raw = re.sub(r"[^a-z0-9]+", "-", memory.title.casefold()).strip("-")
    title_part = (raw or "memory")[:72].rstrip("-")
    digest = sha256(memory.id.encode()).hexdigest()[:8]
    return f"{title_part}-{digest}"


def _h(text: str) -> str:
    """HTML-escape *text* for safe insertion into HTML attributes or body."""
    return html.escape(text, quote=True)


def _page_template(*, title: str, body: str) -> str:
    """Wrap *body* in a minimal HTML5 document with inline CSS."""
    escaped_title = _h(title)
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        f"  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"  <title>{escaped_title}</title>\n"
        f"  <style>\n{_CSS}\n  </style>\n"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "<footer>Generated by <code>onmc wiki site</code>.</footer>\n"
        "</body>\n"
        "</html>\n"
    )


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
    """Render one HTML detail page for *memory*.

    Page structure
    --------------
    1. Navigation breadcrumb (← index).
    2. Kind badge + title heading.
    3. Summary paragraph.
    4. Provenance metadata row.
    5. Details section (when different from summary).
    6. Relationships section with ``<a href>`` hyperlinks per edge.
    7. Tags section.
    """
    kind_label = _KIND_LABELS.get(memory.kind, memory.kind.value)
    created_iso = memory.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    updated_iso = memory.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = []

    # 1. Navigation.
    lines.append('<div class="nav"><a href="index.html">← Memory Index</a></div>')

    # 2. Kind badge + title.
    lines.append(f'<span class="kind-badge">{_h(kind_label)}</span>')
    lines.append(f"<h1>{_h(memory.title)}</h1>")

    # 3. Summary.
    summary_clean = memory.summary.strip()
    lines.append(f"<p>{_h(summary_clean)}</p>")

    # 4. Provenance.
    source_display = memory.source_ref.strip() or memory.source_type.value
    lines.append('<div class="provenance">')
    lines.append(f"  <strong>Source:</strong> <code>{_h(source_display)}</code> &nbsp;")
    lines.append(f"  <strong>Confidence:</strong> {memory.confidence:.0%} &nbsp;")
    lines.append(f"  <strong>Created:</strong> {_h(created_iso)} &nbsp;")
    lines.append(f"  <strong>Updated:</strong> {_h(updated_iso)}")
    lines.append("</div>")

    # 5. Details (only when it adds beyond summary).
    details_clean = memory.details.strip()
    if details_clean and details_clean != summary_clean:
        lines.append("<h2>Details</h2>")
        lines.append(f"<p>{_h(details_clean)}</p>")

    # 6. Relationships.
    if relationships:
        lines.append("<h2>Relationships</h2>")
        lines.append('<ul class="edge-list">')
        for _direction, edge_label, other_id, confidence in sorted(
            relationships, key=lambda t: (t[1], t[2])
        ):
            other = memories_by_id.get(other_id)
            other_slug = slug_by_id.get(other_id)
            if other is None or other_slug is None:
                continue
            conf_str = (
                f'<span class="confidence">({confidence:.0%})</span>'
                if confidence < 1.0  # noqa: PLR2004
                else ""
            )
            lines.append(
                f'  <li><span class="edge-label">{_h(edge_label)}</span>'
                f'<a href="{_h(other_slug)}.html">{_h(other.title)}</a>{conf_str}</li>'
            )
        lines.append("</ul>")

    # 7. Tags.
    if memory.tags:
        lines.append("<h2>Tags</h2>")
        lines.append("<div>")
        for tag in sorted(memory.tags):
            lines.append(f'  <span class="tag">{_h(tag)}</span>')
        lines.append("</div>")

    body = "\n".join(lines)
    return _page_template(title=memory.title, body=body)


def _build_index_page(
    memories: list[MemoryEntry],
    slug_by_id: dict[str, str],
) -> str:
    """Render ``index.html`` — the site landing page.

    Groups memories by kind so the index is navigable.  Empty store produces
    a minimal page with a helpful message rather than crashing.
    """
    lines: list[str] = []

    lines.append("<h1>onmc Memory Site</h1>")

    if not memories:
        lines.append(
            '<p class="empty-notice">No memories stored yet.'
            " Run <code>onmc ingest</code> to populate.</p>"
        )
        body = "\n".join(lines)
        return _page_template(title="onmc Memory Site", body=body)

    lines.append(f"<p><strong>{len(memories)}</strong> memories in this knowledge base.</p>")

    # Group by kind, sorted deterministically.
    by_kind: dict[MemoryKind, list[MemoryEntry]] = defaultdict(list)
    for mem in memories:
        by_kind[mem.kind].append(mem)

    for kind in sorted(by_kind, key=lambda k: k.value):
        kind_label = _KIND_LABELS.get(kind, kind.value)
        kind_memories = sorted(by_kind[kind], key=lambda m: (m.title.casefold(), m.id))
        lines.append(f"<h2>{_h(kind_label)} ({len(kind_memories)})</h2>")
        for mem in kind_memories:
            slug = slug_by_id[mem.id]
            lines.append('<div class="memory-card">')
            lines.append(
                f'  <div class="title"><a href="{_h(slug)}.html">{_h(mem.title)}</a></div>'
            )
            summary_short = mem.summary.strip()[:200]
            if len(mem.summary.strip()) > 200:  # noqa: PLR2004
                summary_short += "…"
            lines.append(f'  <div class="summary">{_h(summary_short)}</div>')
            lines.append("</div>")

    body = "\n".join(lines)
    return _page_template(title="onmc Memory Site", body=body)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_site(store: _MemoryStore) -> dict[str, str]:
    """Generate a self-contained static HTML site as a mapping of path → HTML content.

    Parameters
    ----------
    store:
        Any object exposing ``list_memories()`` and ``list_memory_edges()``
        (the onmc :class:`~oh_no_my_claudecode.storage.SQLiteStorage` satisfies
        this via structural typing).

    Returns
    -------
    dict[str, str]
        Keys are relative file paths like ``"my-decision-a1b2c3d4.html"`` and
        ``"index.html"``.  Values are the rendered HTML.

        The output is always non-empty: ``"index.html"`` is always present even
        when the store is empty.

        Ordering within the dict is deterministic (sorted by path).

    Notes
    -----
    - All file writes are the caller's responsibility.  This function is pure
      string generation with zero side-effects.
    - All user-supplied strings are HTML-escaped; no XSS vectors can leak from
      memory content into the generated HTML.
    - Timestamps come from the memory entries themselves — the wall clock is
      never read, so output is reproducible for the same store state.
    - Memory page links use relative ``<a href="slug.html">`` so the site
      works when opened as local files (``file://``) or served from any path.
    """
    memories = sorted(store.list_memories(), key=lambda m: (m.title.casefold(), m.id))
    edges = store.list_memory_edges()

    slug_by_id: dict[str, str] = {m.id: _page_slug(m) for m in memories}
    memories_by_id: dict[str, MemoryEntry] = {m.id: m for m in memories}
    relationships = _build_relationships(edges)

    pages: dict[str, str] = {}

    # One HTML page per memory.
    for memory in memories:
        slug = slug_by_id[memory.id]
        page_path = f"{slug}.html"
        pages[page_path] = _build_memory_page(
            memory=memory,
            slug=slug,
            relationships=relationships.get(memory.id, []),
            memories_by_id=memories_by_id,
            slug_by_id=slug_by_id,
        )

    # Index page.
    pages["index.html"] = _build_index_page(memories, slug_by_id)

    return dict(sorted(pages.items()))
