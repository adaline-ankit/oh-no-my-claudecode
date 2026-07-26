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
    RetryPolicy,
    RunResultStatus,
    RunSpec,
    RuntimeContractError,
    adapter_capability_payload,
)
from oh_no_my_claudecode.trace.models import TraceEventKind
from oh_no_my_claudecode.trace.recorder import load_session_events, start_session


def _node(
    node_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    side_effecting: bool = False,
    approval_required: bool = False,
) -> NodeSpec:
    return NodeSpec(
        node_id=node_id,
        kind="test",
        objective=f"Run {node_id}",
        completion_condition=f"{node_id} produced verifier evidence" if side_effecting else None,
        dependencies=dependencies,
        side_effecting=side_effecting,
        approval_required=approval_required,
        idempotency_key=f"idem:{node_id}" if side_effecting else None,
        timeout_seconds=30.0 if side_effecting else None,
        budget=Budget(timeout_seconds=30.0, max_tokens=100) if side_effecting else None,
        retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=0.0)
        if side_effecting
        else None,
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
            approval_required=False,
            idempotency_key=None,
            timeout_seconds=30.0,
            budget=Budget(timeout_seconds=30.0),
            retry_policy=RetryPolicy(max_attempts=2),
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
            approval_required=False,
            idempotency_key="idem:execute",
            timeout_seconds=None,
            budget=Budget(timeout_seconds=30.0),
            retry_policy=RetryPolicy(max_attempts=2),
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
            approval_required=False,
            idempotency_key="idem:execute",
            timeout_seconds=30.0,
            budget=None,
            retry_policy=RetryPolicy(max_attempts=2),
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
            approval_required=False,
            idempotency_key="idem:execute",
            timeout_seconds=30.0,
            budget=Budget(timeout_seconds=30.0),
            retry_policy=RetryPolicy(max_attempts=2),
            capabilities=CapabilitySet(),
        )

    with pytest.raises(RuntimeContractError, match="requires retry_policy"):
        NodeSpec(
            node_id="execute",
            kind="execute",
            objective="Make a change",
            completion_condition="Verifier passed",
            dependencies=(),
            side_effecting=True,
            approval_required=False,
            idempotency_key="idem:execute",
            timeout_seconds=30.0,
            budget=Budget(timeout_seconds=30.0),
            retry_policy=None,
            capabilities=CapabilitySet(tools=("edit",), filesystem_write=True),
        )

    with pytest.raises(RuntimeContractError, match="completion_condition"):
        NodeSpec(
            node_id="execute",
            kind="execute",
            objective="Make a change",
            completion_condition=None,
            dependencies=(),
            side_effecting=True,
            approval_required=False,
            idempotency_key="idem:execute",
            timeout_seconds=30.0,
            budget=Budget(timeout_seconds=30.0),
            retry_policy=RetryPolicy(max_attempts=2),
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
        if node.side_effecting:
            snapshot = backend.store.load(spec.run_id)
            lease = snapshot.nodes[node.node_id].lease
            assert lease is not None
            assert lease.owner == "native"
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
    assert backend.store.load("run-1").nodes["execute"].lease is None


def test_native_backend_records_runtime_node_trace_event(tmp_path: Path) -> None:
    session_id = start_session(tmp_path, label="runtime trace")
    assert session_id is not None
    spec = RunSpec(
        run_id="run-trace",
        task="Build feature",
        nodes=(_node("execute", side_effecting=True),),
    )
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "runtime"), repo_root=tmp_path)
    calls: list[str] = []

    def handler(node: NodeSpec) -> NodeResult:
        calls.append(node.node_id)
        if len(calls) == 1:
            raise TimeoutError("temporarily unavailable")
        return NodeResult(
            node_id=node.node_id,
            status=NodeResultStatus.SUCCEEDED,
            idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
            evidence=_completion_evidence(node),
        )

    result = backend.execute(spec, {"execute": handler})

    assert result.status is RunResultStatus.COMPLETED
    session, events = load_session_events(
        tmp_path,
        session_id,
        include_notify_window=False,
    )
    assert session is not None
    runtime_events = [event for event in events if event.kind == TraceEventKind.RUNTIME_NODE]
    assert len(runtime_events) == 1
    payload = runtime_events[0].payload
    assert payload["backend"] == "native"
    assert payload["run_id"] == "run-trace"
    assert payload["node_id"] == "execute"
    assert payload["node_kind"] == "test"
    assert payload["status"] == "succeeded"
    assert payload["side_effecting"] is True
    assert payload["retry_attempts"] == 1
    assert payload["evidence_count"] == 1
    assert payload["evidence_kinds"] == ["completion"]
    assert payload["digest_evidence_count"] == 1
    assert payload["completion_evidence_count"] == 1
    assert payload["duration_seconds"] >= 0
    assert payload["end_ts"] >= runtime_events[0].ts
    assert payload["capabilities"]["filesystem_write"] is True
    run_events = [event for event in events if event.kind == TraceEventKind.RUNTIME_RUN]
    assert len(run_events) == 1
    run_payload = run_events[0].payload
    assert run_payload["backend"] == "native"
    assert run_payload["run_id"] == "run-trace"
    assert run_payload["status"] == "completed"
    assert run_payload["spec_digest"] == spec.digest
    assert len(run_payload["environment_digest"]) == 64
    assert len(run_payload["git_digest"]) == 64
    assert run_payload["environment_python_version"]
    assert run_payload["environment_platform"]
    assert "cwd" not in run_payload
    assert "executable" not in run_payload
    assert "git_root" not in run_payload
    assert run_payload["node_count"] == 1
    assert run_payload["result_count"] == 1
    assert run_payload["node_status_counts"] == {
        "failed": 0,
        "skipped": 0,
        "succeeded": 1,
    }
    assert run_payload["evidence_count"] == 1
    assert run_payload["evidence_kinds"] == ["completion"]
    assert run_payload["digest_evidence_count"] == 1
    assert run_payload["completion_evidence_count"] == 1
    assert run_payload["max_workers"] == 1
    assert run_payload["duration_seconds"] >= payload["duration_seconds"]


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
    backend.store.acquire_lease(
        spec.run_id,
        "execute",
        owner="native",
        ttl_seconds=30,
        idempotency_key="runtime:execute:lease:1",
    )
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
    assert snapshot.nodes["execute"].lease is None


def test_native_backend_reacquires_released_lease_after_crash_before_result_write(
    tmp_path: Path,
) -> None:
    spec = RunSpec(
        run_id="run-crash-after-release",
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
    lease = backend.store.acquire_lease(
        spec.run_id,
        "execute",
        owner="native",
        ttl_seconds=30,
        idempotency_key="runtime:execute:lease:1",
    )
    backend.store.release_lease(
        spec.run_id,
        "execute",
        token=lease.token,
        idempotency_key=f"runtime:execute:lease-release:{lease.token}",
    )
    calls: list[str] = []

    def handler(node: NodeSpec) -> NodeResult:
        calls.append(node.node_id)
        active = backend.store.load(spec.run_id).nodes[node.node_id].lease
        assert active is not None
        assert active.token != lease.token
        return NodeResult(
            node_id=node.node_id,
            status=NodeResultStatus.SUCCEEDED,
            idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
            evidence=_completion_evidence(node),
        )

    recovered = backend.execute(spec, {"execute": handler}, resume=True)

    assert recovered.status is RunResultStatus.COMPLETED
    assert calls == ["execute"]
    snapshot = backend.store.load(spec.run_id)
    assert snapshot.nodes["execute"].state.value == "succeeded"
    assert snapshot.nodes["execute"].lease is None


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


def test_native_backend_retries_transient_exception_before_terminal_result(
    tmp_path: Path,
) -> None:
    spec = RunSpec(
        run_id="run-retry-exception",
        task="Build feature",
        nodes=(_node("execute", side_effecting=True),),
    )
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "runtime"), repo_root=tmp_path)
    calls: list[int] = []

    def handler(node: NodeSpec) -> NodeResult:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise TimeoutError("temporarily unavailable")
        return NodeResult(
            node_id=node.node_id,
            status=NodeResultStatus.SUCCEEDED,
            idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
            evidence=_completion_evidence(node),
        )

    result = backend.execute(spec, {"execute": handler})

    assert result.status is RunResultStatus.COMPLETED
    assert calls == [1, 2]
    retry_history = backend.store.load(spec.run_id).nodes["execute"].retry_history
    assert len(retry_history) == 1
    assert retry_history[0].attempt == 1
    assert retry_history[0].retryable is True
    assert retry_history[0].reason == "temporarily unavailable"


def test_native_backend_persists_approval_interrupt_before_side_effect(
    tmp_path: Path,
) -> None:
    session_id = start_session(tmp_path, label="approval trace")
    assert session_id is not None
    spec = RunSpec(
        run_id="run-approval",
        task="Deploy feature",
        nodes=(_node("deploy", side_effecting=True, approval_required=True),),
    )
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "runtime"), repo_root=tmp_path)
    calls: list[str] = []

    def handler(node: NodeSpec) -> NodeResult:
        calls.append(node.node_id)
        return NodeResult(
            node_id=node.node_id,
            status=NodeResultStatus.SUCCEEDED,
            idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
            evidence=_completion_evidence(node),
        )

    interrupted = backend.execute(spec, {"deploy": handler})

    assert interrupted.status is RunResultStatus.INTERRUPTED
    assert calls == []
    snapshot = backend.store.load(spec.run_id)
    assert snapshot.state.value == "awaiting_approval"
    assert snapshot.nodes["deploy"].state.value == "awaiting_approval"
    _, events = load_session_events(
        tmp_path,
        session_id,
        include_notify_window=False,
    )
    runtime_events = [event for event in events if event.kind == TraceEventKind.RUNTIME_NODE]
    assert len(runtime_events) == 1
    payload = runtime_events[0].payload
    assert payload["run_id"] == "run-approval"
    assert payload["node_id"] == "deploy"
    assert payload["status"] == "interrupted"
    assert payload["error"] == "approval required before deploy"
    assert payload["approval_required"] is True
    assert payload["side_effecting"] is True


def test_native_backend_resumes_approval_interrupt_without_duplicate_side_effect(
    tmp_path: Path,
) -> None:
    spec = RunSpec(
        run_id="run-approved",
        task="Deploy feature",
        nodes=(_node("deploy", side_effecting=True, approval_required=True),),
    )
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "runtime"), repo_root=tmp_path)
    calls: list[str] = []

    def handler(node: NodeSpec) -> NodeResult:
        calls.append(node.node_id)
        return NodeResult(
            node_id=node.node_id,
            status=NodeResultStatus.SUCCEEDED,
            idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
            evidence=_completion_evidence(node),
        )

    interrupted = backend.execute(spec, {"deploy": handler})
    assert interrupted.status is RunResultStatus.INTERRUPTED
    backend.store.approve_node(
        spec.run_id,
        "deploy",
        approved_by="maintainer",
        idempotency_key="approve-node",
    )
    backend.store.approve(
        spec.run_id,
        approved_by="maintainer",
        idempotency_key="approve-run",
    )

    completed = backend.execute(spec, {"deploy": handler}, resume=True)
    replayed = backend.execute(spec, {"deploy": handler}, resume=True)

    assert completed.status is RunResultStatus.COMPLETED
    assert replayed.status is RunResultStatus.COMPLETED
    assert calls == ["deploy"]
    assert [item.node_id for item in completed.results] == ["deploy"]


def test_native_backend_returns_cancelled_run_without_invoking_handlers(
    tmp_path: Path,
) -> None:
    spec = RunSpec(
        run_id="run-cancelled",
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
    backend._write_spec_manifest(spec)
    backend.store.cancel(spec.run_id, reason="operator", idempotency_key="cancel")

    result = backend.execute(
        spec,
        {"execute": lambda node: pytest.fail(f"handler ran for {node.node_id}")},
        resume=True,
    )

    assert result.status is RunResultStatus.CANCELLED
    assert result.results == ()


def test_native_backend_cancels_downstream_pending_nodes_on_skip(
    tmp_path: Path,
) -> None:
    session_id = start_session(tmp_path, label="cancel trace")
    assert session_id is not None
    spec = RunSpec(
        run_id="run-skip-cancel",
        task="Build feature",
        nodes=(
            _node("gate", side_effecting=True),
            _node("execute", dependencies=("gate",), side_effecting=True),
        ),
    )
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "runtime"), repo_root=tmp_path)

    def handler(node: NodeSpec) -> NodeResult:
        return NodeResult(
            node_id=node.node_id,
            status=NodeResultStatus.SKIPPED,
            idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
            error="operator cancelled",
        )

    result = backend.execute(spec, {"gate": handler, "execute": handler})

    assert result.status is RunResultStatus.CANCELLED
    snapshot = backend.store.load(spec.run_id)
    assert snapshot.state.value == "cancelled"
    assert snapshot.nodes["gate"].state.value == "cancelled"
    assert snapshot.nodes["execute"].state.value == "cancelled"
    _, events = load_session_events(
        tmp_path,
        session_id,
        include_notify_window=False,
    )
    runtime_events = [event for event in events if event.kind == TraceEventKind.RUNTIME_NODE]
    assert len(runtime_events) == 2
    by_node = {event.payload["node_id"]: event.payload for event in runtime_events}
    assert by_node["gate"]["status"] == "skipped"
    assert by_node["gate"]["error"] == "operator cancelled"
    assert by_node["execute"]["status"] == "cancelled"
    assert by_node["execute"]["error"] == "operator cancelled"
    assert by_node["execute"]["dependencies"] == ["gate"]


def test_native_backend_exhausts_retry_policy_before_failed_result(
    tmp_path: Path,
) -> None:
    spec = RunSpec(
        run_id="run-retry-failed-result",
        task="Build feature",
        nodes=(_node("execute", side_effecting=True),),
    )
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "runtime"), repo_root=tmp_path)
    calls: list[int] = []

    def handler(node: NodeSpec) -> NodeResult:
        calls.append(len(calls) + 1)
        return NodeResult(
            node_id=node.node_id,
            status=NodeResultStatus.FAILED,
            idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
            error="temporarily unavailable",
        )

    result = backend.execute(spec, {"execute": handler})

    assert result.status is RunResultStatus.FAILED
    assert result.error == "temporarily unavailable"
    assert calls == [1, 2]
    retry_history = backend.store.load(spec.run_id).nodes["execute"].retry_history
    assert len(retry_history) == 1
    assert retry_history[0].attempt == 1
    assert retry_history[0].retryable is True
    assert len(result.results) == 1


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
    assert execute.retry_policy == RetryPolicy(max_attempts=3, backoff_seconds=1.0)
    assert ("pytest", "tests/billing") in verify.capabilities.commands
    assert spec.metadata["source"] == "harness_run.ExecutionPlan"


def test_runtime_contract_exposes_honest_adapter_capabilities(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    dependencies = ControllerDependencies(
        context_engine=HarnessController(tmp_path).dependencies.context_engine,
        runtime_store=RuntimeStore(tmp_path / ".onmc" / "harness-runtime"),
        policy_decider=AllowPolicy(),
        loop_executor=loop,
    )
    plan = HarnessController(tmp_path, dependencies=dependencies).run(
        RunRequest(
            task="Refactor auth flow",
            plan_only=True,
            agent="codex",
            model="gpt-test",
        )
    ).plan

    spec = plan.to_run_spec()
    capability = spec.metadata["adapter_capability"]

    assert capability == adapter_capability_payload("codex")
    assert capability["agent"] == "codex"
    assert capability["cost"] == "not_reported"
    assert capability["tokens"] == "best_effort_human_stdout_parse"
    assert "Cost is never reported" in " ".join(capability["limitations"])
    assert all(node.metadata["adapter_capability"] == capability for node in spec.nodes)


def test_runtime_contract_exposes_declared_isolation_profile(tmp_path: Path) -> None:
    loop = FakeLoop(_loop_result(converged=True))
    dependencies = ControllerDependencies(
        context_engine=HarnessController(tmp_path).dependencies.context_engine,
        runtime_store=RuntimeStore(tmp_path / ".onmc" / "harness-runtime"),
        policy_decider=AllowPolicy(),
        loop_executor=loop,
    )
    plan = HarnessController(tmp_path, dependencies=dependencies).run(
        RunRequest(
            task="Refactor safely",
            plan_only=True,
            isolation=True,
        )
    ).plan

    spec = plan.to_run_spec()
    isolation = spec.metadata["isolation_profile"]

    assert isolation == plan.isolation_profile.to_dict()
    assert isolation["requested"] is True
    assert isolation["mode"] == "git_worktree_required"
    assert isolation["network"] == "not constrained by ONMC"
    assert "not a container or microVM" in " ".join(isolation["limitations"])
    assert all(node.metadata["isolation_profile"] == isolation for node in spec.nodes)


def _completion_evidence(node: NodeSpec) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            evidence_id=f"{node.node_id}:completion",
            kind="completion",
            uri=f"onmc://runtime/{node.node_id}/completion",
            digest="sha256:" + ("0" * 64),
        ),
    )
