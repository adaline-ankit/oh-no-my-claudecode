from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.test_harness_run import AllowPolicy, FakeLoop, _loop_result

from oh_no_my_claudecode.durable_runtime import RuntimeStore
from oh_no_my_claudecode.harness_run import ControllerDependencies, HarnessController, RunRequest
from oh_no_my_claudecode.runtime import (
    Budget,
    CapabilitySet,
    EvidenceRef,
    NativeExecutionBackend,
    NodeResult,
    NodeResultStatus,
    NodeSpec,
    RunResultStatus,
    RunSpec,
    RuntimeContractError,
)


def _node(
    node_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    side_effecting: bool = False,
) -> NodeSpec:
    return NodeSpec(
        node_id=node_id,
        kind="test",
        objective=f"Run {node_id}",
        completion_condition=f"{node_id} produced verifier evidence" if side_effecting else None,
        dependencies=dependencies,
        side_effecting=side_effecting,
        idempotency_key=f"idem:{node_id}" if side_effecting else None,
        timeout_seconds=30.0 if side_effecting else None,
        budget=Budget(timeout_seconds=30.0, max_tokens=100) if side_effecting else None,
        capabilities=CapabilitySet(tools=("edit",), filesystem_write=side_effecting),
    )


def test_side_effecting_nodes_require_idempotency_timeout_budget_and_capabilities() -> None:
    with pytest.raises(RuntimeContractError, match="idempotency_key"):
        NodeSpec(
            node_id="execute",
            kind="execute",
            objective="Make a change",
            completion_condition="Verifier passed",
            dependencies=(),
            side_effecting=True,
            idempotency_key=None,
            timeout_seconds=30.0,
            budget=Budget(timeout_seconds=30.0),
            capabilities=CapabilitySet(tools=("edit",), filesystem_write=True),
        )

    with pytest.raises(RuntimeContractError, match="requires timeout_seconds"):
        NodeSpec(
            node_id="execute",
            kind="execute",
            objective="Make a change",
            completion_condition="Verifier passed",
            dependencies=(),
            side_effecting=True,
            idempotency_key="idem:execute",
            timeout_seconds=None,
            budget=Budget(timeout_seconds=30.0),
            capabilities=CapabilitySet(tools=("edit",), filesystem_write=True),
        )

    with pytest.raises(RuntimeContractError, match="requires budget"):
        NodeSpec(
            node_id="execute",
            kind="execute",
            objective="Make a change",
            completion_condition="Verifier passed",
            dependencies=(),
            side_effecting=True,
            idempotency_key="idem:execute",
            timeout_seconds=30.0,
            budget=None,
            capabilities=CapabilitySet(tools=("edit",), filesystem_write=True),
        )

    with pytest.raises(RuntimeContractError, match="declared capabilities"):
        NodeSpec(
            node_id="execute",
            kind="execute",
            objective="Make a change",
            completion_condition="Verifier passed",
            dependencies=(),
            side_effecting=True,
            idempotency_key="idem:execute",
            timeout_seconds=30.0,
            budget=Budget(timeout_seconds=30.0),
            capabilities=CapabilitySet(),
        )

    with pytest.raises(RuntimeContractError, match="completion_condition"):
        NodeSpec(
            node_id="execute",
            kind="execute",
            objective="Make a change",
            completion_condition=None,
            dependencies=(),
            side_effecting=True,
            idempotency_key="idem:execute",
            timeout_seconds=30.0,
            budget=Budget(timeout_seconds=30.0),
            capabilities=CapabilitySet(tools=("edit",), filesystem_write=True),
        )


def test_run_spec_rejects_invalid_edges_and_serializes_stably() -> None:
    spec = RunSpec(
        run_id="run-1",
        task="Build feature",
        nodes=(_node("plan"), _node("execute", dependencies=("plan",), side_effecting=True)),
    )
    assert RunSpec.from_dict(json.loads(spec.to_json())).to_json() == spec.to_json()
    assert spec.digest == RunSpec.from_dict(spec.to_dict()).digest

    with pytest.raises(RuntimeContractError, match="missing nodes"):
        RunSpec(
            run_id="run-2",
            task="Broken",
            nodes=(_node("execute", dependencies=("missing",), side_effecting=True),),
        )

    with pytest.raises(RuntimeContractError, match="acyclic"):
        RunSpec(
            run_id="run-3",
            task="Cycle",
            nodes=(
                _node("a", dependencies=("b",), side_effecting=True),
                _node("b", dependencies=("a",), side_effecting=True),
            ),
        )


def test_native_backend_replays_completed_idempotency_without_side_effect(tmp_path: Path) -> None:
    spec = RunSpec(
        run_id="run-1",
        task="Build feature",
        nodes=(_node("plan"), _node("execute", dependencies=("plan",), side_effecting=True)),
    )
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "runtime"), repo_root=tmp_path)
    calls: list[str] = []

    def handler(node: NodeSpec) -> NodeResult:
        calls.append(node.node_id)
        return NodeResult(
            node_id=node.node_id,
            status=NodeResultStatus.SUCCEEDED,
            idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
            evidence=_completion_evidence(node) if node.side_effecting else (),
            output={"call": len(calls)},
        )

    first = backend.execute(spec, {"plan": handler, "execute": handler})
    event_count_after_first_run = len(backend.store.events("run-1"))
    second = backend.execute(spec, {"plan": handler, "execute": handler})

    assert first.status is RunResultStatus.COMPLETED
    assert second.status is RunResultStatus.COMPLETED
    assert calls == ["plan", "execute"]
    assert [item.to_dict() for item in second.results] == [
        item.to_dict() for item in first.results
    ]
    assert len(backend.store.events("run-1")) == event_count_after_first_run


def test_native_backend_recovers_result_written_before_crash_without_side_effect(
    tmp_path: Path,
) -> None:
    spec = RunSpec(
        run_id="run-crash",
        task="Build feature",
        nodes=(_node("execute", side_effecting=True),),
    )
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "runtime"), repo_root=tmp_path)
    backend.store.create_run(
        spec.run_id,
        node_ids=("execute",),
        repo=tmp_path,
        idempotency_key="runtime:create",
    )
    backend.store.start(spec.run_id, idempotency_key="runtime:start")
    backend.store.start_node(
        spec.run_id,
        "execute",
        idempotency_key="runtime:execute:start",
    )
    backend._write_spec_manifest(spec)
    result = NodeResult(
        node_id="execute",
        status=NodeResultStatus.SUCCEEDED,
        idempotency_key="idem:execute",
        evidence=_completion_evidence(spec.nodes[0]),
        output={"written_before_crash": True},
    )
    backend._write_result(spec.run_id, result)

    def must_not_run(node: NodeSpec) -> NodeResult:
        raise AssertionError(f"handler repeated side effect for {node.node_id}")

    recovered = backend.execute(spec, {"execute": must_not_run}, resume=True)

    assert recovered.status is RunResultStatus.COMPLETED
    assert [item.to_dict() for item in recovered.results] == [result.to_dict()]
    snapshot = backend.store.load(spec.run_id)
    assert snapshot.state.value == "completed"
    assert snapshot.nodes["execute"].state.value == "succeeded"


def test_native_backend_rejects_successful_side_effect_without_completion_evidence(
    tmp_path: Path,
) -> None:
    spec = RunSpec(
        run_id="run-vacuous",
        task="Build feature",
        nodes=(_node("execute", side_effecting=True),),
    )
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "runtime"), repo_root=tmp_path)

    result = backend.execute(
        spec,
        {
            "execute": lambda node: NodeResult(
                node_id=node.node_id,
                status=NodeResultStatus.SUCCEEDED,
                idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
            )
        },
    )

    assert result.status is RunResultStatus.FAILED
    assert result.error is not None
    assert "completion evidence" in result.error


def test_native_backend_rejects_resume_with_mismatched_run_spec(tmp_path: Path) -> None:
    original = RunSpec(
        run_id="run-locked",
        task="Original task",
        nodes=(_node("plan"),),
    )
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "runtime"), repo_root=tmp_path)
    result = backend.execute(
        original,
        {
            "plan": lambda node: NodeResult(
                node_id=node.node_id,
                status=NodeResultStatus.SUCCEEDED,
                idempotency_key=f"runtime:{node.node_id}",
            )
        },
    )
    assert result.status is RunResultStatus.COMPLETED
    changed = RunSpec(
        run_id="run-locked",
        task="Changed task",
        nodes=(_node("plan"),),
    )

    with pytest.raises(RuntimeContractError, match="digest"):
        backend.execute(changed, {"plan": lambda node: pytest.fail("must not run")})


def test_harness_plan_compiles_to_canonical_run_spec(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    dependencies = ControllerDependencies(
        context_engine=HarnessController(tmp_path).dependencies.context_engine,
        runtime_store=RuntimeStore(tmp_path / ".onmc" / "harness-runtime"),
        policy_decider=AllowPolicy(),
        loop_executor=loop,
    )
    request = RunRequest(
        task="Implement billing webhook",
        plan_only=True,
        verifier="pytest tests/billing",
    )
    plan = HarnessController(tmp_path, dependencies=dependencies).run(request).plan

    spec = plan.to_run_spec()

    assert spec.run_id == plan.run_id
    assert spec.task == "Implement billing webhook"
    assert [node.node_id for node in spec.nodes] == [
        node.node_id for node in plan.dag.topological_order()
    ]
    execute = next(node for node in spec.nodes if node.node_id == "execute")
    verify = next(node for node in spec.nodes if node.node_id == "verify")
    assert execute.side_effecting is True
    assert execute.capabilities.filesystem_write is True
    assert ("pytest", "tests/billing") in verify.capabilities.commands
    assert spec.metadata["source"] == "harness_run.ExecutionPlan"


def _completion_evidence(node: NodeSpec) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            evidence_id=f"{node.node_id}:completion",
            kind="completion",
            uri=f"onmc://runtime/{node.node_id}/completion",
            digest="sha256:" + ("0" * 64),
        ),
    )
