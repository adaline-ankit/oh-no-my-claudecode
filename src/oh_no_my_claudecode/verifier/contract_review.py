"""Independent semantic task-contract review over verifier evidence.

The proof graph proves that *some* set of verifiers passed. This module asks the
orthogonal, semantic question: does the passing evidence actually satisfy the
**task's stated contract** — the behaviours it must add, the invariants it must
preserve, and the regressions it must not introduce?

Crucially it is independent of the agent's self-report. It reuses
:class:`oh_no_my_claudecode.proof_graph.models.EvidenceSource` and counts
:attr:`EvidenceSource.VERIFIER` evidence only; an
:attr:`EvidenceSource.AGENT` assertion is recorded as *non-authoritative* and
can never satisfy a requirement. This is the same trust boundary
:func:`oh_no_my_claudecode.proof_graph.evaluator.evaluate_proof` enforces — this
module builds on that rule rather than re-deriving false-green detection.

Pure and deterministic: no I/O, evaluated entirely over the injected contract
and evidence tuples.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from oh_no_my_claudecode.proof_graph.models import Evidence, EvidenceSource, Outcome


class ContractVerdict(StrEnum):
    """The three verdicts an independent contract review can reach."""

    SATISFIED = "satisfied"
    VIOLATED = "violated"
    INSUFFICIENT_EVIDENCE = "insufficient-evidence"


@dataclass(frozen=True, slots=True)
class BehaviorRequirement:
    """A behaviour the change must add, backed by one or more claims.

    The requirement is satisfied only when every ``claim_id`` carries at least
    one passing verifier evidence.
    """

    requirement_id: str
    description: str
    claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.claim_ids:
            raise ValueError(f"behavior {self.requirement_id} names no claims to verify")


@dataclass(frozen=True, slots=True)
class Invariant:
    """A property the change must preserve, backed by one or more claims.

    Treated like a behaviour for satisfaction, but a *failing* verifier on one
    of its claims is a demonstrated breakage (a contract violation, not merely
    insufficient evidence).
    """

    invariant_id: str
    description: str
    claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.claim_ids:
            raise ValueError(f"invariant {self.invariant_id} names no claims to verify")


@dataclass(frozen=True, slots=True)
class ForbiddenRegression:
    """A regression the change must not introduce.

    Triggered (contract violated) when any ``guard_claim_id`` carries verifier
    evidence with a failing/errored outcome — i.e. a regression was actually
    demonstrated.
    """

    regression_id: str
    description: str
    guard_claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.guard_claim_ids:
            raise ValueError(f"regression {self.regression_id} names no guard claims")


@dataclass(frozen=True, slots=True)
class TaskContract:
    """The full semantic contract a change is independently reviewed against."""

    contract_id: str
    required_behaviors: tuple[BehaviorRequirement, ...] = ()
    preserved_invariants: tuple[Invariant, ...] = ()
    forbidden_regressions: tuple[ForbiddenRegression, ...] = ()

    def __post_init__(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("TaskContract.contract_id must not be empty")


@dataclass(frozen=True, slots=True)
class ContractReview:
    """Typed verdict of an independent contract review."""

    verdict: ContractVerdict
    reasons: tuple[str, ...]
    unmet_behaviors: tuple[str, ...]
    unmet_invariants: tuple[str, ...]
    broken_invariants: tuple[str, ...]
    triggered_regressions: tuple[str, ...]
    agent_only_claims: tuple[str, ...]

    @property
    def satisfied(self) -> bool:
        """``True`` only for a fully verified, unviolated contract."""
        return self.verdict is ContractVerdict.SATISFIED


@dataclass(frozen=True, slots=True)
class _ClaimEvidence:
    """Per-claim tally of verifier vs. agent evidence, split by outcome."""

    verifier_passed: bool
    verifier_failed: bool
    agent_only: bool


def _index_evidence(evidence: Sequence[Evidence]) -> dict[str, _ClaimEvidence]:
    """Reduce raw evidence to a per-claim tally, ignoring agent authority."""
    passed: set[str] = set()
    failed: set[str] = set()
    agent: set[str] = set()
    for item in evidence:
        for claim_id in item.claim_ids:
            if item.source is EvidenceSource.AGENT:
                agent.add(claim_id)
                continue
            if item.outcome is Outcome.PASSED:
                passed.add(claim_id)
            elif item.outcome in (Outcome.FAILED, Outcome.ERROR):
                failed.add(claim_id)
    claim_ids = passed | failed | agent
    return {
        claim_id: _ClaimEvidence(
            verifier_passed=claim_id in passed,
            verifier_failed=claim_id in failed,
            agent_only=claim_id in agent and claim_id not in passed and claim_id not in failed,
        )
        for claim_id in claim_ids
    }


def review_contract(
    contract: TaskContract,
    evidence: Sequence[Evidence],
) -> ContractReview:
    """Independently review *contract* against verifier *evidence*.

    Pure and deterministic. Agent-sourced evidence is treated as
    non-authoritative: it can never satisfy a behaviour or invariant, and a
    claim backed only by agent prose is surfaced in ``agent_only_claims`` and
    counted as unmet. Verdict precedence is ``VIOLATED`` (a demonstrated
    regression or broken invariant) over ``INSUFFICIENT_EVIDENCE`` (a
    requirement lacking passing verifier evidence) over ``SATISFIED``.
    """
    tally = _index_evidence(evidence)
    reasons: list[str] = []
    unmet_behaviors: list[str] = []
    unmet_invariants: list[str] = []
    broken_invariants: list[str] = []
    triggered_regressions: list[str] = []
    agent_only: list[str] = []

    def _passing(claim_id: str) -> bool:
        record = tally.get(claim_id)
        return record is not None and record.verifier_passed

    def _note_agent_only(claim_ids: tuple[str, ...]) -> None:
        for claim_id in claim_ids:
            record = tally.get(claim_id)
            if record is not None and record.agent_only and claim_id not in agent_only:
                agent_only.append(claim_id)

    for behavior in contract.required_behaviors:
        _note_agent_only(behavior.claim_ids)
        missing = [claim_id for claim_id in behavior.claim_ids if not _passing(claim_id)]
        if missing:
            unmet_behaviors.append(behavior.requirement_id)
            reasons.append(
                f"required behavior {behavior.requirement_id!r} lacks passing "
                f"verifier evidence for claim(s): {', '.join(sorted(missing))}"
            )

    for invariant in contract.preserved_invariants:
        _note_agent_only(invariant.claim_ids)
        broken = [
            claim_id
            for claim_id in invariant.claim_ids
            if (record := tally.get(claim_id)) is not None and record.verifier_failed
        ]
        if broken:
            broken_invariants.append(invariant.invariant_id)
            reasons.append(
                f"preserved invariant {invariant.invariant_id!r} is demonstrably broken "
                f"(failing verifier) on claim(s): {', '.join(sorted(broken))}"
            )
            continue
        missing = [claim_id for claim_id in invariant.claim_ids if not _passing(claim_id)]
        if missing:
            unmet_invariants.append(invariant.invariant_id)
            reasons.append(
                f"preserved invariant {invariant.invariant_id!r} lacks passing "
                f"verifier evidence for claim(s): {', '.join(sorted(missing))}"
            )

    for regression in contract.forbidden_regressions:
        fired = [
            claim_id
            for claim_id in regression.guard_claim_ids
            if (record := tally.get(claim_id)) is not None and record.verifier_failed
        ]
        if fired:
            triggered_regressions.append(regression.regression_id)
            reasons.append(
                f"forbidden regression {regression.regression_id!r} was demonstrated "
                f"(failing verifier) on guard claim(s): {', '.join(sorted(fired))}"
            )

    if agent_only:
        reasons.append(
            "agent-only (non-authoritative) evidence cannot satisfy a contract; "
            f"claim(s) backed solely by agent self-report: {', '.join(sorted(agent_only))}"
        )

    if triggered_regressions or broken_invariants:
        verdict = ContractVerdict.VIOLATED
    elif unmet_behaviors or unmet_invariants:
        verdict = ContractVerdict.INSUFFICIENT_EVIDENCE
    else:
        verdict = ContractVerdict.SATISFIED

    return ContractReview(
        verdict=verdict,
        reasons=tuple(dict.fromkeys(reasons)),
        unmet_behaviors=tuple(unmet_behaviors),
        unmet_invariants=tuple(unmet_invariants),
        broken_invariants=tuple(broken_invariants),
        triggered_regressions=tuple(triggered_regressions),
        agent_only_claims=tuple(sorted(agent_only)),
    )
