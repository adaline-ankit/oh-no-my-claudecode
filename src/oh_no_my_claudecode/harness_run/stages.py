"""Typed, content-bearing records for the six real harness-run stages.

Before this module the run's non-execute phases were metadata-only: the durable
runtime flipped node states from PENDING to SUCCEEDED without recording *what*
each phase observed. Each builder here turns the real artifacts of a run — the
compiled DAG, the retrieved context packet, the loop result, the verifier
signals, the proof assessment, and the derived learning candidates — into a
typed :class:`StageRecord` with a stable digest.

Every builder is a pure function of already-computed run data, so stages are
reproducible and serialisable into the run receipt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from oh_no_my_claudecode.context_engine import EvidencePacket
from oh_no_my_claudecode.harness import RiskLevel, TaskDAG
from oh_no_my_claudecode.loop.models import LoopResult
from oh_no_my_claudecode.proof_graph import ProofAssessment
from oh_no_my_claudecode.retrieval import RetrievalDecision

from .context_selection import context_selection_manifest
from .run_policy import VerifierSignal, injection_findings

_SCHEMA_VERSION = "1"


class StageName(StrEnum):
    """The six stages that make up one honest harness run."""

    PREPARE = "prepare"
    CONTEXT = "context"
    EXECUTE = "execute"
    VERIFY = "verify"
    PROOF = "proof"
    LEARN_CANDIDATE = "learn-candidate"


class StageStatus(StrEnum):
    """Honest terminal state of a single stage."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class StageRecord:
    """One typed stage outcome with ordered, JSON-safe facts and a digest."""

    name: StageName
    status: StageStatus
    summary: str
    facts: tuple[tuple[str, str], ...] = ()
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name.value,
            "status": self.status.value,
            "summary": self.summary,
            "facts": [list(pair) for pair in self.facts],
            "reasons": list(self.reasons),
        }

    def digest(self) -> str:
        canonical = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def ok(self) -> bool:
        return self.status is StageStatus.SUCCEEDED


def prepare_stage(dag: TaskDAG, run_id: str, risk: RiskLevel) -> StageRecord:
    """Record the compiled, validated plan that will be executed."""
    return StageRecord(
        name=StageName.PREPARE,
        status=StageStatus.SUCCEEDED,
        summary=f"compiled {len(dag.nodes)}-node plan at risk={risk.value}",
        facts=(
            ("run_id", run_id),
            ("nodes", str(len(dag.nodes))),
            ("risk", risk.value),
            ("dag_digest", hashlib.sha256(dag.to_json().encode("utf-8")).hexdigest()),
        ),
    )


def context_stage(
    packet: EvidencePacket,
    retrieval_fallbacks: tuple[str, ...] = (),
    retrieval_decision: RetrievalDecision | None = None,
) -> StageRecord:
    """Record retrieved context and quarantine any injected instructions.

    Retrieved repository text is untrusted data. Injection patterns are reported
    as ``reasons`` but never fail the stage — they are neutralised by being
    rendered inside an explicit untrusted-data envelope, not by being dropped.

    *retrieval_fallbacks* carries typed reasons for any degradation to the basic
    lexical provider. A degraded run must not look like a healthy one: the
    fallback keeps the run alive, but hiding it would let a silently disabled
    retriever be measured as if it were working.
    """
    joined = "\n".join(item.content for item in packet.evidence)
    findings = injection_findings(joined)
    selection = context_selection_manifest(
        packet,
        retrieval_fallbacks=retrieval_fallbacks,
        retrieval_decision=retrieval_decision,
    )
    reasons = tuple(f"quarantined: {finding.rule_id} {finding.title}" for finding in findings)
    reasons += tuple(f"retrieval-fallback: {reason}" for reason in retrieval_fallbacks)
    summary = (
        f"{selection.used_count}/{selection.explored_count} context candidates used, "
        f"{selection.used_tokens} tokens"
    )
    if findings:
        summary += f"; {len(findings)} injection pattern(s) quarantined"
    if retrieval_fallbacks:
        summary += f"; {len(retrieval_fallbacks)} retrieval fallback(s) — DEGRADED"
    return StageRecord(
        name=StageName.CONTEXT,
        status=StageStatus.SUCCEEDED,
        summary=summary,
        facts=(
            ("evidence_spans", str(len(packet.evidence))),
            ("explored_context", str(selection.explored_count)),
            ("excluded_context", str(selection.excluded_count)),
            ("used_tokens", str(packet.used_tokens)),
            ("token_budget", str(packet.token_budget)),
            ("confidence", f"{selection.confidence:.4f}"),
            ("low_confidence", str(selection.low_confidence).lower()),
            ("abstained", str(selection.abstained).lower()),
            ("fallback_decision", selection.fallback_decision),
            ("query_intent", selection.query_intent),
            ("retrieval_stage", selection.retrieval_stage),
            ("lexical_floor", str(selection.lexical_floor).lower()),
            ("candidate_promoted", str(selection.candidate_promoted).lower()),
            ("injection_findings", str(len(findings))),
        ),
        reasons=reasons,
    )


def execute_stage(
    result: LoopResult,
    *,
    changed_files: tuple[str, ...],
    diff_line_count: int,
) -> StageRecord:
    """Record the real agent loop's outcome and the change it produced."""
    status = StageStatus.SUCCEEDED if result.converged else StageStatus.FAILED
    routed = tuple(
        iteration.route_decision
        for iteration in result.iterations
        if iteration.route_decision is not None
    )
    escalations = sum(1 for decision in routed if decision.get("action") == "escalate")
    return StageRecord(
        name=StageName.EXECUTE,
        status=status,
        summary=(
            f"loop {'converged' if result.converged else 'did not converge'} "
            f"after {len(result.iterations)} iteration(s)"
        ),
        facts=(
            ("converged", str(result.converged).lower()),
            ("iterations", str(len(result.iterations))),
            ("stop_reason", result.stop_reason or "none"),
            ("files_touched", str(len(changed_files))),
            ("diff_lines", str(diff_line_count)),
            ("routing_decisions", str(len(routed))),
            ("routing_escalations", str(escalations)),
        ),
        reasons=() if result.converged else (result.stop_reason or "loop did not converge",),
    )


def verify_stage(signals: tuple[VerifierSignal, ...]) -> StageRecord:
    """Record the observed verifier outcomes distinctly from execution."""
    all_passed = bool(signals) and all(signal.passed for signal in signals)
    failed = tuple(signal.name for signal in signals if not signal.passed)
    if not signals:
        status = StageStatus.FAILED
        reasons: tuple[str, ...] = ("no verifier was executed",)
    elif all_passed:
        status = StageStatus.SUCCEEDED
        reasons = ()
    else:
        status = StageStatus.FAILED
        reasons = tuple(f"verifier failed: {name}" for name in failed)
    return StageRecord(
        name=StageName.VERIFY,
        status=status,
        summary=f"{len(signals) - len(failed)}/{len(signals)} verifier(s) passed",
        facts=tuple((signal.name, "pass" if signal.passed else "fail") for signal in signals),
        reasons=reasons,
    )


def proof_stage(assessment: ProofAssessment, *, receipt_hash: str) -> StageRecord:
    """Record the proof verdict. Succeeds only on a complete, non-false-green proof."""
    proven = assessment.complete and not assessment.false_green
    return StageRecord(
        name=StageName.PROOF,
        status=StageStatus.SUCCEEDED if proven else StageStatus.FAILED,
        summary="proof complete" if proven else "proof incomplete",
        facts=(
            ("complete", str(assessment.complete).lower()),
            ("false_green", str(assessment.false_green).lower()),
            ("receipt_hash", receipt_hash),
        ),
        reasons=assessment.reasons,
    )


def learn_candidate_stage(result: LoopResult, *, proven: bool) -> StageRecord:
    """Derive non-persisted learning candidates from the run.

    This stage never writes to the memory store (that is ``onmc memstage``'s
    job). It only proposes what *would* be worth durably recording, so a caller
    can stage it behind review.
    """
    candidates: list[str] = []
    if proven:
        candidates.append(f"decision: task converged and proved via '{result.stop_reason}'")
    else:
        candidates.append(f"dead-end: run stopped unproven at '{result.stop_reason}'")
    seen_errors = {
        contract.verify_output[:80]
        for contract in result.iterations
        if not contract.verify_passed and contract.verify_output.strip()
    }
    for error_head in sorted(seen_errors):
        candidates.append(f"dead-end: verifier rejected change — {error_head}")
    return StageRecord(
        name=StageName.LEARN_CANDIDATE,
        status=StageStatus.SUCCEEDED,
        summary=f"{len(candidates)} learning candidate(s) proposed (not persisted)",
        facts=tuple((f"candidate_{index}", text) for index, text in enumerate(candidates)),
    )


__all__ = [
    "StageName",
    "StageRecord",
    "StageStatus",
    "context_stage",
    "execute_stage",
    "learn_candidate_stage",
    "prepare_stage",
    "proof_stage",
    "verify_stage",
]
