"""Per-task context pack builder — terse, deterministic, offline.

``build_pack`` assembles a compact context pack for a spawned coding agent by
composing four existing, offline compilers (no new retrieval logic, no LLM, no
network):

- **dead ends** — :func:`oh_no_my_claudecode.guard.compiler.compile_guard`
  surfaces recorded ``FAILED_APPROACH`` memories so the agent does not retry a
  known dead-end.
- **decisions** — :func:`oh_no_my_claudecode.recall.compiler.compile_recall`,
  filtered to ``decision``-kind memories, so prior architectural calls are
  respected.
- **reuse hints** — :func:`oh_no_my_claudecode.reuse.radar.find_reuse` points at
  existing symbols that may already implement the thing (DRY).
- **context files** — :func:`oh_no_my_claudecode.codegraph.builder.context_files`
  over a freshly built code graph gives a tiny, relevant file/symbol slice.
  Explicit file paths mentioned in the goal are **force-included first** so the
  agent always has the files it was told to edit.

The result is rendered to terse markdown bounded by ``budget`` characters. Every
input compiler degrades gracefully to empty on a fresh brain or empty repo, so
``build_pack`` never crashes — it just emits an empty-but-valid pack.

Determinism: all four compilers are deterministic for fixed inputs, and the
renderer is a pure function of the assembled :class:`ContextPack`, so two calls
with the same ``(storage, repo_root, goal, budget)`` produce byte-identical
markdown.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from oh_no_my_claudecode.codegraph import build_codegraph, context_files
from oh_no_my_claudecode.guard.compiler import compile_guard
from oh_no_my_claudecode.recall.compiler import compile_recall
from oh_no_my_claudecode.reuse import find_reuse
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import shorten

DEFAULT_BUDGET = 12000
"""Default character budget for the rendered pack markdown."""

_MIN_BUDGET = 400
"""Floor so a pathologically small budget still yields a usable header."""

_DECISION_KIND = "decision"
"""``MemoryKind.DECISION`` value — the recall kind we keep for the pack."""

_HEADER = "# Context Pack"

# Cap on context files the builder returns (force-included goal paths count
# toward this; codegraph fills the remainder).
_CONTEXT_FILE_BUDGET = 8

# Regex that extracts path-like tokens from free text.  A token qualifies when
# it contains at least one ``/`` separator — that rules out bare filenames like
# "cache.py" while still catching "src/cache.py" and deep nested paths.
_PATH_TOKEN_RE = re.compile(r"[\w./-]*[\w-]/[\w./-]+")

# Known source-file extensions for goal-path extraction.  Values are dotted
# because membership is tested against ``Path(token).suffix``, which always
# carries a leading dot (so "src/foo.ts" → ".ts").  Bare tokens like "ts" are
# not treated as extensions here — they only match when they resolve to a real
# on-disk file.  The set is intentionally broad — we want to cover any file a
# user plausibly names in a goal.
_SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".mts",
        ".cts",
        ".go",
        ".rs",
        ".java",
        ".rb",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".swift",
        ".kt",
        ".kts",
        ".scala",
        ".ex",
        ".exs",
        ".sh",
        ".bash",
        ".zsh",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".md",
        ".mdx",
    }
)


@dataclass(frozen=True, slots=True)
class DeadEnd:
    """A recorded dead-end the agent should not retry."""

    title: str
    why: str


@dataclass(frozen=True, slots=True)
class Decision:
    """A prior decision the agent should respect."""

    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReuseHint:
    """An existing symbol that may already do the thing."""

    symbol: str
    location: str  # "path:lineno"
    note: str


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A tiny, deterministic per-task context pack.

    Attributes mirror the four composed sources plus the goal and the budget the
    pack was built under. :meth:`to_dict` is JSON-safe for the ``--json`` CLI
    surface.
    """

    goal: str
    budget: int
    dead_ends: list[DeadEnd] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    reuse_hints: list[ReuseHint] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when no source produced any material."""
        return not (
            self.dead_ends or self.decisions or self.reuse_hints or self.context_files
        )

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict (markdown included for convenience)."""
        return {
            "goal": self.goal,
            "budget": self.budget,
            "dead_ends": [asdict(d) for d in self.dead_ends],
            "decisions": [asdict(d) for d in self.decisions],
            "reuse_hints": [asdict(h) for h in self.reuse_hints],
            "context_files": list(self.context_files),
            "markdown": render_pack_markdown(self),
        }


def build_pack(
    storage: SQLiteStorage,
    repo_root: Path,
    goal: str,
    *,
    budget: int = DEFAULT_BUDGET,
) -> ContextPack:
    """Assemble a deterministic, offline context pack for *goal*.

    Composes the four reused compilers, degrading each to empty on missing data.
    The returned pack is bounded only by the per-section item caps here; the
    *budget* governs the rendered markdown length in :func:`render_pack_markdown`.

    Explicit file paths found in *goal* are force-included at the front of the
    context files list (highest-signal input always wins).

    Parameters
    ----------
    storage:
        Open memory store (for dead-ends and decisions).
    repo_root:
        Repository root (for code graph and reuse radar).
    goal:
        The task description to build context for.
    budget:
        Character budget for the rendered markdown (floored at ``_MIN_BUDGET``).
    """
    clean_goal = goal.strip()
    effective_budget = max(_MIN_BUDGET, budget)

    dead_ends = _collect_dead_ends(storage, clean_goal)
    decisions = _collect_decisions(storage, clean_goal)
    reuse_hints = _collect_reuse(repo_root, clean_goal)
    files = _collect_context_files(repo_root, clean_goal)

    return ContextPack(
        goal=clean_goal,
        budget=effective_budget,
        dead_ends=dead_ends,
        decisions=decisions,
        reuse_hints=reuse_hints,
        context_files=files,
    )


def _collect_dead_ends(storage: SQLiteStorage, goal: str) -> list[DeadEnd]:
    if not goal:
        return []
    try:
        result = compile_guard(storage, goal, limit=5)
    except Exception:  # noqa: BLE001 - a fresh/empty brain must never crash the pack
        return []
    return [
        DeadEnd(title=entry.title, why=shorten(entry.why_it_failed, max_length=160))
        for entry in result.entries
    ]


def _collect_decisions(storage: SQLiteStorage, goal: str) -> list[Decision]:
    if not goal:
        return []
    try:
        result = compile_recall(storage, goal, limit=8)
    except Exception:  # noqa: BLE001 - graceful empty on missing store
        return []
    decisions: list[Decision] = []
    for entry in result.entries:
        if entry.kind != _DECISION_KIND:
            continue
        detail = entry.resolution or entry.what_happened
        decisions.append(
            Decision(title=entry.title, detail=shorten(detail, max_length=160))
        )
        if len(decisions) >= 5:
            break
    return decisions


def _collect_reuse(repo_root: Path, goal: str) -> list[ReuseHint]:
    if not goal:
        return []
    try:
        hits = find_reuse(repo_root, goal, limit=5)
    except Exception:  # noqa: BLE001 - graceful empty on empty/unreadable repo
        return []
    return [
        ReuseHint(
            symbol=hit.signature or hit.symbol,
            location=f"{hit.file}:{hit.lineno}",
            note=shorten(hit.doc_excerpt, max_length=120),
        )
        for hit in hits
    ]


def extract_goal_paths(goal: str, repo_root: Path) -> list[str]:
    """Extract explicit file paths from *goal* that exist under *repo_root*.

    Scans *goal* for path-like tokens (contain ``/``, optionally end in a known
    source extension).  Returns the repo-relative path strings for any token
    that resolves to a real file on disk.  Order is stable (first-seen wins for
    duplicates).  Never raises.

    This is the "fix B" hook: callers treat the returned paths as the strongest
    possible context signal and include them before any code-graph ranking.
    """
    seen: set[str] = set()
    found: list[str] = []
    for match in _PATH_TOKEN_RE.finditer(goal):
        token = match.group(0).strip("/")
        if not token or token in seen:
            continue
        seen.add(token)
        # Accept tokens that end in a known source extension OR that resolve as
        # a file on disk regardless of extension.
        suffix = Path(token).suffix.lower()
        if suffix and suffix not in _SOURCE_EXTENSIONS:
            # Has a suffix but it's not a source extension — skip.
            continue
        candidate = repo_root / token
        try:
            if candidate.is_file():
                found.append(token)
        except OSError:
            pass
    return found


def _collect_context_files(repo_root: Path, goal: str) -> list[str]:
    """Collect context files for *goal*, with explicit goal paths ranked first.

    1. Extract any file paths explicitly named in the goal that exist on disk.
       These are force-included at position 0 — they represent the strongest
       possible signal (the user literally named them).
    2. Build the code graph and use ``context_files`` for relevance scoring.
       For each force-included file, also pull in its 1-hop graph neighbors
       (imports and dependents) if the graph has them.
    3. Fill remaining budget slots with code-graph ranked files.
    4. Dedup (first-seen wins) and cap at ``_CONTEXT_FILE_BUDGET``.
    """
    if not goal:
        return []

    # Step 1: explicit goal paths (highest signal).
    goal_paths = extract_goal_paths(goal, repo_root)

    # Step 2: build codegraph (needed for scoring + neighbors).
    graph = None
    try:
        graph = build_codegraph(repo_root)
    except Exception:  # noqa: BLE001, S110, SIM105 - graceful degradation
        graph = None

    ordered: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        if path not in seen:
            seen.add(path)
            ordered.append(path)

    # Force-include goal paths first.
    for gp in goal_paths:
        _add(gp)
        # Pull in 1-hop neighbors from the graph if available.
        if graph is not None:
            node = graph.nodes.get(gp)
            if node is not None:
                for imp in node.imports:
                    _add(imp)
                for dep in graph.dependents.get(gp, []):
                    _add(dep)

    # Fill remaining budget with codegraph-ranked files.
    if graph is not None:
        try:
            remaining = max(0, _CONTEXT_FILE_BUDGET - len(ordered))
            if remaining > 0:
                selection = context_files(graph, goal, budget=_CONTEXT_FILE_BUDGET)
                for path in selection.files:
                    _add(path)
        except Exception:  # noqa: BLE001, S110, SIM105 - graceful: empty graph leaves forced paths
            ...

    return ordered[:_CONTEXT_FILE_BUDGET]


def render_pack_markdown(pack: ContextPack) -> str:
    """Render *pack* to terse markdown bounded by ``pack.budget`` characters.

    Pure function of the pack: deterministic and side-effect free. Sections with
    no items are emitted with a short ``_(none)_`` placeholder so the shape of
    the pack is always legible. If the assembled markdown exceeds the budget it
    is hard-truncated with a ``[truncated]`` marker.
    """
    lines: list[str] = [_HEADER, "", f"**Goal:** {pack.goal or '(none)'}", ""]

    lines.append("## Dead ends (do not retry)")
    if pack.dead_ends:
        lines.extend(
            f"- **{d.title}** — {d.why}" if d.why else f"- **{d.title}**"
            for d in pack.dead_ends
        )
    else:
        lines.append("_(none recorded)_")
    lines.append("")

    lines.append("## Decisions (respect these)")
    if pack.decisions:
        lines.extend(
            f"- **{d.title}** — {d.detail}" if d.detail else f"- **{d.title}**"
            for d in pack.decisions
        )
    else:
        lines.append("_(none recorded)_")
    lines.append("")

    lines.append("## Reuse first")
    if pack.reuse_hints:
        lines.extend(
            f"- `{h.symbol}` ({h.location})" + (f" — {h.note}" if h.note else "")
            for h in pack.reuse_hints
        )
    else:
        lines.append("_(no candidates)_")
    lines.append("")

    lines.append("## Context files")
    if pack.context_files:
        lines.extend(f"- `{path}`" for path in pack.context_files)
    else:
        lines.append("_(none)_")
    lines.append("")

    markdown = "\n".join(lines).rstrip() + "\n"
    if len(markdown) <= pack.budget:
        return markdown
    return _truncate(markdown, pack.budget)


def _truncate(markdown: str, budget: int) -> str:
    marker = "\n\n[truncated]\n"
    keep = max(0, budget - len(marker))
    return markdown[:keep].rstrip() + marker
