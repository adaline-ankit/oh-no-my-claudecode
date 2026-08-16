"""Outcome-driven context eviction — paging where importance is measured.

MemGPT made the context window an OS problem (RAM + paging); Generative
Agents scored memories recency × importance × relevance — with importance
*guessed by an LLM*. This module replaces the guess with the ledger: the
importance term is measured lift, so the eviction order is an evidence
ranking, not an opinion.

Order out the door:
1. HARMFUL (should never have been resident; evict on sight)
2. lowest score first, where score = recency × relevance × (1 + max(lift, 0))
3. protected items (load-bearing constraints, R1 set) are UNEVICTABLE —
   if the token target can't be met without them, the plan reports the
   shortfall instead of quietly paging out a policy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.learning.attribution import LiftVerdict, MemoryLift


@dataclass(frozen=True, slots=True)
class ResidentItem:
    """One item currently occupying context."""

    item_id: str
    tokens: int
    recency: float = 1.0  # 0..1, newer = higher
    relevance: float = 1.0  # 0..1, from recall scoring
    protected: bool = False  # R1 constraint set — never evictable


@dataclass(frozen=True, slots=True)
class EvictionPlan:
    """What to page out, in order, and whether the target was actually met."""

    evict: tuple[str, ...]
    freed_tokens: int
    shortfall_tokens: int  # >0 means the target is unreachable without protected items

    def to_dict(self) -> dict[str, object]:
        return {
            "evict": list(self.evict),
            "freed_tokens": self.freed_tokens,
            "shortfall_tokens": self.shortfall_tokens,
        }


def plan_eviction(
    items: Sequence[ResidentItem],
    ledger: Sequence[MemoryLift],
    *,
    tokens_to_free: int,
) -> EvictionPlan:
    """Rank residents for eviction until the token target is met.

    Deterministic: ties break on item_id. Items absent from the ledger score
    with lift 0 (unproven earns no protection, costs no penalty).
    """
    if tokens_to_free < 0:
        raise ValueError("tokens_to_free must be non-negative")
    lift_by_id: Mapping[str, MemoryLift] = {entry.memory_id: entry for entry in ledger}

    def _harmful(item: ResidentItem) -> bool:
        entry = lift_by_id.get(item.item_id)
        return entry is not None and entry.verdict is LiftVerdict.HARMFUL

    def _score(item: ResidentItem) -> float:
        entry = lift_by_id.get(item.item_id)
        lift = max(entry.mean_lift, 0.0) if entry else 0.0
        return item.recency * item.relevance * (1.0 + lift)

    evictable = [i for i in items if not i.protected]
    ordered = sorted(
        evictable,
        key=lambda i: (not _harmful(i), _score(i), i.item_id),
    )

    evict: list[str] = []
    freed = 0
    for item in ordered:
        if freed >= tokens_to_free and not _harmful(item):
            break  # target met; only harmful items are evicted beyond need
        evict.append(item.item_id)
        freed += item.tokens

    return EvictionPlan(
        evict=tuple(evict),
        freed_tokens=freed,
        shortfall_tokens=max(0, tokens_to_free - freed),
    )


__all__ = ["EvictionPlan", "ResidentItem", "plan_eviction"]
