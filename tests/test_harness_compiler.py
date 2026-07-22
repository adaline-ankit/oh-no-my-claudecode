from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from oh_no_my_claudecode.harness import (
    SCHEMA_VERSION,
    CompilerConfig,
    DAGValidationError,
    NodeKind,
    NodePolicy,
    RetryPolicy,
    RiskLevel,
    SerializationError,
    TaskDAG,
    TaskNode,
    compile_task,
)

EXPECTED_KINDS = (
    NodeKind.UNDERSTAND,
    NodeKind.RETRIEVE,
    NodeKind.PLAN,
    NodeKind.CLAIM,
    NodeKind.EXECUTE,
    NodeKind.VERIFY,
    NodeKind.REPAIR,
    NodeKind.PROVE,
    NodeKind.LEARN,
)

EXPECTED_DEPENDENCIES = {
    "understand": (),
    "retrieve": ("understand",),
    "plan": ("retrieve",),
    "claim": ("plan",),
    "execute": ("claim",),
    "verify": ("execute",),
    "repair": ("verify",),
    "prove": ("verify", "repair"),
    "learn": ("prove",),
}


def _policy() -> NodePolicy:
    return NodePolicy(
        agent="codex",
        model="gpt-test",
        tools=("read",),
        context_budget=1000,
        verifier="pytest -q",
        retry=RetryPolicy(max_attempts=2, backoff_seconds=0.5),
    )


def _node(kind: NodeKind, dependencies: tuple[str, ...] = ()) -> TaskNode:
    return TaskNode(
        node_id=kind.value,
        kind=kind,
        objective=f"Run {kind.value}",
        dependencies=dependencies,
        policy=_policy(),
    )


def test_compile_builds_canonical_dag() -> None:
    dag = compile_task("Add safe cache invalidation", risk=RiskLevel.HIGH)

    assert dag.schema_version == SCHEMA_VERSION == "1"
    assert dag.task == "Add safe cache invalidation"
    assert dag.risk is RiskLevel.HIGH
    assert tuple(node.kind for node in dag.nodes) == EXPECTED_KINDS
    assert {node.node_id: node.dependencies for node in dag.nodes} == EXPECTED_DEPENDENCIES
    assert tuple(node.node_id for node in dag.topological_order()) == tuple(
        kind.value for kind in EXPECTED_KINDS
    )


def test_compile_normalizes_task_text_and_is_deterministic() -> None:
    first = compile_task("  Add\n safe   cache invalidation  ")
    second = compile_task("Add safe cache invalidation")

    assert first == second
    assert first.task == "Add safe cache invalidation"
    assert first.to_json() == second.to_json()


@pytest.mark.parametrize("config", [False, 0, "", (), [], {}])
def test_compile_rejects_falsey_non_config_values(config: object) -> None:
    with pytest.raises(ValueError, match="config must be a CompilerConfig"):
        compile_task("Reject invalid config", config=config)  # type: ignore[arg-type]


@pytest.mark.parametrize("task", ["", "   ", "\n\t"])
def test_compile_rejects_empty_task(task: str) -> None:
    with pytest.raises(ValueError, match="task text must not be empty"):
        compile_task(task)


def test_custom_config_populates_every_execution_policy_field() -> None:
    config = CompilerConfig(
        agent="claude",
        model="opus-test",
        tools=("search", "read", "shell"),
        context_budget=12_000,
        verifier="python -m pytest tests/test_target.py",
        retry=RetryPolicy(max_attempts=3, backoff_seconds=2.5),
    )

    dag = compile_task("Refactor target", risk=RiskLevel.LOW, config=config)

    assert all(node.policy.agent == "claude" for node in dag.nodes)
    assert all(node.policy.model == "opus-test" for node in dag.nodes)
    assert all(node.policy.tools == ("search", "read", "shell") for node in dag.nodes)
    assert all(node.policy.context_budget == 12_000 for node in dag.nodes)
    assert all(
        node.policy.verifier == "python -m pytest tests/test_target.py" for node in dag.nodes
    )
    assert all(node.policy.retry == config.retry for node in dag.nodes)


def test_risk_scales_budget_and_retry_deterministically() -> None:
    config = CompilerConfig(
        context_budget=8_000,
        retry=RetryPolicy(max_attempts=1, backoff_seconds=0.0),
    )

    policies = {
        risk: compile_task("Ship guarded change", risk=risk, config=config).nodes[0].policy
        for risk in RiskLevel
    }

    assert [policies[risk].context_budget for risk in RiskLevel] == [8_000, 10_000, 12_000, 16_000]
    assert [policies[risk].retry.max_attempts for risk in RiskLevel] == [1, 2, 3, 4]
    assert all(policy.retry.backoff_seconds == 0.0 for policy in policies.values())


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (CompilerConfig(agent=""), "agent must not be empty"),
        (CompilerConfig(model=" "), "model must not be empty"),
        (CompilerConfig(tools=()), "at least one tool"),
        (CompilerConfig(tools=("read", "read")), "tools must be unique"),
        (CompilerConfig(context_budget=0), "context_budget must be positive"),
        (CompilerConfig(verifier=""), "verifier must not be empty"),
    ],
)
def test_config_validation(config: CompilerConfig, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        compile_task("Valid task", config=config)


@pytest.mark.parametrize(
    ("retry", "message"),
    [
        (RetryPolicy(max_attempts=0), "max_attempts must be positive"),
        (RetryPolicy(backoff_seconds=-0.1), "backoff_seconds must not be negative"),
    ],
)
def test_retry_validation(retry: RetryPolicy, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        NodePolicy(
            agent="codex",
            model="default",
            tools=("read",),
            context_budget=100,
            verifier="pytest",
            retry=retry,
        )


def test_compile_validates_retry_before_risk_scaling() -> None:
    config = CompilerConfig(retry=RetryPolicy(max_attempts=0))
    with pytest.raises(ValueError, match="max_attempts must be positive"):
        compile_task("Do not mask invalid input", risk=RiskLevel.CRITICAL, config=config)


@pytest.mark.parametrize("backoff", [float("nan"), float("inf"), float("-inf")])
def test_compile_rejects_non_finite_retry_backoff(backoff: float) -> None:
    config = CompilerConfig(retry=RetryPolicy(backoff_seconds=backoff))
    with pytest.raises(ValueError, match="backoff_seconds must be finite"):
        compile_task("Reject non-finite retry", config=config)


def test_compile_rejects_unrepresentable_integer_retry_backoff() -> None:
    config = CompilerConfig(retry=RetryPolicy(backoff_seconds=10**10_000))
    with pytest.raises(ValueError, match="backoff_seconds must be finite"):
        compile_task("Reject unrepresentable retry", config=config)


def test_models_are_deeply_immutable() -> None:
    dag = compile_task("Immutable graph")

    with pytest.raises(FrozenInstanceError):
        dag.task = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        dag.nodes[0].objective = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        dag.nodes[0].policy.agent = "changed"  # type: ignore[misc]
    assert isinstance(dag.nodes, tuple)
    assert isinstance(dag.nodes[0].dependencies, tuple)
    assert isinstance(dag.nodes[0].policy.tools, tuple)


def test_graph_rejects_duplicate_node_ids() -> None:
    node = _node(NodeKind.UNDERSTAND)
    with pytest.raises(DAGValidationError, match="duplicate node id: understand"):
        TaskDAG(
            schema_version=SCHEMA_VERSION,
            task="task",
            risk=RiskLevel.LOW,
            nodes=(node, node),
        )


def test_graph_rejects_empty_node_set() -> None:
    with pytest.raises(DAGValidationError, match="at least one node"):
        TaskDAG(schema_version=SCHEMA_VERSION, task="task", risk=RiskLevel.LOW, nodes=())


def test_graph_rejects_missing_dependency() -> None:
    node = _node(NodeKind.RETRIEVE, ("missing",))
    with pytest.raises(DAGValidationError, match="unknown dependency 'missing'"):
        TaskDAG(
            schema_version=SCHEMA_VERSION,
            task="task",
            risk=RiskLevel.LOW,
            nodes=(node,),
        )


def test_graph_rejects_self_dependency() -> None:
    node = _node(NodeKind.UNDERSTAND, ("understand",))
    with pytest.raises(DAGValidationError, match="cannot depend on itself"):
        TaskDAG(
            schema_version=SCHEMA_VERSION,
            task="task",
            risk=RiskLevel.LOW,
            nodes=(node,),
        )


def test_graph_detects_cycle_with_path() -> None:
    nodes = (
        _node(NodeKind.UNDERSTAND, ("retrieve",)),
        _node(NodeKind.RETRIEVE, ("understand",)),
    )

    with pytest.raises(DAGValidationError, match=r"cycle detected: .*understand.*retrieve"):
        TaskDAG(
            schema_version=SCHEMA_VERSION,
            task="task",
            risk=RiskLevel.HIGH,
            nodes=nodes,
        )


def test_graph_validation_handles_deep_dag_without_recursion() -> None:
    nodes = tuple(
        TaskNode(
            node_id=f"node-{index}",
            kind=NodeKind.EXECUTE,
            objective=f"Execute step {index}",
            dependencies=() if index == 0 else (f"node-{index - 1}",),
            policy=_policy(),
        )
        for index in range(1_100)
    )

    dag = TaskDAG(
        schema_version=SCHEMA_VERSION,
        task="deep graph",
        risk=RiskLevel.LOW,
        nodes=nodes,
    )

    assert len(dag.topological_order()) == 1_100


def test_graph_rejects_duplicate_dependencies() -> None:
    with pytest.raises(DAGValidationError, match="dependencies must be unique"):
        _node(NodeKind.RETRIEVE, ("understand", "understand"))


def test_stable_json_round_trip_has_canonical_shape() -> None:
    dag = compile_task("Serialize this", risk=RiskLevel.CRITICAL)

    serialized = dag.to_json()
    decoded = json.loads(serialized)

    assert serialized == json.dumps(decoded, sort_keys=True, separators=(",", ":"))
    assert list(decoded) == ["nodes", "risk", "schema_version", "task"]
    assert TaskDAG.from_json(serialized) == dag
    assert TaskDAG.from_dict(dag.to_dict()) == dag
    assert TaskDAG.from_json(serialized).to_json() == serialized


def test_integer_backoff_has_byte_stable_json_round_trip() -> None:
    config = CompilerConfig(retry=RetryPolicy(backoff_seconds=1))
    dag = compile_task("Canonical numeric encoding", risk=RiskLevel.LOW, config=config)

    serialized = dag.to_json()

    assert '"backoff_seconds":1.0' in serialized
    assert TaskDAG.from_json(serialized).to_json() == serialized


def test_deserialization_accepts_bytes() -> None:
    dag = compile_task("Decode bytes")
    assert TaskDAG.from_json(dag.to_json().encode()) == dag


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not-json", "invalid task DAG JSON"),
        ("[]", "task DAG payload must be an object"),
        ('{"schema_version":"999","task":"x","risk":"low","nodes":[]}', "unsupported schema"),
        ('{"schema_version":"1","task":"x","risk":"unknown","nodes":[]}', "invalid risk"),
        ('{"schema_version":"1","task":"x","risk":"low"}', "missing fields: nodes"),
        (
            '{"schema_version":"1","task":"x","risk":"low","nodes":[],"extra":true}',
            "unknown fields: extra",
        ),
    ],
)
def test_deserialization_rejects_malformed_payloads(payload: str, message: str) -> None:
    with pytest.raises(SerializationError, match=message):
        TaskDAG.from_json(payload)


def test_deserialization_runs_dependency_validation() -> None:
    payload = compile_task("Validate decoded graph").to_dict()
    nodes = payload["nodes"]
    assert isinstance(nodes, list)
    retrieve = nodes[1]
    assert isinstance(retrieve, dict)
    retrieve["dependencies"] = ["missing"]

    with pytest.raises(DAGValidationError, match="unknown dependency 'missing'"):
        TaskDAG.from_dict(payload)


def test_deserialization_rejects_wrong_nested_types() -> None:
    payload = compile_task("Reject types").to_dict()
    nodes = payload["nodes"]
    assert isinstance(nodes, list)
    first = nodes[0]
    assert isinstance(first, dict)
    policy = first["policy"]
    assert isinstance(policy, dict)
    policy["context_budget"] = True

    with pytest.raises(SerializationError, match="context_budget must be an integer"):
        TaskDAG.from_dict(payload)
