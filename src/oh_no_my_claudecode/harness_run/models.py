"""Typed public contracts for ``onmc run`` planning and execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from oh_no_my_claudecode.context_engine import EvidencePacket
from oh_no_my_claudecode.harness import NodeKind, RiskLevel, TaskDAG
from oh_no_my_claudecode.harness_run.budget_modes import BudgetMode
from oh_no_my_claudecode.runtime.adapter_capabilities import adapter_capability_payload
from oh_no_my_claudecode.runtime.contracts import (
    Budget,
    CapabilitySet,
    EvidenceRef,
    NodeSpec,
    RunSpec,
)
from oh_no_my_claudecode.runtime.contracts import (
    RetryPolicy as RuntimeRetryPolicy,
)

from .context_selection import ContextSelectionManifest
from .isolation import IsolationProfile
from .receipt import HarnessRunReceipt
from .run_policy import RunPolicyDecision
from .stages import StageRecord

AgentName = Literal["claude", "codex", "opencode"]


class HarnessStatus(StrEnum):
    """Honest terminal states returned by the public harness."""

    PLANNED = "planned"
    DENIED = "denied"
    BLOCKED = "blocked"
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
    context_selection: ContextSelectionManifest
    proof_requirements: tuple[ProofRequirement, ...]
    policy_decisions: tuple[PolicyDecisionRecord, ...]
    isolation_profile: IsolationProfile
    state_path: str
    schema_version: str = "1"

    def to_run_spec(self) -> RunSpec:
        """Compile the public plan into ONMC's canonical runtime graph."""
        evidence = tuple(_evidence_refs(self.context_packet))
        agent = self.dag.nodes[0].policy.agent if self.dag.nodes else "claude"
        adapter_capability = adapter_capability_payload(agent)
        isolation = self.isolation_profile.to_dict()
        context_selection = self.context_selection.to_dict()
        nodes = tuple(
            NodeSpec(
                node_id=node.node_id,
                kind=node.kind.value,
                objective=node.objective,
                completion_condition=_completion_condition_for(
                    node.kind,
                    node.objective,
                    self.proof_requirements,
                ),
                dependencies=node.dependencies,
                side_effecting=_node_has_side_effects(node.kind),
                approval_required=False,
                idempotency_key=f"{self.run_id}:node:{node.node_id}",
                timeout_seconds=120.0,
                budget=Budget(timeout_seconds=120.0, max_tokens=node.policy.context_budget),
                retry_policy=RuntimeRetryPolicy(
                    max_attempts=node.policy.retry.max_attempts,
                    backoff_seconds=node.policy.retry.backoff_seconds,
                ),
                capabilities=_capabilities_for(
                    node.kind,
                    node.policy.tools,
                    self.proof_requirements,
                ),
                metadata={
                    "agent": node.policy.agent,
                    "model": node.policy.model,
                    "adapter_capability": adapter_capability_payload(node.policy.agent),
                    "isolation_profile": isolation,
                    "context_selection": context_selection,
                    "risk": self.dag.risk.value,
                    "verifier": node.policy.verifier,
                },
            )
            for node in self.dag.nodes
        )
        return RunSpec(
            run_id=self.run_id,
            task=self.dag.task,
            nodes=nodes,
            evidence=evidence,
            metadata={
                "source": "harness_run.ExecutionPlan",
                "state_path": self.state_path,
                "adapter_capability": adapter_capability,
                "isolation_profile": isolation,
                "context_selection": context_selection,
            },
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "dag": self.dag.to_dict(),
            "context_packet": self.context_packet.to_dict(),
            "context_selection": self.context_selection.to_dict(),
            "proof_requirements": [item.to_dict() for item in self.proof_requirements],
            "policy_decisions": [item.to_dict() for item in self.policy_decisions],
            "isolation_profile": self.isolation_profile.to_dict(),
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
    verified: bool = False
    stages: tuple[StageRecord, ...] = ()
    policy_decision: RunPolicyDecision | None = None
    receipt: HarnessRunReceipt | None = None
    enforcement_trace: tuple[dict[str, Any], ...] = ()
    iterations: int | None = None
    """Loop iterations actually executed; ``None`` when no loop ran (plan-only)."""
    tokens_used: int | None = None
    """Agent tokens consumed; ``None`` when the run did not report them."""
    cost_usd: float | None = None
    """Agent spend in USD; ``None`` when the provider did not report a cost.

    Never defaulted to ``0.0`` — "cost unknown" and "cost was zero" are different
    facts, and a fabricated zero would make a run look free.
    """

    @property
    def enforcement_mode(self) -> str:
        """``enforced`` / ``advisory`` / ``none``, derived from the decision trace.

        ``advisory`` means the reference monitor recorded verdicts that blocked
        nothing. Reporting it explicitly is the difference between "effects were
        mediated" and "effects were logged" — a distinction the run output
        previously left invisible. ``none`` means no monitor ran at all, which is
        deliberately NOT reported as advisory: no trace is a weaker statement than
        an advisory trace.
        """
        if not self.enforcement_trace:
            return "none"
        # Mixed traces cannot occur today (one monitor per run) but must not be
        # silently reported as fully enforced if they ever do.
        modes = {str(record.get("mode", "advisory")) for record in self.enforcement_trace}
        if modes == {"enforced"}:
            return "enforced"
        if modes == {"advisory"}:
            return "advisory"
        return "mixed:" + "+".join(sorted(modes))

    @property
    def denied_effect_count(self) -> int:
        """Effects the monitor refused. Non-zero with ``enforced`` means blocked."""
        return sum(
            1
            for record in self.enforcement_trace
            if str(record.get("outcome", "")).lower() in {"deny", "denied", "escalate"}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "enforcement_mode": self.enforcement_mode,
            "denied_effect_count": self.denied_effect_count,
            "status": self.status.value,
            "plan": self.plan.to_dict(),
            "loop_converged": self.loop_converged,
            "proof_complete": self.proof_complete,
            "verified": self.verified,
            "stop_reason": self.stop_reason,
            "proof_reasons": list(self.proof_reasons),
            "resumed": self.resumed,
            "resume_run_id": self.resume_run_id,
            "worktree_path": self.worktree_path,
            "stages": [stage.to_dict() for stage in self.stages],
            "policy_decision": (
                self.policy_decision.to_dict() if self.policy_decision is not None else None
            ),
            "receipt": self.receipt.to_dict() if self.receipt is not None else None,
            "enforcement_trace": [dict(record) for record in self.enforcement_trace],
        }

    def render_text(self) -> str:
        agent = self.plan.dag.nodes[0].policy.agent if self.plan.dag.nodes else "claude"
        adapter_capability = adapter_capability_payload(agent)
        isolation = self.plan.isolation_profile
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
            (
                "Context decision: "
                f"explored={self.plan.context_selection.explored_count}, "
                f"used={self.plan.context_selection.used_count}, "
                f"confidence={self.plan.context_selection.confidence:.2f}, "
                f"fallback={self.plan.context_selection.fallback_decision}, "
                f"abstained={str(self.plan.context_selection.abstained).lower()}"
            ),
            f"Proof requirements: {len(self.plan.proof_requirements)}",
            "Policy: "
            + ", ".join(
                f"{item.capability}={item.effect}" for item in self.plan.policy_decisions
            ),
            (
                f"Adapter: {adapter_capability['agent']} "
                f"({adapter_capability['invocation_mode']}; "
                f"tokens={adapter_capability['tokens']}; "
                f"cost={adapter_capability['cost']}; "
                f"isolation={adapter_capability['isolation']})"
            ),
            (
                f"Isolation: {isolation.mode} "
                f"(filesystem={isolation.filesystem}; network={isolation.network}; "
                f"secrets={isolation.secrets})"
            ),
        ]
        if self.status is not HarnessStatus.PLANNED:
            lines.append(
                f"Outcome: loop_converged={self.loop_converged}, "
                f"proof_complete={self.proof_complete}, stop={self.stop_reason}"
            )
            # Cost/turns were previously invisible: an executed run reported no
            # spend at all, so a user could not see what a run had cost them.
            # "n/a" is used where the provider reported nothing — never $0.00.
            cost = "n/a" if self.cost_usd is None else f"${self.cost_usd:.4f}"
            tokens = "n/a" if self.tokens_used is None else str(self.tokens_used)
            iterations = "n/a" if self.iterations is None else str(self.iterations)
            lines.append(f"Usage: iterations={iterations}, tokens={tokens}, cost={cost}")
            # An advisory run looked IDENTICAL to an enforced one: the monitor
            # recorded a verdict that blocked nothing and said so nowhere. A user
            # could believe effects were being mediated when they were only being
            # observed, which is the exact difference between a guarantee and a
            # log. State the mode, and how many effects were actually guarded.
            lines.append(
                f"Enforcement: {self.enforcement_mode} "
                f"({len(self.enforcement_trace)} effect(s) guarded"
                + (f", {self.denied_effect_count} denied" if self.denied_effect_count else "")
                + ")"
            )
        if self.worktree_path is not None:
            lines.append(f"Worktree: {self.worktree_path}")
        return "\n".join(lines)


def state_path_for(root: Path, run_id: str) -> str:
    """Return the durable event directory exposed in plans."""
    return str(root / "runs" / run_id)


def _node_has_side_effects(kind: NodeKind) -> bool:
    return kind in {
        NodeKind.CLAIM,
        NodeKind.EXECUTE,
        NodeKind.VERIFY,
        NodeKind.REPAIR,
        NodeKind.PROVE,
        NodeKind.LEARN,
    }


def _capabilities_for(
    kind: NodeKind,
    tools: tuple[str, ...],
    proof_requirements: tuple[ProofRequirement, ...],
) -> CapabilitySet:
    if kind in {NodeKind.UNDERSTAND, NodeKind.RETRIEVE, NodeKind.PLAN}:
        return CapabilitySet(tools=tools)
    commands = tuple(requirement.argv for requirement in proof_requirements)
    if kind in {NodeKind.VERIFY, NodeKind.PROVE}:
        return CapabilitySet(tools=tools, commands=commands)
    return CapabilitySet(tools=tools, commands=commands, filesystem_write=True)


def _completion_condition_for(
    kind: NodeKind,
    objective: str,
    proof_requirements: tuple[ProofRequirement, ...],
) -> str | None:
    """Return the falsifiable condition required before a node can succeed."""
    if not _node_has_side_effects(kind):
        return None
    if kind in {NodeKind.VERIFY, NodeKind.PROVE} and proof_requirements:
        rendered = ", ".join(" ".join(requirement.argv) for requirement in proof_requirements)
        return f"Verifier command succeeds with digest-backed evidence: {rendered}"
    return f"Node objective has digest-backed completion evidence: {objective}"


def _evidence_refs(packet: EvidencePacket) -> tuple[EvidenceRef, ...]:
    refs: list[EvidenceRef] = []
    for item in packet.evidence:
        uri = item.citations[0].render() if item.citations else item.candidate_id
        refs.append(EvidenceRef(item.candidate_id, "repository-context", uri))
    return tuple(refs)


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
