"""Typed, evidence-carrying outcomes for the six public harness stages.

Previously the intermediate DAG nodes (understand/retrieve/plan/claim and
verify/repair/prove/learn) were advanced by a bare state transition — they
recorded *that* a phase ran but nothing *about* it. These builders derive a
typed :class:`StageOutcome` from the real plan, context packet, loop result and
proof assessment, so every stage carries falsifiable content that flows into
the run receipt.

The ``learn-candidate`` stage deliberately emits a *candidate* only: durable
memory writes remain owned by ``memstage``. A run that did not prove complete
never produces a learn candidate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from oh_no_my_claudecode.context_engine import EvidencePacket
from oh_no_my_claudecode.harness import TaskDAG
from oh_no_my_claudecode.loop import LoopResult
from oh_no_my_claudecode.proof_graph import ProofAssessment


class HarnessStage(StrEnum):
    """The six public, typed stages of an ``onmc run``."""

    PREPARE = "prepare"
    CONTEXT = "context"
    EXECUTE = "execute"
    VERIFY = "verify"
    PROOF = "proof"
    LEARN_CANDIDATE = "learn-candidate"


class StageStatus(StrEnum):
    """Honest per-stage status."""

    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class LearnCandidate:
    """A proposed memory record — never auto-persisted, only surfaced."""

    title: str
    body: str
    evidence_digest: str

    def to_dict(self) -> dict[str, object]:
        return {"title": self.title, "body": self.body, "evidence_digest": self.evidence_digest}


@dataclass(frozen=True, slots=True)
class StageOutcome:
    """One typed stage result with a machine-readable detail map."""

    stage: HarnessStage
    status: StageStatus
    summary: str
    details: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "summary": self.summary,
            "details": self.details,
        }


def prepare_stage(dag: TaskDAG) -> StageOutcome:
    """Real preparation: the compiled DAG shape and risk headroom."""
    order = tuple(node.node_id for node in dag.topological_order())
    return StageOutcome(
        HarnessStage.PREPARE,
        StageStatus.OK,
        f"compiled {len(dag.nodes)} nodes at risk={dag.risk.value}",
        {"node_count": len(dag.nodes), "risk": dag.risk.value, "order": list(order)},
    )


def context_stage(packet: EvidencePacket) -> StageOutcome:
    """Real context: retrieved evidence and token accounting."""
    status = StageStatus.OK if packet.evidence else StageStatus.SKIPPED
    summary = (
        f"retrieved {len(packet.evidence)} evidence items "
        f"({packet.used_tokens}/{packet.token_budget} tokens)"
    )
    return StageOutcome(
        HarnessStage.CONTEXT,
        status,
        summary,
        {
            "evidence_count": len(packet.evidence),
            "used_tokens": packet.used_tokens,
            "token_budget": packet.token_budget,
        },
    )


def execute_stage(result: LoopResult) -> StageOutcome:
    """Real execution: the memory-grounded loop's convergence verdict."""
    status = StageStatus.OK if result.converged else StageStatus.FAILED
    return StageOutcome(
        HarnessStage.EXECUTE,
        status,
        f"loop {'converged' if result.converged else 'did not converge'}: {result.stop_reason}",
        {
            "converged": result.converged,
            "iterations": len(result.iterations),
            "stop_reason": result.stop_reason,
        },
    )


def verify_stage(result: LoopResult) -> StageOutcome:
    """Real verification: the final verifier outcome and its output digest."""
    if not result.iterations:
        return StageOutcome(
            HarnessStage.VERIFY,
            StageStatus.FAILED,
            "no verifier ran",
            {"verifier_ran": False},
        )
    final = result.iterations[-1]
    digest = hashlib.sha256(final.verify_output.encode("utf-8")).hexdigest()
    status = StageStatus.OK if final.verify_passed else StageStatus.FAILED
    return StageOutcome(
        HarnessStage.VERIFY,
        status,
        f"verifier {'passed' if final.verify_passed else 'failed'}",
        {"verifier_ran": True, "passed": final.verify_passed, "output_digest": digest},
    )


def proof_stage(assessment: ProofAssessment, receipt_hash: str) -> StageOutcome:
    """Real proof: the false-green-aware assessment and its receipt hash."""
    status = StageStatus.OK if assessment.complete else StageStatus.FAILED
    return StageOutcome(
        HarnessStage.PROOF,
        status,
        "proof complete" if assessment.complete else "proof incomplete",
        {
            "complete": assessment.complete,
            "false_green": assessment.false_green,
            "reasons": list(assessment.reasons),
            "receipt_hash": receipt_hash,
        },
    )


def learn_candidate_stage(
    dag: TaskDAG,
    result: LoopResult,
    *,
    proof_complete: bool,
) -> StageOutcome:
    """Emit a learn *candidate* only when the run proved complete.

    A non-converged or unproven run yields ``SKIPPED`` with no candidate, so we
    never propose learning from an unverified outcome.
    """
    if not (proof_complete and result.converged and result.iterations):
        return StageOutcome(
            HarnessStage.LEARN_CANDIDATE,
            StageStatus.SKIPPED,
            "no candidate: run did not prove complete",
            {"candidate": None},
        )
    final = result.iterations[-1]
    digest = hashlib.sha256(final.verify_output.encode("utf-8")).hexdigest()
    candidate = LearnCandidate(
        title=f"verified: {dag.task}"[:120],
        body=(
            f"Task converged after {len(result.iterations)} iteration(s) with the "
            f"configured verifier passing. Candidate for memstage review."
        ),
        evidence_digest=digest,
    )
    return StageOutcome(
        HarnessStage.LEARN_CANDIDATE,
        StageStatus.OK,
        "learn candidate proposed (not persisted)",
        {"candidate": candidate.to_dict()},
    )


__all__ = [
    "HarnessStage",
    "LearnCandidate",
    "StageOutcome",
    "StageStatus",
    "context_stage",
    "execute_stage",
    "learn_candidate_stage",
    "prepare_stage",
    "proof_stage",
    "verify_stage",
]
