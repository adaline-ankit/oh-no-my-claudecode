"""User profile compiler — PURE, deterministic, no LLM, no network.

Reads user-scope memories from ``~/.onmc/user.db`` and buckets them into
behavioral categories by combining memory kind + simple keyword signals.
Weights each memory by ``confidence × feedback × recency-decay`` (reusing the
decay formula from ``recall/compiler.py``).

Bucket derivation rules
-----------------------
1. **frequent_mistakes** — memories where:
   - kind == FAILED_APPROACH, OR
   - any keyword in {correction, don't, never, avoid, mistake, wrong, fix} appears
     in title+summary (case-insensitive).
2. **preferences** — memories where:
   - kind == DECISION, OR
   - "preference" tag present, OR
   - any keyword in {prefer, always, use, instead, favor, choose} appears in
     title+summary that was NOT already bucketed as a mistake.
3. **tooling** — memories where:
   - any tooling keyword in {pytest, ruff, mypy, lint, type, format, black, flake,
     isort, pre-commit, git, docker, make, uv, pip, poetry, venv, ci, github,
     actions, test, build} appears in title+summary, OR
   - "tooling" or "tool" tag is present,
   AND not already bucketed as mistake or preference.
4. **patterns** — everything else (catch-all for generic coding style).

Priority: mistakes > preferences > tooling > patterns.
Each bucket is bounded to ``max_items`` (default 5) top-weighted entries.
Total ``derived_from`` = number of user memories that contributed to at least
one bucket.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind

# ---------------------------------------------------------------------------
# Decay constants (mirrors recall/compiler.py)
# ---------------------------------------------------------------------------

_DECAY_HALF_LIFE_DAYS: float = 90.0
_DECAY_FLOOR: float = 0.3

# ---------------------------------------------------------------------------
# Bucket keyword sets
# ---------------------------------------------------------------------------

_MISTAKE_KEYWORDS: frozenset[str] = frozenset(
    {"correction", "don't", "dont", "never", "avoid", "mistake", "wrong", "fix", "incorrect"}
)
_PREFERENCE_KEYWORDS: frozenset[str] = frozenset(
    {"prefer", "always", "instead", "favor", "favour", "choose"}
)
_TOOLING_KEYWORDS: frozenset[str] = frozenset(
    {
        "pytest",
        "ruff",
        "mypy",
        "lint",
        "type",
        "format",
        "black",
        "flake",
        "isort",
        "pre-commit",
        "precommit",
        "git",
        "docker",
        "make",
        "uv",
        "pip",
        "poetry",
        "venv",
        "ci",
        "github",
        "actions",
        "test",
        "build",
        "unittest",
        "coverage",
        "tox",
    }
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class UserProfile:
    """Derived behavioral profile from user-scope memories.

    All lists contain ``(title, summary)`` string pairs bounded to ``max_items``
    entries each, ordered by weight descending.

    Attributes:
        preferences: Recurring tool/style preferences (e.g. "prefer pytest").
        patterns: Generic coding patterns that don't fit other buckets.
        frequent_mistakes: Known anti-patterns the user has explicitly recorded.
        tooling: Tooling-specific signals (linters, CI, build tools).
        salient_memory_ids: IDs of the top-weighted memories across all buckets.
        derived_from: Total count of user memories that contributed to this profile.
    """

    preferences: list[tuple[str, str]] = field(default_factory=list)
    patterns: list[tuple[str, str]] = field(default_factory=list)
    frequent_mistakes: list[tuple[str, str]] = field(default_factory=list)
    tooling: list[tuple[str, str]] = field(default_factory=list)
    salient_memory_ids: list[str] = field(default_factory=list)
    derived_from: int = 0

    @property
    def is_empty(self) -> bool:
        """Return True when the profile has nothing to show."""
        return not (self.preferences or self.patterns or self.frequent_mistakes or self.tooling)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _decay_factor(memory: MemoryEntry, now: datetime) -> float:
    """Age-based decay for confidence contribution (mirrors recall/compiler.py)."""
    anchor: datetime = memory.last_verified_at or memory.updated_at or memory.created_at
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    age_days = max(0.0, (now - anchor).total_seconds() / 86_400.0)
    feedback_clamp = max(0.0, min(1.0, memory.feedback_score))
    effective_age = age_days * (1.0 - 0.5 * feedback_clamp)
    raw = math.pow(2.0, -effective_age / _DECAY_HALF_LIFE_DAYS)
    return max(_DECAY_FLOOR, raw)


def _weight(memory: MemoryEntry, now: datetime) -> float:
    """Composite weight: confidence × decay × feedback_bonus."""
    decay = _decay_factor(memory, now)
    # feedback_score in [-1, 1]; map to [0, 1] bonus
    feedback_bonus = 1.0 + max(0.0, memory.feedback_score) * 0.1
    return memory.confidence * decay * feedback_bonus


def _haystack(memory: MemoryEntry) -> str:
    """Return a lower-cased string of all searchable fields."""
    return " ".join([memory.title, memory.summary, " ".join(memory.tags)]).lower()


def _matches_any(text: str, keywords: frozenset[str]) -> bool:
    """Return True when any keyword appears as a whole word in *text*."""
    words = set(re.findall(r"[a-z']+", text))
    return bool(words & keywords)


def _is_mistake(memory: MemoryEntry) -> bool:
    """True when memory signals a known anti-pattern or correction."""
    if memory.kind == MemoryKind.FAILED_APPROACH:
        return True
    hay = _haystack(memory)
    return _matches_any(hay, _MISTAKE_KEYWORDS)


def _is_preference(memory: MemoryEntry) -> bool:
    """True when memory signals a deliberate preference or decision."""
    if memory.kind == MemoryKind.DECISION:
        return True
    hay = _haystack(memory)
    if "preference" in memory.tags or "user-pref" in memory.tags:
        return True
    return _matches_any(hay, _PREFERENCE_KEYWORDS)


def _is_tooling(memory: MemoryEntry) -> bool:
    """True when memory relates to tooling choices."""
    if "tooling" in memory.tags or "tool" in memory.tags:
        return True
    hay = _haystack(memory)
    return _matches_any(hay, _TOOLING_KEYWORDS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_user_profile(
    memories: list[MemoryEntry],
    *,
    now: datetime | None = None,
    max_items: int = 5,
) -> UserProfile:
    """Derive a behavioral UserProfile from *memories*.

    Args:
        memories: All user-scope memories from ``~/.onmc/user.db``.  Pass an empty
            list to get an empty profile (graceful-empty; never raises).
        now: Reference timestamp for recency-decay.  Injected in tests to keep
            results deterministic.  Defaults to current UTC time.
        max_items: Maximum entries per bucket.

    Returns:
        A ``UserProfile`` with up to ``max_items`` entries in each bucket.
        All buckets may be empty when the user store is empty.
    """
    ref_now: datetime = now if now is not None else datetime.now(UTC)

    # Filter out explicitly rejected memories (mirrors boot_digest.py policy).
    eligible = [m for m in memories if m.feedback_score > -0.5 and m.confidence > 0.0]

    if not eligible:
        return UserProfile()

    # Assign weights once.
    weighted: list[tuple[float, MemoryEntry]] = [
        (_weight(m, ref_now), m) for m in eligible
    ]
    weighted.sort(key=lambda x: -x[0])  # descending weight

    # Bucket assignment — priority: mistakes > preferences > tooling > patterns.
    buckets: dict[str, list[tuple[float, MemoryEntry]]] = {
        "mistakes": [],
        "preferences": [],
        "tooling": [],
        "patterns": [],
    }
    contributed_ids: set[str] = set()

    for w, m in weighted:
        contributed_ids.add(m.id)
        if _is_mistake(m):
            buckets["mistakes"].append((w, m))
        elif _is_preference(m):
            buckets["preferences"].append((w, m))
        elif _is_tooling(m):
            buckets["tooling"].append((w, m))
        else:
            buckets["patterns"].append((w, m))

    def _top(bucket: list[tuple[float, MemoryEntry]]) -> list[tuple[str, str]]:
        return [(m.title, m.summary) for _, m in bucket[:max_items]]

    # Salient IDs = top-weighted overall, bounded to max_items.
    salient_ids = [m.id for _, m in weighted[:max_items]]

    return UserProfile(
        preferences=_top(buckets["preferences"]),
        patterns=_top(buckets["patterns"]),
        frequent_mistakes=_top(buckets["mistakes"]),
        tooling=_top(buckets["tooling"]),
        salient_memory_ids=salient_ids,
        derived_from=len(contributed_ids),
    )
