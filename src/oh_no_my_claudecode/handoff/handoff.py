"""Portable cross-session/cross-agent task-context bundle — pure & offline.

A *handoff* packages everything a fresh agent or session needs to resume a task
into one portable JSON bundle. :func:`build_handoff` composes signals that
already exist elsewhere in onmc — it invents no new analysis:

- **context pack** — :func:`oh_no_my_claudecode.pack.builder.build_pack` assembles
  the deterministic per-task context (dead-ends, decisions, reuse hints, files).
- **decisions** — :func:`oh_no_my_claudecode.orggraph.graph.build_org_graph` over
  the repo's memories, filtered to the decision entities whose lineage touches
  the goal, so prior architectural calls travel with the bundle.
- **dead ends** — :func:`oh_no_my_claudecode.guard.compiler.compile_guard`
  surfaces recorded ``FAILED_APPROACH`` memories so the resuming agent does not
  retry a known dead-end.
- **recent receipts** — the last-N tamper-evident run receipts under
  ``.agent-memory/receipts/`` (via :func:`oh_no_my_claudecode.badge.load_receipt`)
  so the fresh agent sees what was recently attempted and whether it verified.

Every source is wrapped in its own ``try/except``: a missing pack / orggraph /
guard / receipts store degrades to an empty section plus a human-readable note,
so :func:`build_handoff` never crashes on a fresh brain or empty repo.

Purity: :func:`build_handoff` performs no wall-clock reads — the caller supplies
``now`` (the command layer passes an ISO-8601 string). The four data sources are
injectable callables (defaulting to the real compilers) so tests run offline and
deterministically.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.badge import load_receipt as _real_load_receipt
from oh_no_my_claudecode.guard.compiler import compile_guard as _real_compile_guard
from oh_no_my_claudecode.orggraph.graph import (
    KIND_DECISION,
)
from oh_no_my_claudecode.orggraph.graph import (
    build_org_graph as _real_build_org_graph,
)
from oh_no_my_claudecode.pack.builder import build_pack as _real_build_pack
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import shorten, tokenize

BUNDLE_VERSION = 1
"""Monotonic schema version for forward-compatible reading of old bundles."""

_DEFAULT_RECEIPTS = 5
"""Default number of most-recent receipts to embed."""

_MAX_DECISIONS = 12
"""Cap on decision entities embedded — keeps the bundle terse."""

# The receipts live under ``.agent-memory/receipts/`` (see loop.receipt.write_receipt).
_RECEIPTS_DIR_PARTS = (".agent-memory", "receipts")

# Receipt keys copied into the bundle (a terse, resume-relevant projection).
_RECEIPT_KEYS = (
    "goal",
    "agent",
    "model",
    "verified",
    "stop_reason",
    "iterations",
    "receipt_hash",
    "ended_at",
    "started_at",
)


# ---------------------------------------------------------------------------
# Injectable source callables (defaults are the real compilers)
# ---------------------------------------------------------------------------

#: ``(storage, repo_root, goal) -> object with .to_dict()`` — the context pack.
PackBuilder = Callable[[SQLiteStorage, Path, str], Any]
#: ``() -> list[MemoryEntry]`` — the memories the org graph is built from.
MemoryLoader = Callable[[], Sequence[Any]]
#: ``(storage, goal) -> GuardResult`` — recorded dead-ends.
GuardCompiler = Callable[[SQLiteStorage, str], Any]
#: ``(repo_root, n) -> list[dict]`` — the last-N run receipts as dicts.
ReceiptLoader = Callable[[Path, int], list[dict[str, Any]]]


@dataclass
class HandoffBundle:
    """A portable, JSON-round-trippable snapshot of a task's resume context."""

    version: int
    goal: str
    created_at: str | None
    context_pack: dict[str, Any] = field(default_factory=dict)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    dead_ends: list[str] = field(default_factory=list)
    recent_receipts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "version": self.version,
            "goal": self.goal,
            "created_at": self.created_at,
            "context_pack": self.context_pack,
            "decisions": list(self.decisions),
            "dead_ends": list(self.dead_ends),
            "recent_receipts": list(self.recent_receipts),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandoffBundle:
        """Reconstruct a bundle from a (possibly partial) dict — tolerant.

        Missing keys fall back to empty/sensible defaults so a bundle written by
        an older/newer onmc still reads back without raising.
        """
        raw_version = data.get("version", BUNDLE_VERSION)
        try:
            version = int(raw_version)
        except (TypeError, ValueError):
            version = BUNDLE_VERSION
        return cls(
            version=version,
            goal=str(data.get("goal", "")),
            created_at=data.get("created_at"),
            context_pack=_as_dict(data.get("context_pack")),
            decisions=_as_dict_list(data.get("decisions")),
            dead_ends=[str(x) for x in _as_list(data.get("dead_ends"))],
            recent_receipts=_as_dict_list(data.get("recent_receipts")),
            notes=[str(x) for x in _as_list(data.get("notes"))],
        )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_handoff(
    storage: SQLiteStorage,
    repo_root: Path,
    goal: str,
    *,
    now: str | None = None,
    receipts: int = _DEFAULT_RECEIPTS,
    pack_builder: PackBuilder | None = None,
    memory_loader: MemoryLoader | None = None,
    guard_compiler: GuardCompiler | None = None,
    receipt_loader: ReceiptLoader | None = None,
) -> HandoffBundle:
    """Assemble a :class:`HandoffBundle` for *goal* — offline and pure.

    Each of the four sources is collected independently and defensively: any
    failure (or missing store/repo) leaves that section empty and appends a note,
    so the bundle is always valid. ``now`` is supplied by the caller (no
    wall-clock read here) to keep the function testable and deterministic.

    Parameters
    ----------
    storage:
        Open memory store (dead-ends, decisions, context pack).
    repo_root:
        Repository root (context pack, reuse radar, receipts directory).
    goal:
        The task description to package context for.
    now:
        Optional ISO-8601 timestamp recorded as ``created_at``. The command layer
        supplies this; ``None`` is allowed to keep the core pure.
    receipts:
        How many of the most-recent run receipts to embed.
    pack_builder, memory_loader, guard_compiler, receipt_loader:
        Injectable source callables (default to the real compilers). Tests pass
        fakes so no storage/repo is required.
    """
    clean_goal = goal.strip()
    notes: list[str] = []

    context_pack = _collect_pack(
        storage, repo_root, clean_goal, notes, pack_builder or _default_pack_builder
    )
    decisions = _collect_decisions(
        clean_goal, notes, memory_loader or _make_default_memory_loader(storage)
    )
    dead_ends = _collect_dead_ends(
        storage, clean_goal, notes, guard_compiler or _default_guard_compiler
    )
    recent = _collect_receipts(
        repo_root, receipts, notes, receipt_loader or _default_receipt_loader
    )

    return HandoffBundle(
        version=BUNDLE_VERSION,
        goal=clean_goal,
        created_at=now,
        context_pack=context_pack,
        decisions=decisions,
        dead_ends=dead_ends,
        recent_receipts=recent,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Default source callables
# ---------------------------------------------------------------------------


def _default_pack_builder(storage: SQLiteStorage, repo_root: Path, goal: str) -> Any:
    return _real_build_pack(storage, repo_root, goal)


def _make_default_memory_loader(storage: SQLiteStorage) -> MemoryLoader:
    def _loader() -> Sequence[Any]:
        return storage.list_memories()

    return _loader


def _default_guard_compiler(storage: SQLiteStorage, goal: str) -> Any:
    return _real_compile_guard(storage, goal, limit=8)


def _default_receipt_loader(repo_root: Path, n: int) -> list[dict[str, Any]]:
    """Load up to *n* most-recent receipt dicts from ``.agent-memory/receipts/``.

    Newest first by file mtime. Uses :func:`badge.load_receipt` per file so the
    parsing is shared with the badge feature. Missing dir / unreadable files
    degrade to an empty list.
    """
    receipts_dir = repo_root
    for part in _RECEIPTS_DIR_PARTS:
        receipts_dir = receipts_dir / part
    if not receipts_dir.is_dir():
        return []
    files = [p for p in receipts_dir.glob("*.json") if p.is_file()]
    files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[: max(0, n)]:
        receipt = _real_load_receipt(str(path), repo_root=repo_root)
        if receipt is not None:
            out.append(_project_receipt(receipt))
    return out


# ---------------------------------------------------------------------------
# Collectors (each degrades gracefully + records a note on failure)
# ---------------------------------------------------------------------------


def _collect_pack(
    storage: SQLiteStorage,
    repo_root: Path,
    goal: str,
    notes: list[str],
    builder: PackBuilder,
) -> dict[str, Any]:
    try:
        pack = builder(storage, repo_root, goal)
    except Exception as exc:  # noqa: BLE001 - a missing pack must never crash the bundle
        notes.append(f"context pack unavailable: {exc}")
        return {}
    to_dict = getattr(pack, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
        except Exception as exc:  # noqa: BLE001
            notes.append(f"context pack serialisation failed: {exc}")
            return {}
        return _as_dict(result)
    if isinstance(pack, dict):
        return pack
    notes.append("context pack unavailable: builder returned no serialisable pack")
    return {}


def _collect_decisions(
    goal: str,
    notes: list[str],
    loader: MemoryLoader,
) -> list[dict[str, Any]]:
    try:
        memories = list(loader())
    except Exception as exc:  # noqa: BLE001 - missing store must not crash the bundle
        notes.append(f"decisions unavailable: {exc}")
        return []
    if not memories:
        notes.append("no memories stored — decisions section empty")
        return []
    try:
        graph = _real_build_org_graph(memories)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"decision graph unavailable: {exc}")
        return []

    goal_tokens = set(tokenize(goal))
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for entity in graph.entities:
        if entity.kind != KIND_DECISION:
            continue
        overlap = len(goal_tokens & set(tokenize(entity.name))) if goal_tokens else 0
        scored.append(
            (
                overlap,
                entity.name,
                {
                    "title": entity.name,
                    "relevance": overlap,
                    "memory_ids": list(entity.memory_ids),
                },
            )
        )
    if not scored:
        notes.append("no decision-kind memories found for this repo")
        return []
    # Most goal-relevant first; stable tie-break on title.
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [payload for _, _, payload in scored[:_MAX_DECISIONS]]


def _collect_dead_ends(
    storage: SQLiteStorage,
    goal: str,
    notes: list[str],
    compiler: GuardCompiler,
) -> list[str]:
    try:
        result = compiler(storage, goal)
    except Exception as exc:  # noqa: BLE001 - guard failure must not crash the bundle
        notes.append(f"dead-ends unavailable: {exc}")
        return []
    entries = getattr(result, "entries", None) or []
    lines: list[str] = []
    for entry in entries:
        title = getattr(entry, "title", "") or ""
        why = getattr(entry, "why_it_failed", "") or ""
        if not title:
            continue
        lines.append(f"{title} — {shorten(why, max_length=160)}" if why else title)
    if not lines:
        notes.append("no recorded dead-ends match this goal")
    return lines


def _collect_receipts(
    repo_root: Path,
    n: int,
    notes: list[str],
    loader: ReceiptLoader,
) -> list[dict[str, Any]]:
    try:
        receipts = loader(repo_root, n)
    except Exception as exc:  # noqa: BLE001 - receipts store optional
        notes.append(f"recent receipts unavailable: {exc}")
        return []
    if not receipts:
        notes.append("no recent run receipts found")
    return receipts


def _project_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Copy the resume-relevant subset of a receipt dict (terse projection)."""
    return {key: receipt.get(key) for key in _RECEIPT_KEYS if key in receipt}


# ---------------------------------------------------------------------------
# IO — write / read (tolerant)
# ---------------------------------------------------------------------------


def write_bundle(bundle: HandoffBundle, path: str | Path) -> Path:
    """Write *bundle* as pretty JSON to *path* (creating parent dirs)."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dest


def read_bundle(path: str | Path) -> HandoffBundle:
    """Read a bundle from *path*, tolerating a partial/older shape.

    Raises :class:`FileNotFoundError` when the file is absent and
    :class:`ValueError` when the file is not a JSON object — callers surface
    these as clean CLI errors.
    """
    src = Path(path)
    text = src.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{src}: not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{src}: expected a JSON object, got {type(data).__name__}")
    return HandoffBundle.from_dict(data)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_resume(bundle: HandoffBundle, console: Any) -> None:
    """Render *bundle* as a human/agent-readable briefing to *console*.

    ``console`` is any object with a ``print(str)`` method (a Rich ``Console`` or
    a thin shim). The output leads with the goal, then the dead-ends to avoid
    (loudest signal first), key decisions, a context summary, and recent
    outcomes. Empty sections say so explicitly rather than being omitted.
    """
    console.print("# Handoff briefing")
    console.print("")
    console.print(f"Goal: {bundle.goal or '(none)'}")
    if bundle.created_at:
        console.print(f"Created: {bundle.created_at}")
    console.print("")

    console.print("## Dead ends — DO NOT retry")
    if bundle.dead_ends:
        for line in bundle.dead_ends:
            console.print(f"- {line}")
    else:
        console.print("(none recorded)")
    console.print("")

    console.print("## Key decisions (respect these)")
    if bundle.decisions:
        for dec in bundle.decisions:
            title = str(dec.get("title", "")).strip() or "(untitled)"
            console.print(f"- {title}")
    else:
        console.print("(none recorded)")
    console.print("")

    console.print("## Context summary")
    for line in _context_summary_lines(bundle.context_pack):
        console.print(line)
    console.print("")

    console.print("## Recent outcomes")
    if bundle.recent_receipts:
        for receipt in bundle.recent_receipts:
            console.print(_receipt_line(receipt))
    else:
        console.print("(no recent run receipts)")

    if bundle.notes:
        console.print("")
        console.print("## Notes (partial sources)")
        for note in bundle.notes:
            console.print(f"- {note}")


def summarize(bundle: HandoffBundle) -> str:
    """Return a one-line summary of a bundle's contents (for CLI confirmation)."""
    files = bundle.context_pack.get("context_files")
    file_count = len(files) if isinstance(files, list) else 0
    return (
        f"{len(bundle.decisions)} decision(s), "
        f"{len(bundle.dead_ends)} dead-end(s), "
        f"{file_count} context file(s), "
        f"{len(bundle.recent_receipts)} recent receipt(s)"
    )


def _context_summary_lines(context_pack: dict[str, Any]) -> list[str]:
    if not context_pack:
        return ["(no context pack)"]
    lines: list[str] = []
    reuse = context_pack.get("reuse_hints")
    if isinstance(reuse, list) and reuse:
        lines.append(f"- Reuse candidates: {len(reuse)}")
    files = context_pack.get("context_files")
    if isinstance(files, list) and files:
        lines.append("- Context files:")
        for path in files:
            lines.append(f"  - {path}")
    if not lines:
        lines.append("(context pack has no reuse hints or files)")
    return lines


def _receipt_line(receipt: dict[str, Any]) -> str:
    verified = receipt.get("verified")
    mark = "verified" if verified is True else ("unverified" if verified is False else "?")
    goal = shorten(str(receipt.get("goal", "")), max_length=60) or "(no goal)"
    agent = receipt.get("agent") or "?"
    stop = receipt.get("stop_reason") or "?"
    return f"- [{mark}] {goal} (agent={agent}, stop={stop})"


# ---------------------------------------------------------------------------
# Small tolerant coercion helpers (for from_dict)
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in _as_list(value) if isinstance(item, dict)]
