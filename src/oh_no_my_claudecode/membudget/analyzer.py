"""Pure analysis core for ``onmc membudget``.

``analyze(memories, *, limit)`` inspects a list of :class:`MemoryEntry`-like
objects and returns a :class:`BudgetReport` — fully deterministic and offline.
No I/O, no database access, no LLM calls.  The caller (CLI) decides whether
to persist anything; this module is read-only / advisory.

Design
------
- **Budget check**: total UTF-8 byte size of (title + summary + details) across
  all entries is compared to *limit*.  Over budget → ``over_budget=True``.
- **Per-kind breakdown**: byte size and entry count grouped by ``kind``.
- **Consolidation suggestions**: heuristic, deterministic recommendations:
    MERGE_DUPLICATES  — near-duplicate pairs detected by Jaccard ≥ 0.55 on
                        (title + summary + details) tokens within the same kind.
    MOVE_TO_TOPIC     — individual entries whose ``details`` field alone exceeds
                        *verbose_threshold* bytes; better stored in a topic file
                        and linked by reference.
    DROP_STALE        — entries where ``staleness`` is "stale" or "orphaned";
                        carry no signal and inflate the budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

# ── constants ─────────────────────────────────────────────────────────────────

# Default byte budget (256 KiB — covers ~500 medium entries comfortably).
DEFAULT_LIMIT_BYTES: int = 256 * 1024

# Details-field size threshold for MOVE_TO_TOPIC suggestions (4 KiB).
_VERBOSE_THRESHOLD_BYTES: int = 4 * 1024

# Jaccard threshold for near-duplicate detection (mirrors consolidation.py).
_DEDUP_JACCARD: float = 0.55

# Stopwords excluded from tokenisation (mirrors utils/text.py convention).
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "with",
    }
)

# Staleness values that warrant DROP_STALE suggestions.
_STALE_VALUES: frozenset[str] = frozenset({"stale", "orphaned"})


# ── suggestion kinds ──────────────────────────────────────────────────────────


class SuggestionKind(StrEnum):
    """Advisory suggestion categories produced by the analyzer."""

    MERGE_DUPLICATES = "merge_duplicates"
    MOVE_TO_TOPIC = "move_to_topic"
    DROP_STALE = "drop_stale"


# ── protocol (structural typing — no pydantic import) ──────────────────────────


@runtime_checkable
class MemoryLike(Protocol):
    """Structural interface for MemoryEntry — avoids importing pydantic models."""

    id: str
    kind: object  # StrEnum or str — we call str() on it
    title: str
    summary: str
    details: str
    staleness: object  # str | None


# ── dataclasses ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KindBreakdown:
    """Per-kind size and count statistics."""

    kind: str
    entry_count: int
    byte_size: int


@dataclass(frozen=True)
class Suggestion:
    """A single advisory suggestion to reduce budget or improve quality."""

    kind: SuggestionKind
    entry_ids: tuple[str, ...]
    description: str


@dataclass
class BudgetReport:
    """Full analysis report returned by :func:`analyze`."""

    total_bytes: int
    limit_bytes: int
    over_budget: bool
    entry_count: int
    breakdown: list[KindBreakdown] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)

    # Computed on post-init so callers can read it directly.
    budget_used_pct: float = field(init=False)

    def __post_init__(self) -> None:
        if self.limit_bytes > 0:
            self.budget_used_pct = round(self.total_bytes / self.limit_bytes * 100, 1)
        else:
            self.budget_used_pct = 0.0

    @property
    def merge_count(self) -> int:
        """Number of MERGE_DUPLICATES suggestions."""
        return sum(1 for s in self.suggestions if s.kind == SuggestionKind.MERGE_DUPLICATES)

    @property
    def move_count(self) -> int:
        """Number of MOVE_TO_TOPIC suggestions."""
        return sum(1 for s in self.suggestions if s.kind == SuggestionKind.MOVE_TO_TOPIC)

    @property
    def drop_count(self) -> int:
        """Number of DROP_STALE suggestions."""
        return sum(1 for s in self.suggestions if s.kind == SuggestionKind.DROP_STALE)


# ── tokenisation helpers ──────────────────────────────────────────────────────


def _tokenize(text: str) -> set[str]:
    """Return a set of lowercase word tokens from *text*, excluding stopwords."""
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def _jaccard(set_a: set[str], set_b: set[str]) -> float:
    """Return Jaccard similarity between two token sets."""
    if not set_a and not set_b:
        return 1.0
    union = len(set_a | set_b)
    return len(set_a & set_b) / union if union else 0.0


def _entry_bytes(mem: MemoryLike) -> int:
    """Return the UTF-8 byte size of the three main text fields."""
    return (
        len(mem.title.encode("utf-8"))
        + len(mem.summary.encode("utf-8"))
        + len(mem.details.encode("utf-8"))
    )


def _entry_tokens(mem: MemoryLike) -> set[str]:
    """Return the union token set for the full text of a memory."""
    return _tokenize(f"{mem.title} {mem.summary} {mem.details}")


# ── core analysis ─────────────────────────────────────────────────────────────


def analyze(
    memories: list[MemoryLike],
    *,
    limit: int = DEFAULT_LIMIT_BYTES,
    verbose_threshold: int = _VERBOSE_THRESHOLD_BYTES,
) -> BudgetReport:
    """Analyse *memories* and return a :class:`BudgetReport`.

    Parameters
    ----------
    memories:
        All memory entries to analyse.  Any object satisfying the
        :class:`MemoryLike` structural protocol is accepted — no pydantic
        import required.
    limit:
        Budget ceiling in bytes.  Default is 256 KiB.
    verbose_threshold:
        Byte size of the ``details`` field above which a MOVE_TO_TOPIC
        suggestion is emitted.  Default is 4 KiB.

    Returns
    -------
    BudgetReport
        Advisory report — deterministic, no I/O.
    """
    if not memories:
        return BudgetReport(
            total_bytes=0,
            limit_bytes=limit,
            over_budget=False,
            entry_count=0,
            breakdown=[],
            suggestions=[],
        )

    # ── totals and per-kind breakdown ─────────────────────────────────────
    total_bytes = 0
    kind_bytes: dict[str, int] = {}
    kind_counts: dict[str, int] = {}

    for mem in memories:
        kb = _entry_bytes(mem)
        total_bytes += kb
        kind_key = str(mem.kind)
        kind_bytes[kind_key] = kind_bytes.get(kind_key, 0) + kb
        kind_counts[kind_key] = kind_counts.get(kind_key, 0) + 1

    breakdown = [
        KindBreakdown(kind=k, entry_count=kind_counts[k], byte_size=kind_bytes[k])
        for k in sorted(kind_bytes)
    ]

    suggestions: list[Suggestion] = []

    # ── DROP_STALE suggestions ────────────────────────────────────────────
    for mem in memories:
        staleness = str(mem.staleness) if mem.staleness is not None else ""
        if staleness in _STALE_VALUES:
            suggestions.append(
                Suggestion(
                    kind=SuggestionKind.DROP_STALE,
                    entry_ids=(mem.id,),
                    description=(
                        f"Entry '{mem.title[:60]}' (id={mem.id}) has staleness='{staleness}' "
                        "and carries no active signal — consider dropping it to reclaim budget."
                    ),
                )
            )

    # ── MOVE_TO_TOPIC suggestions ─────────────────────────────────────────
    for mem in memories:
        details_bytes = len(mem.details.encode("utf-8"))
        if details_bytes > verbose_threshold:
            suggestions.append(
                Suggestion(
                    kind=SuggestionKind.MOVE_TO_TOPIC,
                    entry_ids=(mem.id,),
                    description=(
                        f"Entry '{mem.title[:60]}' (id={mem.id}) has a details field of "
                        f"{details_bytes} bytes (>{verbose_threshold} threshold). "
                        "Move verbose content to a topic file and store a reference instead."
                    ),
                )
            )

    # ── MERGE_DUPLICATES suggestions ──────────────────────────────────────
    # Group by kind first — duplicates only suggested within the same kind.
    by_kind: dict[str, list[MemoryLike]] = {}
    for mem in memories:
        k = str(mem.kind)
        by_kind.setdefault(k, []).append(mem)

    seen_pairs: set[frozenset[str]] = set()
    for group in by_kind.values():
        # Sort by id for deterministic ordering.
        group_sorted = sorted(group, key=lambda m: m.id)
        for i, mem_a in enumerate(group_sorted):
            toks_a = _entry_tokens(mem_a)
            for mem_b in group_sorted[i + 1 :]:
                pair = frozenset({mem_a.id, mem_b.id})
                if pair in seen_pairs:
                    continue
                toks_b = _entry_tokens(mem_b)
                if _jaccard(toks_a, toks_b) >= _DEDUP_JACCARD:
                    seen_pairs.add(pair)
                    # Order ids deterministically (smaller first).
                    ordered = tuple(sorted([mem_a.id, mem_b.id]))
                    suggestions.append(
                        Suggestion(
                            kind=SuggestionKind.MERGE_DUPLICATES,
                            entry_ids=ordered,
                            description=(
                                f"Entries '{mem_a.title[:40]}' and '{mem_b.title[:40]}' "
                                f"(ids={ordered[0]}, {ordered[1]}) share "
                                f"≥{int(_DEDUP_JACCARD * 100)}% token overlap within the "
                                "same kind — consider merging them."
                            ),
                        )
                    )

    # Sort suggestions: DROP_STALE first (biggest budget impact), then
    # MERGE_DUPLICATES, then MOVE_TO_TOPIC.  Stable sort preserves relative
    # order within each kind.
    _kind_order = {
        SuggestionKind.DROP_STALE: 0,
        SuggestionKind.MERGE_DUPLICATES: 1,
        SuggestionKind.MOVE_TO_TOPIC: 2,
    }
    suggestions.sort(key=lambda s: _kind_order[s.kind])

    return BudgetReport(
        total_bytes=total_bytes,
        limit_bytes=limit,
        over_budget=total_bytes > limit,
        entry_count=len(memories),
        breakdown=breakdown,
        suggestions=suggestions,
    )
