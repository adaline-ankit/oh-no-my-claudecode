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

The result is rendered to terse markdown bounded by ``budget`` characters. Every
input compiler degrades gracefully to empty on a fresh brain or empty repo, so
``build_pack`` never crashes — it just emits an empty-but-valid pack.

Determinism: all four compilers are deterministic for fixed inputs, and the
renderer is a pure function of the assembled :class:`ContextPack`, so two calls
with the same ``(storage, repo_root, goal, budget)`` produce byte-identical
markdown.
"""

from __future__ import annotations

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


def _collect_context_files(repo_root: Path, goal: str) -> list[str]:
    if not goal:
        return []
    try:
        graph = build_codegraph(repo_root)
        selection = context_files(graph, goal, budget=8)
    except Exception:  # noqa: BLE001 - graceful empty on empty/unreadable repo
        return []
    return list(selection.files)


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
