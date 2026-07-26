from __future__ import annotations

import threading
import time
from pathlib import Path

from oh_no_my_claudecode.durable_runtime import RuntimeStore
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
    dependency_layers,
)


def _node(node_id: str, *, dependencies: tuple[str, ...] = ()) -> NodeSpec:
    return NodeSpec(
        node_id=node_id,
        kind="test",
        objective=f"Run {node_id}",
        completion_condition=f"{node_id} completed with evidence",
        dependencies=dependencies,
        side_effecting=True,
        approval_required=False,
        idempotency_key=f"idem:{node_id}",
        timeout_seconds=30.0,
        budget=Budget(timeout_seconds=30.0, max_tokens=100),
        retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=0.0),
        capabilities=CapabilitySet(tools=("edit",), filesystem_write=True),
    )


def _result(node: NodeSpec) -> NodeResult:
    return NodeResult(
        node_id=node.node_id,
        status=NodeResultStatus.SUCCEEDED,
        idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
        evidence=(
            EvidenceRef(
                evidence_id=f"{node.node_id}:completion",
                kind="completion",
                uri=f"onmc://runtime/{node.node_id}/completion",
                digest="sha256:" + ("1" * 64),
            ),
        ),
    )


def test_dependency_layers_preserve_source_order_within_ready_sets() -> None:
    spec = RunSpec(
        run_id="run-layers",
        task="Layer graph",
        nodes=(
            _node("plan"),
            _node("a", dependencies=("plan",)),
            _node("b", dependencies=("plan",)),
            _node("join", dependencies=("a", "b")),
        ),
    )

    assert [[node.node_id for node in layer] for layer in dependency_layers(spec)] == [
        ["plan"],
        ["a", "b"],
        ["join"],
    ]


def test_native_backend_fans_out_ready_nodes_and_fans_in_deterministically(
    tmp_path: Path,
) -> None:
    spec = RunSpec(
        run_id="run-parallel",
        task="Parallel graph",
        nodes=(
            _node("a"),
            _node("b"),
            _node("join", dependencies=("a", "b")),
        ),
    )
    backend = NativeExecutionBackend(
        RuntimeStore(tmp_path / "runtime"),
        repo_root=tmp_path,
        max_workers=2,
    )
    entered: list[str] = []
    lock = threading.Lock()
    both_roots_entered = threading.Event()

    def handler(node: NodeSpec) -> NodeResult:
        if node.node_id in {"a", "b"}:
            with lock:
                entered.append(node.node_id)
                if set(entered) == {"a", "b"}:
                    both_roots_entered.set()
            assert both_roots_entered.wait(2), "ready roots did not execute concurrently"
            if node.node_id == "a":
                time.sleep(0.05)
        else:
            assert both_roots_entered.is_set()
        return _result(node)

    result = backend.execute(spec, {"a": handler, "b": handler, "join": handler})

    assert result.status is RunResultStatus.COMPLETED
    assert [item.node_id for item in result.results] == ["a", "b", "join"]
    snapshot = backend.store.load(spec.run_id)
    assert [snapshot.nodes[node_id].state.value for node_id in ("a", "b", "join")] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]


def test_native_backend_parallel_contract_error_fails_all_running_nodes(
    tmp_path: Path,
) -> None:
    spec = RunSpec(
        run_id="run-parallel-contract-error",
        task="Parallel graph",
        nodes=(_node("a"), _node("b")),
    )
    backend = NativeExecutionBackend(
        RuntimeStore(tmp_path / "runtime"),
        repo_root=tmp_path,
        max_workers=2,
    )

    def handler(node: NodeSpec) -> NodeResult:
        if node.node_id == "a":
            return NodeResult(
                node_id=node.node_id,
                status=NodeResultStatus.SUCCEEDED,
                idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
            )
        time.sleep(0.05)
        return _result(node)

    result = backend.execute(spec, {"a": handler, "b": handler})

    assert result.status is RunResultStatus.FAILED
    assert result.error is not None
    assert "completion evidence" in result.error
    snapshot = backend.store.load(spec.run_id)
    assert [snapshot.nodes[node_id].state.value for node_id in ("a", "b")] == [
        "failed",
        "failed",
    ]
