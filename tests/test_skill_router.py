"""Skill router: evidence outranks relevance, poison never loads."""

from __future__ import annotations

from oh_no_my_claudecode.learning.attribution import LiftVerdict, MemoryLift
from oh_no_my_claudecode.learning.skill_router import load_for_query, route_skills

SKILLS = {
    "sql-migrations": "Writing safe SQL schema migrations: locks, backfill, rollback plans.",
    "sql-injection-bad": "SQL query helpers and migration shortcuts for schema changes.",
    "frontend-css": "Centering divs and responsive flexbox layout patterns.",
}


def _lift(mid: str, mean: float, lo: float, hi: float, verdict: LiftVerdict) -> MemoryLift:
    return MemoryLift(memory_id=mid, mean_lift=mean, ci95=(lo, hi), n_tasks=10, verdict=verdict)


LEDGER = [
    _lift("sql-migrations", 0.30, 0.10, 0.50, LiftVerdict.EARNING),
    _lift("sql-injection-bad", -0.20, -0.40, -0.05, LiftVerdict.HARMFUL),
]


def test_harmful_skill_never_loads_even_when_most_relevant() -> None:
    routed = route_skills("sql migration schema change", SKILLS, LEDGER, top_k=3)
    ids = [r.skill_id for r in routed]
    assert "sql-injection-bad" not in ids  # measured poison excluded outright
    assert ids[0] == "sql-migrations"  # earning skill wins


def test_earning_lift_boosts_score_and_is_auditable() -> None:
    routed = route_skills("sql migration schema change", SKILLS, LEDGER, top_k=1)
    top = routed[0]
    assert top.verdict is LiftVerdict.EARNING
    assert top.score > top.relevance  # evidence multiplied relevance

    block = load_for_query("sql migration schema change", SKILLS, LEDGER, top_k=1)
    assert "sql-migrations" in block
    assert "measured lift +0.30" in block  # the why is in the loaded context


def test_irrelevant_query_loads_nothing_relevant() -> None:
    routed = route_skills("kubernetes ingress timeout", SKILLS, LEDGER, top_k=2)
    assert all(r.skill_id != "sql-injection-bad" for r in routed)
    assert load_for_query("", SKILLS, LEDGER) == ""
