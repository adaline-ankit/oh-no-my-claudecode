"""Deterministic compiler from task text to an execution-ready task DAG."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from oh_no_my_claudecode.harness.models import (
    SCHEMA_VERSION,
    NodeKind,
    NodePolicy,
    RetryPolicy,
    RiskLevel,
    TaskDAG,
    TaskNode,
)


@dataclass(frozen=True, slots=True)
class CompilerConfig:
    """Base execution policy applied to every compiled node."""

    agent: str = "codex"
    model: str = "default"
    tools: tuple[str, ...] = ("read", "search", "edit", "shell")
    context_budget: int = 16_000
    verifier: str = "pytest -q"
    retry: RetryPolicy = field(default_factory=RetryPolicy)


@dataclass(frozen=True, slots=True)
class _NodeTemplate:
    kind: NodeKind
    dependencies: tuple[NodeKind, ...]
    objective: str


@dataclass(frozen=True, slots=True)
class _RiskAdjustment:
    context_numerator: int
    context_denominator: int
    extra_attempts: int


_CANONICAL_NODES = (
    _NodeTemplate(
        NodeKind.UNDERSTAND,
        (),
        "Understand the task, constraints, and success criteria.",
    ),
    _NodeTemplate(
        NodeKind.RETRIEVE,
        (NodeKind.UNDERSTAND,),
        "Retrieve relevant code, context, prior decisions, and known dead ends.",
    ),
    _NodeTemplate(
        NodeKind.PLAN,
        (NodeKind.RETRIEVE,),
        "Plan the smallest dependency-ordered change.",
    ),
    _NodeTemplate(
        NodeKind.CLAIM,
        (NodeKind.PLAN,),
        "Claim the files and resources needed for execution.",
    ),
    _NodeTemplate(
        NodeKind.EXECUTE,
        (NodeKind.CLAIM,),
        "Execute the planned change within its scope.",
    ),
    _NodeTemplate(
        NodeKind.VERIFY,
        (NodeKind.EXECUTE,),
        "Run the configured verifier against the change.",
    ),
    _NodeTemplate(
        NodeKind.REPAIR,
        (NodeKind.VERIFY,),
        "Repair failures surfaced by verification.",
    ),
    _NodeTemplate(
        NodeKind.PROVE,
        (NodeKind.VERIFY, NodeKind.REPAIR),
        "Produce reproducible evidence that the success criteria are satisfied.",
    ),
    _NodeTemplate(
        NodeKind.LEARN,
        (NodeKind.PROVE,),
        "Capture durable outcomes, decisions, and dead ends.",
    ),
)

_RISK_ADJUSTMENTS = {
    RiskLevel.LOW: _RiskAdjustment(1, 1, 0),
    RiskLevel.MEDIUM: _RiskAdjustment(5, 4, 1),
    RiskLevel.HIGH: _RiskAdjustment(3, 2, 2),
    RiskLevel.CRITICAL: _RiskAdjustment(2, 1, 3),
}


def compile_task(
    task_text: str,
    *,
    risk: RiskLevel = RiskLevel.MEDIUM,
    config: CompilerConfig | None = None,
) -> TaskDAG:
    """Compile task text and policy inputs into the canonical execution DAG."""
    task = _normalize_task(task_text)
    if not isinstance(risk, RiskLevel):
        raise ValueError("risk must be a RiskLevel")
    selected = CompilerConfig() if config is None else config
    if not isinstance(selected, CompilerConfig):
        raise ValueError("config must be a CompilerConfig")
    policy = _policy_for(selected, risk)
    nodes = tuple(
        TaskNode(
            node_id=template.kind.value,
            kind=template.kind,
            objective=template.objective,
            dependencies=tuple(
                dependency.value for dependency in template.dependencies
            ),
            policy=policy,
        )
        for template in _CANONICAL_NODES
    )
    return TaskDAG(
        schema_version=SCHEMA_VERSION,
        task=task,
        risk=risk,
        nodes=nodes,
    )


def _normalize_task(task_text: str) -> str:
    if not isinstance(task_text, str):
        raise ValueError("task text must be a string")
    normalized = " ".join(task_text.split())
    if not normalized:
        raise ValueError("task text must not be empty")
    return normalized


def _policy_for(config: CompilerConfig, risk: RiskLevel) -> NodePolicy:
    adjustment = _RISK_ADJUSTMENTS[risk]
    if not isinstance(config.retry, RetryPolicy):
        raise ValueError("retry must be a RetryPolicy")
    config.retry.validate()
    if (
        not isinstance(config.context_budget, int)
        or isinstance(config.context_budget, bool)
        or config.context_budget <= 0
    ):
        raise ValueError("context_budget must be positive")
    scaled_budget = (
        config.context_budget
        * adjustment.context_numerator
        // adjustment.context_denominator
    )
    retry = replace(
        config.retry,
        max_attempts=config.retry.max_attempts + adjustment.extra_attempts,
    )
    return NodePolicy(
        agent=config.agent,
        model=config.model,
        tools=config.tools,
        context_budget=scaled_budget,
        verifier=config.verifier,
        retry=retry,
    )
