"""Pure, testable nightshift planning — bounded overnight swarm units.

``nightshift`` answers one operational question: *given a backlog of goals and a
budget, exactly which swarm units would run overnight, and — the morning after —
which of them actually verified?*  It is the accountability spine of an
unattended overnight run.

This module is **pure and offline**.  It never spawns an agent and never touches
the swarm state directory — mirroring the plan-mode safety of
:func:`oh_no_my_claudecode.mission.pipeline.plan_mission`.  The one place a real
inline swarm gets materialised is left to the caller (the model driving the
fan-out from the emitted plan); ``nightshift`` only *plans* and later
*summarises receipts*.

Determinism
-----------
``plan_nightshift`` is a pure function of ``(goals, budget)``: it de-duplicates
and orders goals deterministically (stable input order, dupes dropped), then
truncates to the budget cap.  Two calls with the same inputs produce byte-
identical plans.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Default cap on how many units a single nightshift run will schedule.  Keeps an
# unattended overnight run bounded regardless of how large the backlog is.
DEFAULT_BUDGET = 5


@dataclass(frozen=True, slots=True)
class NightshiftUnit:
    """One planned swarm unit: an ordinal slot plus its goal.

    ``index`` is the deterministic 0-based position of this unit in the plan
    (its execution order); ``goal`` is the stripped backlog goal it carries.
    """

    index: int
    goal: str

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {"index": self.index, "goal": self.goal}


@dataclass(frozen=True, slots=True)
class NightshiftPlan:
    """The bounded set of swarm units a nightshift run *would* schedule.

    Attributes
    ----------
    units:
        The deterministically-ordered, budget-capped units to run.
    budget:
        The unit cap applied (``len(units) <= budget``).
    total_goals:
        Count of distinct, non-empty goals in the backlog *before* the budget
        cap — so the plan can honestly report how many were deferred.
    """

    units: list[NightshiftUnit] = field(default_factory=list)
    budget: int = DEFAULT_BUDGET
    total_goals: int = 0

    @property
    def is_empty(self) -> bool:
        """True when the backlog produced no schedulable units."""
        return not self.units

    @property
    def scheduled_count(self) -> int:
        """Number of units this plan will schedule (after the budget cap)."""
        return len(self.units)

    @property
    def deferred_count(self) -> int:
        """Goals that did not fit under the budget cap (never negative)."""
        return max(0, self.total_goals - len(self.units))

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict for the ``--json`` CLI surface."""
        return {
            "budget": self.budget,
            "total_goals": self.total_goals,
            "scheduled_count": self.scheduled_count,
            "deferred_count": self.deferred_count,
            "units": [u.to_dict() for u in self.units],
        }


def _clean_goals(goals: list[str]) -> list[str]:
    """Strip, drop empties, and de-duplicate while preserving first-seen order.

    De-duplication is deterministic: the first occurrence of a goal wins and
    later duplicates are dropped, so the ordering is a stable function of the
    input.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in goals:
        goal = raw.strip()
        if not goal or goal in seen:
            continue
        seen.add(goal)
        cleaned.append(goal)
    return cleaned


def plan_nightshift(goals: list[str], *, budget: int = DEFAULT_BUDGET) -> NightshiftPlan:
    """Plan a bounded overnight swarm from *goals*, honouring the *budget* cap.

    Pure, deterministic, and offline — spawns nothing and touches no state
    directory (plan-mode safety, mirroring
    :func:`oh_no_my_claudecode.mission.pipeline.plan_mission`).

    The backlog is cleaned (stripped, empties dropped, de-duplicated preserving
    first-seen order) and then truncated to at most ``budget`` units.  When the
    backlog is empty the result is an empty-but-valid plan (no crash).

    Parameters
    ----------
    goals:
        Backlog of goal strings.  Blank and duplicate goals are ignored.
    budget:
        Maximum number of units to schedule.  A budget ``<= 0`` schedules
        nothing (an explicit "plan but run nothing" request).

    Returns
    -------
    NightshiftPlan
        The deterministic, budget-capped plan.
    """
    cleaned = _clean_goals(goals)
    cap = max(0, budget)
    scheduled = cleaned[:cap]
    units = [NightshiftUnit(index=i, goal=g) for i, g in enumerate(scheduled)]
    return NightshiftPlan(units=units, budget=budget, total_goals=len(cleaned))


@dataclass(frozen=True, slots=True)
class NightshiftSummary:
    """Morning summary of a completed nightshift run, from collected receipts.

    Attributes
    ----------
    verified:
        Units whose receipt asserted ``verified=True`` (real, gated wins).
    failed:
        Units that ran but did not verify.
    total:
        Total receipts collected.
    results:
        The normalised per-unit rows (goal, verified, pr_url) in input order —
        the raw material the morning digest renders.
    """

    verified: int = 0
    failed: int = 0
    total: int = 0
    results: list[dict[str, object]] = field(default_factory=list)

    @property
    def all_verified(self) -> bool:
        """True when every collected receipt verified (and there was at least one)."""
        return self.total > 0 and self.failed == 0

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "verified": self.verified,
            "failed": self.failed,
            "total": self.total,
            "results": list(self.results),
        }


def summarize_receipts(receipts: list[dict[str, object]]) -> NightshiftSummary:
    """Summarise collected swarm receipts into verified-vs-failed counts.

    Each receipt is a loose dict as produced by
    :func:`oh_no_my_claudecode.swarm.inline.record_inline_unit` (or a manifest
    unit entry): it may carry ``verified`` (bool), ``goal`` (str) and a PR link
    under either ``pr_url`` or ``pr`` .  Missing keys degrade gracefully — an
    absent/falsey ``verified`` counts as failed, an absent goal renders as
    ``"(unknown)"``.

    Returns
    -------
    NightshiftSummary
        Counts plus a normalised, input-ordered row per receipt.
    """
    verified = 0
    failed = 0
    rows: list[dict[str, object]] = []
    for receipt in receipts:
        is_verified = bool(receipt.get("verified"))
        if is_verified:
            verified += 1
        else:
            failed += 1
        goal = str(receipt.get("goal") or "(unknown)")
        pr_url = receipt.get("pr_url") or receipt.get("pr")
        rows.append(
            {
                "goal": goal,
                "verified": is_verified,
                "pr_url": str(pr_url) if pr_url else None,
            }
        )
    return NightshiftSummary(
        verified=verified,
        failed=failed,
        total=len(receipts),
        results=rows,
    )
