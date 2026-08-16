"""Eviction: harmful first, earning last, protected never, shortfalls honest."""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.context_engine.eviction import ResidentItem, plan_eviction
from oh_no_my_claudecode.learning.attribution import LiftVerdict, MemoryLift

LEDGER = [
    MemoryLift("poison", -0.3, (-0.5, -0.1), 10, LiftVerdict.HARMFUL),
    MemoryLift("earner", 0.5, (0.3, 0.7), 10, LiftVerdict.EARNING),
]

ITEMS = [
    ResidentItem("constitution", tokens=200, protected=True),
    ResidentItem("poison", tokens=300, recency=1.0, relevance=1.0),
    ResidentItem("earner", tokens=400, recency=0.5, relevance=0.5),
    ResidentItem("unproven", tokens=500, recency=0.5, relevance=0.5),
]


def test_harmful_evicts_first_earning_survives_longest() -> None:
    plan = plan_eviction(ITEMS, LEDGER, tokens_to_free=700)
    # poison goes first regardless of its high recency/relevance; then the
    # lower-scored unproven (same recency×relevance but no earned lift).
    assert plan.evict == ("poison", "unproven")
    assert plan.freed_tokens == 800 and plan.shortfall_tokens == 0
    assert "earner" not in plan.evict and "constitution" not in plan.evict


def test_harmful_evicted_even_when_no_tokens_needed() -> None:
    plan = plan_eviction(ITEMS, LEDGER, tokens_to_free=0)
    assert plan.evict == ("poison",)  # evict-on-sight, not on pressure


def test_protected_never_pages_out_and_shortfall_is_honest() -> None:
    plan = plan_eviction(ITEMS, LEDGER, tokens_to_free=10_000)
    assert "constitution" not in plan.evict
    assert plan.freed_tokens == 1200  # everything evictable
    assert plan.shortfall_tokens == 8800  # the truth, not a silent policy evict


def test_deterministic_and_validates_input() -> None:
    assert plan_eviction(ITEMS, LEDGER, tokens_to_free=700) == plan_eviction(
        ITEMS, LEDGER, tokens_to_free=700
    )
    with pytest.raises(ValueError):
        plan_eviction(ITEMS, LEDGER, tokens_to_free=-1)
