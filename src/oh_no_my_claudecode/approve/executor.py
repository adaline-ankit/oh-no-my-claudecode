"""Approval executor — turn a parsed chat action into a real merge decision.

This is the piece that CLOSES the phone-to-merge loop.  The mission bridge only
*parses* an approval ("approve unit 2" / "approve all" / a button callback) into
an :class:`~oh_no_my_claudecode.missionbridge.models.ApproveAction`; this module
decides which units that approval is *allowed* to act on and then performs the
merge.

Two layers, cleanly split:

Pure decision core (:func:`plan_approval`)
    Given the mission trust card + a parsed action, decides which unit ids are
    ELIGIBLE to merge and which are REFUSED (with a reason).  100% pure and
    deterministic: no I/O, no clock, no randomness — this is what the tests
    hammer.

Thin side-effecting executor (:func:`execute_plan`)
    Walks the plan's eligible units and calls an injectable ``merger``.  Refused
    units are reported, never merged.  Defaults to a DRY merger that records
    intent and does nothing, so the executor is read-only-safe unless a real
    merger is injected AND ``dry_run`` is turned off.

Safety invariant (the whole point of onmc = accountability)
    A unit is eligible to merge ONLY when it is a *verified success* — the
    manifest marks it verified AND a tamper-evident receipt backs it up (exactly
    the :class:`~oh_no_my_claudecode.missionbridge.models.UnitLine` ``verified``
    signal, with ``held`` its negation).  A held / unverified / receipt-less /
    aborted unit is NEVER eligible.  This mirrors ``onmc swarm pr``'s
    "refuses unverified" rule.  Merging is destructive and outward-facing, so
    the default is a dry plan; real execution requires an explicit opt-in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.missionbridge.models import (
    ApproveAction,
    ApproveKind,
    MissionCard,
    UnitLine,
)

# ---------------------------------------------------------------------------
# Refusal reasons (stable strings — a gateway / automation branches on these)
# ---------------------------------------------------------------------------

#: Unit id not present in the mission card.
REASON_NOT_FOUND = "not-found"

#: Unit is not verified and carries no tamper-evident receipt.
REASON_UNVERIFIED = "unverified"

#: Unit is held (present + receipt, but the manifest did not verify it).
REASON_HELD = "held"

#: Unit's run was aborted — never a verified success.
REASON_ABORTED = "aborted"


# ---------------------------------------------------------------------------
# Result dataclasses (frozen — a plan/result never mutates after creation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalPlan:
    """The decision of :func:`plan_approval` — pure, no side effects yet.

    Attributes
    ----------
    kind:
        The :class:`ApproveKind` the plan was built from (merge-all / merge-one
        / show-diff / abort / unknown).
    eligible:
        Unit ids cleared to merge — verified successes only, in card order.
    refused:
        ``(unit_id, reason)`` pairs for every unit the action touched that is
        NOT a verified success.  A refused unit is never merged.
    note:
        A short human-readable summary of the overall intent.
    """

    kind: ApproveKind
    eligible: list[str] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    note: str = ""


@dataclass(frozen=True)
class MergeOutcome:
    """The result of attempting to merge a single eligible unit."""

    unit_id: str
    ok: bool
    detail: str
    pr_url: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    """The result of :func:`execute_plan`.

    Attributes
    ----------
    merged:
        One :class:`MergeOutcome` per eligible unit.  In a dry run each records
        intent (``ok=True``, "would merge") without any action having happened.
    skipped:
        The plan's refused ``(unit_id, reason)`` pairs — reported, never merged.
    dry_run:
        ``True`` when no real merger was invoked (plan-only).
    """

    merged: list[MergeOutcome] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    dry_run: bool = True


# ---------------------------------------------------------------------------
# A merger is any callable that performs the real, outward-facing action for one
# unit.  It is injected so the pure/thin split stays testable: tests pass a fake
# that records calls; production passes one that wraps swarm's open-PR and land's
# merge helpers.  Signature: (repo_root, swarm_id, unit_id) -> MergeOutcome.
# ---------------------------------------------------------------------------

Merger = Callable[[Path, str, str], MergeOutcome]


# ---------------------------------------------------------------------------
# Pure decision core
# ---------------------------------------------------------------------------


def _is_eligible(unit: UnitLine) -> bool:
    """A unit may merge ONLY when it is a verified success (and not held).

    This is the single trust gate.  It intentionally mirrors ``onmc swarm pr``:
    an un-gated / held / unverified change can never reach a merge.
    """
    return unit.verified and not unit.held


def _refusal_reason(unit: UnitLine) -> str:
    """Classify *why* a non-eligible unit is refused (for honest reporting).

    Only ever called on units that failed :func:`_is_eligible`.
    """
    if unit.status == "aborted":
        return REASON_ABORTED
    # No tamper-evident receipt backing the unit -> unverified.
    if unit.receipt_hash is None:
        return REASON_UNVERIFIED
    return REASON_HELD


def plan_approval(card: MissionCard, action: ApproveAction) -> ApprovalPlan:
    """Decide which units an *action* is allowed to merge against a *card*.

    Pure and deterministic: the same card + action always yields the same plan.
    Units keep the card's order so the plan is stable.

    - ``APPROVE_ALL`` → every verified unit eligible; every other unit refused
      with its reason.
    - ``APPROVE_UNIT`` → the target if it is a verified success, else refused
      (``not-found`` when the id is unknown).
    - ``SHOW_DIFF`` / ``ABORT`` / ``UNKNOWN`` → no merges; an explanatory note.
    """
    kind = action.kind

    if kind is ApproveKind.ABORT:
        return ApprovalPlan(kind, note="abort requested — no units will be merged")

    if kind is ApproveKind.SHOW_DIFF:
        target = action.unit_id or "?"
        return ApprovalPlan(kind, note=f"show-diff requested for {target} — no merge")

    if kind is ApproveKind.UNKNOWN:
        return ApprovalPlan(kind, note="unrecognised action — no units will be merged")

    if kind is ApproveKind.APPROVE_UNIT:
        target = action.unit_id or ""
        unit = next((u for u in card.units if u.unit_id == target), None)
        if unit is None:
            return ApprovalPlan(
                kind,
                refused=[(target or "?", REASON_NOT_FOUND)],
                note=f"{target or 'unit'} is not in mission {card.mission_id}",
            )
        if _is_eligible(unit):
            return ApprovalPlan(
                kind,
                eligible=[unit.unit_id],
                note=f"{unit.unit_id} is a verified success — cleared to merge",
            )
        reason = _refusal_reason(unit)
        return ApprovalPlan(
            kind,
            refused=[(unit.unit_id, reason)],
            note=f"{unit.unit_id} refused ({reason}) — not a verified success",
        )

    # APPROVE_ALL (the only remaining kind).
    eligible: list[str] = []
    refused: list[tuple[str, str]] = []
    for unit in card.units:
        if _is_eligible(unit):
            eligible.append(unit.unit_id)
        else:
            refused.append((unit.unit_id, _refusal_reason(unit)))
    note = (
        f"{len(eligible)} verified unit(s) cleared to merge, "
        f"{len(refused)} refused in mission {card.mission_id}"
    )
    return ApprovalPlan(ApproveKind.APPROVE_ALL, eligible=eligible, refused=refused, note=note)


# ---------------------------------------------------------------------------
# Thin side-effecting executor
# ---------------------------------------------------------------------------


def _dry_merger(repo_root: Path, swarm_id: str, unit_id: str) -> MergeOutcome:
    """The default merger: records intent, performs NO outward-facing action."""
    return MergeOutcome(
        unit_id=unit_id,
        ok=True,
        detail="dry-run: would merge (no action taken)",
    )


def execute_plan(
    repo_root: Path,
    swarm_id: str,
    plan: ApprovalPlan,
    *,
    merger: Merger | None = None,
    dry_run: bool = True,
) -> ExecutionResult:
    """Execute an :class:`ApprovalPlan`, merging only its eligible units.

    Parameters
    ----------
    repo_root, swarm_id:
        Context handed to the merger so it can resolve live state.
    plan:
        The pure plan from :func:`plan_approval`.
    merger:
        Injectable ``(repo_root, swarm_id, unit_id) -> MergeOutcome`` callable.
        Defaults to :func:`_dry_merger`.  Refused units are never passed to it.
    dry_run:
        When ``True`` (the default) the merger is NEVER called — each eligible
        unit is recorded as intent only.  When ``False`` the merger is invoked
        exactly once per eligible unit.

    Returns
    -------
    ExecutionResult
        ``merged`` carries one outcome per eligible unit; ``skipped`` carries the
        plan's refused pairs verbatim; ``dry_run`` echoes the mode.
    """
    active_merger = merger if merger is not None else _dry_merger
    merged: list[MergeOutcome] = []
    for unit_id in plan.eligible:
        if dry_run:
            merged.append(_dry_merger(repo_root, swarm_id, unit_id))
        else:
            merged.append(active_merger(repo_root, swarm_id, unit_id))
    return ExecutionResult(merged=merged, skipped=list(plan.refused), dry_run=dry_run)
