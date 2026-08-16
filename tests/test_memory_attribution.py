"""Memory P&L: a helpful memory earns, poison is caught, inert stays unproven."""

from __future__ import annotations

from oh_no_my_claudecode.learning.attribution import (
    LiftVerdict,
    attribute_memories,
    retirement_candidates,
)

TASKS = [f"t{i}" for i in range(10)]


def _runner(task: str, memories: frozenset[str]) -> bool:
    # Ground truth: "good" makes every task pass; "poison" breaks t0-t4 even
    # when good is present; "inert" changes nothing.
    if "poison" in memories and task in {"t0", "t1", "t2", "t3", "t4"}:
        return False
    return "good" in memories


def test_ledger_separates_earning_poison_and_inert() -> None:
    ledger = attribute_memories(["good", "poison", "inert"], TASKS, _runner, seed=7)
    by_id = {entry.memory_id: entry for entry in ledger}

    assert by_id["good"].verdict is LiftVerdict.EARNING
    assert by_id["good"].mean_lift > 0
    assert by_id["poison"].verdict is LiftVerdict.HARMFUL
    assert by_id["poison"].mean_lift < 0
    assert by_id["inert"].verdict is LiftVerdict.UNPROVEN
    assert by_id["inert"].mean_lift == 0.0

    # Sorted best-first; retirement is evidence-driven and hits only poison.
    assert ledger[0].memory_id == "good"
    assert retirement_candidates(ledger) == ("poison",)

    # Deterministic: same seed, same runner -> identical ledger.
    assert attribute_memories(["good", "poison", "inert"], TASKS, _runner, seed=7) == ledger
