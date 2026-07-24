"""Typed public contracts for ``onmc run`` planning and execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from oh_no_my_claudecode.context_engine import EvidencePacket
from oh_no_my_claudecode.harness import RiskLevel, TaskDAG
from oh_no_my_claudecode.harness_run.budget_modes import BudgetMode

AgentName = Literal["claude", "codex", "opencode"]


class HarnessStatus(StrEnum):
    """Honest terminal states returned by the public harness."""

    PLANNED = "planned"
    DENIED = "denied"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Validated inputs shared by plan-only and executing runs."""

    task: str
    plan_only: bool = False
    execute: bool = False
    agent: AgentName = "claude"
    model: str = "default"
    verifier: str = "pytest"
    max_iterations: int = 10
    max_cost_usd: float | None = None
    isolation: bool = False
    risk: RiskLevel = RiskLevel.MEDIUM
    context_budget: int = 4_000
    budget_mode: BudgetMode = BudgetMode.STANDARD
    resume_run_id: str | None = None

    def __post_init__(self) -> None:
        if self.plan_only and self.execute:
            raise ValueError("--plan-only and --execute are mutually exclusive")
        if not isinstance(self.task, str) or not self.task.strip():
            raise ValueError("task must not be empty")
        if self.agent not in {"claude", "codex", "opencode"}:
            raise ValueError("agent must be claude, codex, or opencode")
        if not self.model.strip():
            raise ValueError("model must not be empty")
        if not self.verifier.strip():
            raise ValueError("verifier must not be empty")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if self.max_cost_usd is not None and self.max_cost_usd < 0:
            raise ValueError("max_cost_usd must be non-negative")
        if self.context_budget < 1:
            raise ValueError("context_budget must be positive")
        if not isinstance(self.risk, RiskLevel):
            raise ValueError("risk must be a RiskLevel")
        if not isinstance(self.budget_mode, BudgetMode):
            raise ValueError("budget_mode must be a BudgetMode")


@dataclass(frozen=True, slots=True)
class ProofRequirement:
    """One verifier-backed completion requirement."""

    verifier_id: str
    argv: tuple[str, ...]
    expected_outcome: str
    claim_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "verifier_id": self.verifier_id,
            "argv": list(self.argv),
            "expected_outcome": self.expected_outcome,
            "claim_ids": list(self.claim_ids),
        }


@dataclass(frozen=True, slots=True)
class PolicyDecisionRecord:
    """Serializable broker decision for a declared capability."""

    capability: str
    allowed: bool
    effect: str
    reason: str
    matched_rule_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "capability": self.capability,
            "allowed": self.allowed,
            "effect": self.effect,
            "reason": self.reason,
            "matched_rule_ids": list(self.matched_rule_ids),
        }


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Deterministic, subprocess-free execution plan."""

    run_id: str
    dag: TaskDAG
    context_packet: EvidencePacket
    proof_requirements: tuple[ProofRequirement, ...]
    policy_decisions: tuple[PolicyDecisionRecord, ...]
    state_path: str
    schema_version: str = "1"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "dag": self.dag.to_dict(),
            "context_packet": self.context_packet.to_dict(),
            "proof_requirements": [item.to_dict() for item in self.proof_requirements],
            "policy_decisions": [item.to_dict() for item in self.policy_decisions],
            "state_path": self.state_path,
            "resume": {
                "supported": True,
                "run_id": self.run_id,
                "flag": f"--resume {self.run_id}",
            },
        }


@dataclass(frozen=True, slots=True)
class HarnessResult:
    """Plan plus an honest execution/proof verdict."""

    status: HarnessStatus
    plan: ExecutionPlan
    loop_converged: bool = False
    proof_complete: bool = False
    stop_reason: str = "plan-only"
    proof_reasons: tuple[str, ...] = ()
    resumed: bool = False
    resume_run_id: str | None = None
    worktree_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "plan": self.plan.to_dict(),
            "loop_converged": self.loop_converged,
            "proof_complete": self.proof_complete,
            "stop_reason": self.stop_reason,
            "proof_reasons": list(self.proof_reasons),
            "resumed": self.resumed,
            "resume_run_id": self.resume_run_id,
            "worktree_path": self.worktree_path,
        }

    def render_text(self) -> str:
        lines = [
            f"ONMC run {self.plan.run_id}: {self.status.value}",
            f"Task: {self.plan.dag.task}",
            f"State: {self.plan.state_path}",
            f"DAG: {' -> '.join(node.node_id for node in self.plan.dag.topological_order())}",
            (
                "Context: "
                f"{self.plan.context_packet.used_tokens}/"
                f"{self.plan.context_packet.token_budget} tokens"
            ),
            f"Proof requirements: {len(self.plan.proof_requirements)}",
            "Policy: "
            + ", ".join(
                f"{item.capability}={item.effect}" for item in self.plan.policy_decisions
            ),
        ]
        if self.status is not HarnessStatus.PLANNED:
            lines.append(
                f"Outcome: loop_converged={self.loop_converged}, "
                f"proof_complete={self.proof_complete}, stop={self.stop_reason}"
            )
        if self.worktree_path is not None:
            lines.append(f"Worktree: {self.worktree_path}")
        return "\n".join(lines)


def state_path_for(root: Path, run_id: str) -> str:
    """Return the durable event directory exposed in plans."""
    return str(root / "runs" / run_id)


__all__ = [
    "AgentName",
    "ExecutionPlan",
    "HarnessResult",
    "HarnessStatus",
    "PolicyDecisionRecord",
    "ProofRequirement",
    "RunRequest",
    "state_path_for",
]
