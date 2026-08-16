"""Evidence-weighted skill routing — load skills by measured lift, not vibes.

Plain query→skill matching is a commodity (any embedding does it). What no
skill marketplace has is the *earned* half: routing weighted by each skill's
measured lift on this repo's own benchmark (:mod:`.attribution`), with one
hard rule — a skill the ledger measured as HARMFUL is never loaded, no matter
how relevant it looks. Relevance proposes; evidence disposes.

Pure over inputs: the caller supplies the skill texts and the ledger; the
router returns what to load. No I/O, no LLM calls.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.learning.attribution import LiftVerdict, MemoryLift
from oh_no_my_claudecode.retrieval.bm25 import BM25Corpus

#: Score multiplier reserved for skills with EARNING evidence; unproven skills
#: keep neutral weight rather than being punished for lacking data yet.
_EARNING_BONUS = 1.0


@dataclass(frozen=True, slots=True)
class RoutedSkill:
    """One skill the router selected, with the reasoning made auditable."""

    skill_id: str
    relevance: float
    measured_lift: float | None
    verdict: LiftVerdict | None
    score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "skill_id": self.skill_id,
            "relevance": round(self.relevance, 4),
            "measured_lift": self.measured_lift,
            "verdict": self.verdict.value if self.verdict else None,
            "score": round(self.score, 4),
        }


def route_skills(
    query: str,
    skills: Mapping[str, str],
    ledger: Sequence[MemoryLift] = (),
    *,
    top_k: int = 2,
) -> list[RoutedSkill]:
    """Rank skills for *query*: BM25 relevance × (1 + earned lift).

    ``skills`` maps skill_id -> description/body text. Ledger entries are the
    attribution output for those same ids (missing = unproven). HARMFUL skills
    are excluded outright — measured poison never rides back in on relevance.
    """
    if not query.strip() or not skills or top_k <= 0:
        return []
    by_id = {entry.memory_id: entry for entry in ledger}
    ids = sorted(skills)
    corpus = BM25Corpus(ids, [skills[i] for i in ids])

    routed: list[RoutedSkill] = []
    for skill_id, relevance in corpus.retrieve(query, k=len(ids)):
        entry = by_id.get(skill_id)
        if entry is not None and entry.verdict is LiftVerdict.HARMFUL:
            continue  # hard rule: never load measured poison
        lift = entry.mean_lift if entry is not None else None
        earning = entry is not None and entry.verdict is LiftVerdict.EARNING
        multiplier = 1.0 + (_EARNING_BONUS * max(0.0, lift or 0.0) if earning else 0.0)
        routed.append(
            RoutedSkill(
                skill_id=skill_id,
                relevance=relevance,
                measured_lift=lift,
                verdict=entry.verdict if entry else None,
                score=relevance * multiplier,
            )
        )
    routed.sort(key=lambda r: (-r.score, r.skill_id))
    return routed[:top_k]


def load_for_query(
    query: str,
    skills: Mapping[str, str],
    ledger: Sequence[MemoryLift] = (),
    *,
    top_k: int = 2,
) -> str:
    """Return the pre-work context block: the routed skills' bodies, labeled.

    Each loaded skill is annotated with its evidence so the agent (and any
    later audit) can see *why* it was loaded — measured lift or "unproven".
    """
    routed = route_skills(query, skills, ledger, top_k=top_k)
    if not routed:
        return ""
    blocks: list[str] = []
    for r in routed:
        evidence = (
            f"measured lift {r.measured_lift:+.2f} on this repo's benchmark"
            if r.verdict is LiftVerdict.EARNING
            else "unproven (no measured lift yet)"
        )
        blocks.append(
            f"<skill id={r.skill_id!r} evidence={evidence!r}>\n{skills[r.skill_id]}\n</skill>"
        )
    return "\n\n".join(blocks)


__all__ = ["RoutedSkill", "load_for_query", "route_skills"]
