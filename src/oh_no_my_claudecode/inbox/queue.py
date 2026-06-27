"""Pure, typed core for the ``onmc inbox`` ranked work queue.

Design
------
This module is **side-effect-light and deterministic**:

- The only persisted state is the list of *manual* items, stored as JSON under
  ``.onmc/inbox/queue.json`` (mirroring the ``.onmc`` JSON convention used by
  :class:`oh_no_my_claudecode.notify.sinks.FileSink`).
- Every function that needs the wall clock takes an injected ``now`` so callers
  (and tests) get reproducible output. No function reads ``datetime.now()``
  implicitly.
- Ranking is a pure function of the items: ``score = source_weight +
  recency_bonus``. Ties break on a stable key so ordering never wobbles.

Sources
-------
An :class:`InboxItem` carries a ``source`` tag describing where it came from:

``manual``    user-added via ``onmc inbox add``
``todo``      a ``TODO`` / ``FIXME`` marker grepped from the working tree
``coverage``  a high-churn file with zero memory coverage (reuses the coverage
              compiler)
``memory``    a low-confidence / unverified memory worth revisiting

:func:`gather_candidates` unions all four into a single ranked list without
mutating persisted state.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from oh_no_my_claudecode.utils.time import isoformat_utc, parse_datetime

if TYPE_CHECKING:
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

InboxSource = Literal["manual", "todo", "coverage", "memory"]

# Relative weight per source — higher means surfaced sooner. Manual items are
# the user's explicit intent so they outrank auto-discovered signals; TODO/FIXME
# markers are concrete and actionable; coverage gaps and stale memories are
# softer "you might want to look at this" hints.
_SOURCE_WEIGHTS: dict[InboxSource, float] = {
    "manual": 100.0,
    "todo": 60.0,
    "coverage": 40.0,
    "memory": 20.0,
}

# All recognised sources, in canonical (highest-weight-first) order.
SOURCES: tuple[InboxSource, ...] = ("manual", "todo", "coverage", "memory")

# Recency contributes a bounded bonus so that, within a source, newer items
# float up without ever overtaking a higher-weight source.
_MAX_RECENCY_BONUS = 15.0
_RECENCY_HALFLIFE_DAYS = 7.0

# Default ceiling on auto-discovered candidates per source so a giant repo does
# not flood the queue.
_MAX_TODO_HITS = 50
_MAX_COVERAGE_HITS = 10
_MAX_MEMORY_HITS = 10

# A memory is "worth revisiting" when its confidence is below this threshold.
_LOW_CONFIDENCE = 0.5

# File globs we scan for TODO/FIXME markers.
_SOURCE_SUFFIXES = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".md",
)

# Directories we never descend into when grepping for markers.
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".onmc",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".tox",
    }
)

_MARKER_RE = re.compile(r"\b(TODO|FIXME)\b[:\s]*(.*)", re.IGNORECASE)

_QUEUE_DIRNAME = "inbox"
_QUEUE_FILENAME = "queue.json"


@dataclass(slots=True)
class InboxItem:
    """One ranked unit of work in the inbox queue.

    Fields
    ------
    id:
        Stable identifier. For manual items this is content-derived so the same
        text added twice collides (idempotent adds). For auto-discovered items
        it encodes the origin (file + line, or path, or memory id).
    text:
        Human-readable description of the work.
    source:
        Where the item came from — one of :data:`SOURCES`.
    score:
        Rank score (higher = more urgent). Populated by :func:`rank_items`;
        ``0.0`` until ranked.
    created_at:
        ISO-8601 UTC timestamp of when the item entered the queue. For
        auto-discovered items this is the gather time.
    """

    id: str
    text: str
    source: InboxSource
    score: float = 0.0
    created_at: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable mapping for this item."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> InboxItem:
        """Reconstruct an item from its serialised form, tolerating extras."""
        source = str(data.get("source", "manual"))
        if source not in _SOURCE_WEIGHTS:
            source = "manual"
        raw_score = data.get("score", 0.0)
        score = float(raw_score) if isinstance(raw_score, (int, float, str)) else 0.0
        return cls(
            id=str(data["id"]),
            text=str(data.get("text", "")),
            source=source,  # type: ignore[arg-type]
            score=score,
            created_at=str(data.get("created_at", "")),
        )


# ---------------------------------------------------------------------------
# Persistence (manual items only)
# ---------------------------------------------------------------------------


def _queue_path(repo_root: Path) -> Path:
    """Absolute path to the manual-items JSON store under ``.onmc/inbox/``."""
    return repo_root / ".onmc" / _QUEUE_DIRNAME / _QUEUE_FILENAME


def _load_manual(repo_root: Path) -> list[InboxItem]:
    """Load persisted manual items. Returns ``[]`` when the store is absent."""
    path = _queue_path(repo_root)
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    items: list[InboxItem] = []
    for entry in data:
        if isinstance(entry, dict):
            try:
                items.append(InboxItem.from_dict(entry))
            except (KeyError, TypeError, ValueError):
                continue
    return items


def _save_manual(repo_root: Path, items: list[InboxItem]) -> None:
    """Persist *items* (assumed all ``source == "manual"``) atomically-ish."""
    path = _queue_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.to_dict() for item in items]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _manual_id(text: str) -> str:
    """Content-derived stable id for a manual item (idempotent adds)."""
    digest = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()  # noqa: S324
    return f"manual-{digest[:12]}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def add_item(repo_root: Path, text: str, *, now: datetime) -> InboxItem:
    """Add a manual work item and persist it. Returns the stored item.

    Idempotent on text: adding the same (stripped) text twice updates the
    existing entry rather than creating a duplicate. ``now`` is injected so the
    ``created_at`` stamp is deterministic in tests.

    Raises
    ------
    ValueError
        If *text* is empty or whitespace-only.
    """
    cleaned = text.strip()
    if not cleaned:
        msg = "inbox item text must not be empty"
        raise ValueError(msg)

    items = _load_manual(repo_root)
    item_id = _manual_id(cleaned)
    created = isoformat_utc(now)

    for existing in items:
        if existing.id == item_id:
            existing.text = cleaned
            existing.created_at = created
            _save_manual(repo_root, items)
            return existing

    item = InboxItem(id=item_id, text=cleaned, source="manual", created_at=created)
    items.append(item)
    _save_manual(repo_root, items)
    return item


def list_items(repo_root: Path) -> list[InboxItem]:
    """Return the persisted manual items (unranked, in insertion order)."""
    return _load_manual(repo_root)


def _recency_bonus(created_at: str, *, now: datetime) -> float:
    """Bounded recency bonus: newest items get up to ``_MAX_RECENCY_BONUS``.

    Uses an exponential decay with a 7-day half-life. Unparseable or future
    timestamps yield the full bonus and zero bonus respectively so the function
    never raises.
    """
    created = parse_datetime(created_at)
    if created is None:
        return _MAX_RECENCY_BONUS
    age_seconds = (now - created).total_seconds()
    if age_seconds <= 0:
        return _MAX_RECENCY_BONUS
    age_days = age_seconds / 86400.0
    decay: float = 0.5 ** (age_days / _RECENCY_HALFLIFE_DAYS)
    return round(_MAX_RECENCY_BONUS * decay, 4)


def _score(item: InboxItem, *, now: datetime) -> float:
    """Deterministic score = source weight + bounded recency bonus."""
    base = _SOURCE_WEIGHTS.get(item.source, 0.0)
    return round(base + _recency_bonus(item.created_at, now=now), 4)


def rank_items(items: list[InboxItem], *, now: datetime) -> list[InboxItem]:
    """Return a new list of items sorted by descending score (deterministic).

    Each returned item is a copy with its ``score`` field populated. Ties break
    on ``(source order, id)`` so the ordering is fully stable and reproducible.
    """
    source_order = {src: i for i, src in enumerate(SOURCES)}
    ranked: list[InboxItem] = []
    for item in items:
        scored = InboxItem(
            id=item.id,
            text=item.text,
            source=item.source,
            score=_score(item, now=now),
            created_at=item.created_at,
        )
        ranked.append(scored)
    ranked.sort(
        key=lambda it: (-it.score, source_order.get(it.source, len(SOURCES)), it.id)
    )
    return ranked


# ---------------------------------------------------------------------------
# Candidate gathering (read-only union of all sources)
# ---------------------------------------------------------------------------


def _iter_source_files(repo_root: Path) -> list[Path]:
    """Sorted list of source files to scan for markers (skips noise dirs)."""
    results: list[Path] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix not in _SOURCE_SUFFIXES:
            continue
        parts = set(path.relative_to(repo_root).parts)
        if parts & _SKIP_DIRS:
            continue
        results.append(path)
    return results


def _gather_todos(repo_root: Path, *, now: datetime) -> list[InboxItem]:
    """Grep TODO/FIXME markers from source files into inbox items."""
    created = isoformat_utc(now)
    items: list[InboxItem] = []
    for path in _iter_source_files(repo_root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = path.relative_to(repo_root).as_posix()
        for lineno, line in enumerate(lines, start=1):
            match = _MARKER_RE.search(line)
            if not match:
                continue
            marker = match.group(1).upper()
            note = match.group(2).strip().rstrip(":").strip()
            text = f"{marker} in {rel}:{lineno}"
            if note:
                text += f" — {note}"
            items.append(
                InboxItem(
                    id=f"todo-{rel}:{lineno}",
                    text=text,
                    source="todo",
                    created_at=created,
                )
            )
            if len(items) >= _MAX_TODO_HITS:
                return items
    return items


def _gather_coverage(
    repo_root: Path,
    storage: SQLiteStorage,
    *,
    now: datetime,
) -> list[InboxItem]:
    """Turn uncovered hotspot files (from the coverage compiler) into items."""
    from oh_no_my_claudecode.coverage.compiler import compile_coverage

    created = isoformat_utc(now)
    report = compile_coverage(storage, repo_root)
    items: list[InboxItem] = []
    for gap in report.top_gaps[:_MAX_COVERAGE_HITS]:
        text = (
            f"Document {gap.path} "
            f"({gap.churn} commits, 0 memories) in {gap.subsystem}"
        )
        items.append(
            InboxItem(
                id=f"coverage-{gap.path}",
                text=text,
                source="coverage",
                created_at=created,
            )
        )
    return items


def _gather_memory(
    storage: SQLiteStorage,
    *,
    now: datetime,
) -> list[InboxItem]:
    """Flag low-confidence memories as items worth revisiting."""
    created = isoformat_utc(now)
    memories = storage.list_memories()
    candidates = [m for m in memories if m.confidence < _LOW_CONFIDENCE]
    candidates.sort(key=lambda m: (m.confidence, m.id))
    items: list[InboxItem] = []
    for mem in candidates[:_MAX_MEMORY_HITS]:
        text = f"Revisit low-confidence memory: {mem.title} (conf {mem.confidence:.2f})"
        items.append(
            InboxItem(
                id=f"memory-{mem.id}",
                text=text,
                source="memory",
                created_at=created,
            )
        )
    return items


def gather_candidates(
    repo_root: Path,
    storage: SQLiteStorage | None = None,
    *,
    now: datetime,
) -> list[InboxItem]:
    """Union all sources into one ranked candidate list (no state mutation).

    Combines persisted manual items, grepped TODO/FIXME markers, coverage gaps,
    and low-confidence memories, then ranks the union deterministically.

    ``storage`` is optional: when ``None`` the coverage and memory sources are
    skipped (so the feature degrades gracefully on a repo that has never run
    ``onmc ingest``). ``now`` is injected for reproducible scoring.
    """
    items: list[InboxItem] = []
    items.extend(_load_manual(repo_root))
    items.extend(_gather_todos(repo_root, now=now))
    if storage is not None:
        items.extend(_gather_coverage(repo_root, storage, now=now))
        items.extend(_gather_memory(storage, now=now))
    return rank_items(items, now=now)
