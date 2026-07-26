"""Run-report coverage manifest for honest harness/eval claims."""

from __future__ import annotations

from dataclasses import dataclass

from oh_no_my_claudecode.loop.models import IterationContract, LoopResult
from oh_no_my_claudecode.proof_graph import ProofAssessment

from .run_policy import RunPolicyDecision
from .stages import StageName, StageRecord

_SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ReportCoverageField:
    """Coverage verdict for one SOTA/eval report requirement."""

    name: str
    covered: bool
    source: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "covered": self.covered,
            "source": self.source,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ReportCoverageManifest:
    """Machine-readable coverage of what this run can honestly report."""

    fields: tuple[ReportCoverageField, ...]
    schema_version: str = _SCHEMA_VERSION

    @property
    def covered_count(self) -> int:
        return sum(1 for field in self.fields if field.covered)

    @property
    def missing_count(self) -> int:
        return len(self.fields) - self.covered_count

    @property
    def claim_ready(self) -> bool:
        """True only when all external-claim report fields are covered."""
        return self.missing_count == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "covered_count": self.covered_count,
            "missing_count": self.missing_count,
            "claim_ready": self.claim_ready,
            "fields": [field.to_dict() for field in self.fields],
        }


def report_coverage_manifest(
    *,
    loop_result: LoopResult | None,
    stages: tuple[StageRecord, ...],
    policy: RunPolicyDecision,
    proof: ProofAssessment,
) -> ReportCoverageManifest:
    """Build the honest report-coverage manifest for one completed run attempt."""

    stage_names = {stage.name for stage in stages}
    verify_stage = _stage(stages, StageName.VERIFY)
    execute_stage = _stage(stages, StageName.EXECUTE)
    proof_stage = _stage(stages, StageName.PROOF)
    has_trajectory = loop_result is not None and bool(loop_result.iterations)
    has_token_usage = bool(
        loop_result
        and (
            loop_result.total_tokens > 0
            or any(item.tokens is not None for item in loop_result.iterations)
        )
    )
    has_cost = bool(loop_result and loop_result.total_cost_usd is not None)
    fields = (
        ReportCoverageField(
            "raw_trajectories",
            has_trajectory,
            "receipt.trajectory",
            "loop iteration contracts persisted"
            if has_trajectory
            else "no loop trajectory was recorded",
        ),
        ReportCoverageField(
            "verifier_artifacts",
            verify_stage is not None and proof_stage is not None,
            "harness.stages.verify + harness.stages.proof",
            "verifier and proof stage records are present"
            if verify_stage is not None and proof_stage is not None
            else "verifier/proof stage records are missing",
        ),
        ReportCoverageField(
            "pass_rate",
            verify_stage is not None,
            "harness.stages.verify",
            "single-run verifier pass/fail is present"
            if verify_stage is not None
            else "no verifier stage is present",
        ),
        ReportCoverageField(
            "pass_at_k",
            False,
            "not available",
            "this is a single attempt, not a multi-sample pass@k evaluation",
        ),
        ReportCoverageField(
            "paired_deltas",
            False,
            "not available",
            "no matched plain-agent control run is attached",
        ),
        ReportCoverageField(
            "uncertainty",
            False,
            "not available",
            "no repeated seeds or confidence interval are attached",
        ),
        ReportCoverageField(
            "latency",
            False,
            "not available",
            "harness stages currently record outcomes, not measured wall-clock spans",
        ),
        ReportCoverageField(
            "token_use",
            has_token_usage,
            "receipt.tokens_used",
            "adapter reported token usage"
            if has_token_usage
            else "adapter did not report token usage",
        ),
        ReportCoverageField(
            "cost_coverage",
            has_cost,
            "receipt.cost_usd",
            "adapter reported cost"
            if has_cost
            else "adapter did not report cost; cost must stay unknown",
        ),
        ReportCoverageField(
            "failure_taxonomy",
            bool(execute_stage or proof.reasons or policy.violations),
            "harness stages + proof + policy",
            "stop/proof/policy failure reasons are recorded",
        ),
        ReportCoverageField(
            "leakage_audit",
            False,
            "not available",
            "no external benchmark dataset or leakage audit is attached",
        ),
        ReportCoverageField(
            "environment_manifest",
            True,
            "runtime_contract.metadata.environment_snapshot",
            "repo and runtime snapshot are bound into the runtime contract",
        ),
        ReportCoverageField(
            "runtime_contract",
            bool(stage_names),
            "harness.runtime_contract",
            "canonical runtime contract is bound into the harness receipt",
        ),
    )
    return ReportCoverageManifest(fields=fields)


def trajectory_payload(loop_result: LoopResult | None) -> tuple[dict[str, object], ...]:
    """Return JSON-safe raw iteration contracts for persisted run receipts."""

    if loop_result is None:
        return ()
    return tuple(_iteration_payload(iteration) for iteration in loop_result.iterations)


def _iteration_payload(iteration: IterationContract) -> dict[str, object]:
    return {
        "iteration": iteration.iteration,
        "prediction": iteration.prediction,
        "action_summary": iteration.action_summary,
        "files_touched": list(iteration.files_touched),
        "verify_passed": iteration.verify_passed,
        "verify_output": iteration.verify_output,
        "outcome": iteration.outcome,
        "tokens": iteration.tokens,
        "route_decision": iteration.route_decision,
    }


def _stage(stages: tuple[StageRecord, ...], name: StageName) -> StageRecord | None:
    return next((stage for stage in stages if stage.name is name), None)


__all__ = [
    "ReportCoverageField",
    "ReportCoverageManifest",
    "report_coverage_manifest",
    "trajectory_payload",
]
