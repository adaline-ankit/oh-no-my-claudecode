"""Named context-budget presets for the execution harness.

Three modes trade context breadth against token cost:

* ``tiny``     — minimal, utility-first packing for cheap/fast planning.
* ``standard`` — the default balanced profile.
* ``deep``     — wide recall for hard tasks.

Each profile pins the token budget, the retriever's ``top_k`` and fusion
``mode``, the packer strategy, and the planner quality gates. Retrieval mode
is **BM25-first for code** in ``tiny``/``standard`` (offline eval showed lexical
BM25 beats hybrid on code retrieval); ``deep`` opts into hybrid fusion for
maximal recall. The benchmark report (``onmc retrieval-eval``) quantifies the
wins/losses so the default can be revisited with evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BudgetMode(StrEnum):
    """Named context-sizing presets."""

    TINY = "tiny"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass(frozen=True, slots=True)
class BudgetProfile:
    """Resolved knobs for one budget mode.

    Fields
    ------
    mode:
        The originating :class:`BudgetMode`.
    token_budget:
        Authoritative context-packet token ceiling.
    top_k:
        Maximum ranked files the retriever surfaces as candidates.
    retrieval_mode:
        Fusion mode passed to the hybrid retriever: ``"bm25"`` (lexical-only,
        BM25-first for code), ``"dense"``, or ``"hybrid"``.
    utility_first:
        When true the packer greedily selects by marginal utility (ROI /
        tokens); otherwise by absolute relevance score.
    min_confidence:
        Confidence floor below which a packed result is flagged low-confidence.
    min_context_roi:
        ROI gate below which a candidate is excluded.
    min_freshness:
        Freshness floor below which a candidate is excluded as stale.
    """

    mode: BudgetMode
    token_budget: int
    top_k: int
    retrieval_mode: str
    utility_first: bool
    min_confidence: float
    min_context_roi: float
    min_freshness: float


_PROFILES: dict[BudgetMode, BudgetProfile] = {
    BudgetMode.TINY: BudgetProfile(
        mode=BudgetMode.TINY,
        token_budget=1_500,
        top_k=8,
        retrieval_mode="bm25",
        utility_first=True,
        min_confidence=0.05,
        min_context_roi=0.001,
        min_freshness=0.2,
    ),
    BudgetMode.STANDARD: BudgetProfile(
        mode=BudgetMode.STANDARD,
        token_budget=4_000,
        top_k=20,
        retrieval_mode="bm25",
        utility_first=False,
        min_confidence=0.0,
        min_context_roi=0.00025,
        min_freshness=0.2,
    ),
    BudgetMode.DEEP: BudgetProfile(
        mode=BudgetMode.DEEP,
        token_budget=12_000,
        top_k=40,
        retrieval_mode="hybrid",
        utility_first=False,
        min_confidence=0.0,
        min_context_roi=0.0001,
        min_freshness=0.1,
    ),
}


def resolve_budget_profile(
    mode: BudgetMode | str,
    *,
    token_budget_override: int | None = None,
) -> BudgetProfile:
    """Return the :class:`BudgetProfile` for *mode*.

    ``token_budget_override`` (when > 0) replaces the profile's token budget so
    an explicit ``--context-budget`` still wins over the preset.
    """
    resolved = BudgetMode(mode)
    profile = _PROFILES[resolved]
    if token_budget_override is not None and token_budget_override > 0:
        return BudgetProfile(
            mode=profile.mode,
            token_budget=token_budget_override,
            top_k=profile.top_k,
            retrieval_mode=profile.retrieval_mode,
            utility_first=profile.utility_first,
            min_confidence=profile.min_confidence,
            min_context_roi=profile.min_context_roi,
            min_freshness=profile.min_freshness,
        )
    return profile


__all__ = ["BudgetMode", "BudgetProfile", "resolve_budget_profile"]
