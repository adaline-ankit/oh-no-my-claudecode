"""Contract tests for the optional LangGraph runtime backend."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from oh_no_my_claudecode.durable_runtime import RuntimeStore
from oh_no_my_claudecode.runtime import (
    Budget,
    CapabilitySet,
    EvidenceRef,
    LangGraphExecutionBackend,
    LangGraphUnavailableError,
    NativeExecutionBackend,
    NodeResult,
    NodeResultStatus,
    NodeSpec,
    RetryPolicy,
    RunResultStatus,
    RunSpec,
    langgraph_available,
)
from oh_no_my_claudecode.runtime.checkpoint_codec import (
    CheckpointCodecError,
    decode_checkpoint,
    encode_checkpoint,
)


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
        completion_condition=f"{node_id} completed" if side_effecting else None,
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


def _spec(run_id: str = "run-langgraph") -> RunSpec:
    return RunSpec(
        run_id=run_id,
        task="Exercise backend parity",
        nodes=(
            _node("plan"),
            _node("execute", dependencies=("plan",), side_effecting=True),
            _node("verify", dependencies=("execute",)),
        ),
    )


def _result(node: NodeSpec) -> NodeResult:
    evidence = (
        EvidenceRef(
            evidence_id=f"evidence:{node.node_id}",
            kind="completion",
            uri=f"onmc://{node.node_id}",
            digest=f"sha256:{node.node_id}",
        ),
    )
    return NodeResult(
        node_id=node.node_id,
        status=NodeResultStatus.SUCCEEDED,
        idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
        output={"node": node.node_id},
        evidence=evidence if node.side_effecting else (),
    )


class _SequentialDriver:
    """Dependency-free driver used to exercise ONMC semantics offline."""

    def run(
        self,
        spec: RunSpec,
        execute_node: Callable[[NodeSpec], None],
        *,
        resume: bool,
    ) -> None:
        del resume
        for node in spec.topological_order():
            execute_node(node)


class _SimulatedCrash(BaseException):
    pass


class _CrashAfterNodeDriver:
    def __init__(self, target: str) -> None:
        self.target = target
        self.crashed = False

    def run(
        self,
        spec: RunSpec,
        execute_node: Callable[[NodeSpec], None],
        *,
        resume: bool,
    ) -> None:
        del resume
        for node in spec.topological_order():
            execute_node(node)
            if node.node_id == self.target and not self.crashed:
                self.crashed = True
                raise _SimulatedCrash(node.node_id)


def test_native_backend_remains_usable_without_langgraph(tmp_path: Path) -> None:
    backend = NativeExecutionBackend(RuntimeStore(tmp_path / "native"), repo_root=tmp_path)
    spec = RunSpec(run_id="native-only", task="Run native", nodes=(_node("plan"),))

    result = backend.execute(spec, {"plan": _result})

    assert result.status is RunResultStatus.COMPLETED
    assert result.backend == "native"


def test_default_langgraph_backend_fails_closed_when_extra_is_absent(tmp_path: Path) -> None:
    if langgraph_available():
        pytest.skip("LangGraph optional dependencies are installed")
    backend = LangGraphExecutionBackend(
        RuntimeStore(tmp_path / "langgraph"),
        repo_root=tmp_path,
    )

    with pytest.raises(LangGraphUnavailableError, match="optional LangGraph dependencies"):
        backend.execute(_spec(), {node.node_id: _result for node in _spec().nodes})
    assert not (backend.store.root / "runs" / _spec().run_id).exists()


def test_injected_driver_matches_native_terminal_contract(tmp_path: Path) -> None:
    spec = _spec()
    native = NativeExecutionBackend(RuntimeStore(tmp_path / "native"), repo_root=tmp_path)
    langgraph = LangGraphExecutionBackend(
        RuntimeStore(tmp_path / "langgraph"),
        repo_root=tmp_path,
        driver=_SequentialDriver(),
    )
    handlers = {node.node_id: _result for node in spec.nodes}

    native_result = native.execute(spec, handlers)
    langgraph_result = langgraph.execute(spec, handlers)

    assert langgraph_result.status is native_result.status
    assert langgraph_result.spec_digest == native_result.spec_digest
    assert [item.to_dict() for item in langgraph_result.results] == [
        item.to_dict() for item in native_result.results
    ]
    assert langgraph_result.backend == "langgraph"
    native_snapshot = native.store.load(spec.run_id)
    langgraph_snapshot = langgraph.store.load(spec.run_id)
    assert langgraph_snapshot.state is native_snapshot.state
    assert {
        node_id: node.state for node_id, node in langgraph_snapshot.nodes.items()
    } == {node_id: node.state for node_id, node in native_snapshot.nodes.items()}


def test_interrupt_resume_does_not_duplicate_side_effect_with_injected_driver(
    tmp_path: Path,
) -> None:
    deploy = _node("deploy", side_effecting=True, approval_required=True)
    spec = RunSpec(run_id="approval", task="Deploy", nodes=(deploy,))
    backend = LangGraphExecutionBackend(
        RuntimeStore(tmp_path / "runtime"),
        repo_root=tmp_path,
        driver=_SequentialDriver(),
    )
    calls: list[str] = []

    def handler(node: NodeSpec) -> NodeResult:
        calls.append(node.node_id)
        return _result(node)

    interrupted = backend.execute(spec, {"deploy": handler})
    assert interrupted.status is RunResultStatus.INTERRUPTED
    assert calls == []

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


def test_resume_reuses_result_persisted_before_driver_crash(tmp_path: Path) -> None:
    execute = _node("execute", side_effecting=True)
    spec = RunSpec(run_id="crash-replay", task="Write once", nodes=(execute,))
    backend = LangGraphExecutionBackend(
        RuntimeStore(tmp_path / "runtime"),
        repo_root=tmp_path,
        driver=_SequentialDriver(),
    )
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
    persisted = _result(execute)
    backend._write_result(spec.run_id, persisted)

    def must_not_run(node: NodeSpec) -> NodeResult:
        raise AssertionError(f"duplicated side effect for {node.node_id}")

    recovered = backend.execute(spec, {"execute": must_not_run}, resume=True)

    assert recovered.status is RunResultStatus.COMPLETED
    assert [item.to_dict() for item in recovered.results] == [persisted.to_dict()]


@pytest.mark.parametrize("crash_after", ["plan", "execute", "verify"])
def test_crash_after_each_node_resumes_without_duplicate_handler(
    tmp_path: Path,
    crash_after: str,
) -> None:
    spec = _spec(f"crash-after-{crash_after}")
    driver = _CrashAfterNodeDriver(crash_after)
    backend = LangGraphExecutionBackend(
        RuntimeStore(tmp_path / "runtime"),
        repo_root=tmp_path,
        driver=driver,
    )
    calls: list[str] = []

    def handler(node: NodeSpec) -> NodeResult:
        calls.append(node.node_id)
        return _result(node)

    with pytest.raises(_SimulatedCrash, match=crash_after):
        backend.execute(spec, {node.node_id: handler for node in spec.nodes})

    completed = backend.execute(
        spec,
        {node.node_id: handler for node in spec.nodes},
        resume=True,
    )

    assert completed.status is RunResultStatus.COMPLETED
    assert calls == ["plan", "execute", "verify"]


def test_checkpoint_codec_round_trips_current_schema() -> None:
    encoded = encode_checkpoint(
        spec_digest="abc123",
        completed_node_ids=("plan", "execute"),
    )

    decoded = decode_checkpoint(encoded, expected_spec_digest="abc123")

    assert decoded.spec_digest == "abc123"
    assert decoded.completed_node_ids == ("plan", "execute")


def test_checkpoint_codec_rejects_unknown_schema_without_mutating_payload() -> None:
    payload = encode_checkpoint(spec_digest="abc123", completed_node_ids=("plan",))
    payload["schema_version"] = 999
    original = dict(payload)

    with pytest.raises(CheckpointCodecError, match="unsupported checkpoint schema"):
        decode_checkpoint(payload, expected_spec_digest="abc123")

    assert payload == original


@pytest.mark.skipif(not langgraph_available(), reason="LangGraph optional extra not installed")
def test_real_langgraph_driver_matches_native_terminal_contract(tmp_path: Path) -> None:
    spec = _spec("real-langgraph")
    native = NativeExecutionBackend(RuntimeStore(tmp_path / "native"), repo_root=tmp_path)
    langgraph = LangGraphExecutionBackend(
        RuntimeStore(tmp_path / "langgraph"),
        repo_root=tmp_path,
    )
    handlers = {node.node_id: _result for node in spec.nodes}

    native_result = native.execute(spec, handlers)
    langgraph_result = langgraph.execute(spec, handlers)

    assert langgraph_result.status is native_result.status
    assert [item.to_dict() for item in langgraph_result.results] == [
        item.to_dict() for item in native_result.results
    ]
