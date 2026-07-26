"""Native ONMC execution backend backed by the durable event store."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from oh_no_my_claudecode.durable_runtime import (
    InvalidTransitionError,
    NodeState,
    RunNotFoundError,
    RunSnapshot,
    RunState,
    RuntimeStore,
)
from oh_no_my_claudecode.runtime.backend import NodeHandler
from oh_no_my_claudecode.runtime.contracts import (
    NodeResult,
    NodeResultStatus,
    RunResult,
    RunResultStatus,
    RunSpec,
    RuntimeContractError,
)


class NativeExecutionBackend:
    """Execute a ``RunSpec`` with local event-sourced replay semantics."""

    backend_name = "native"

    def __init__(self, store: RuntimeStore, *, repo_root: Path | None = None) -> None:
        self.store = store
        self.repo_root = None if repo_root is None else Path(repo_root)

    def execute(
        self,
        spec: RunSpec,
        handlers: Mapping[str, NodeHandler],
        *,
        resume: bool = False,
    ) -> RunResult:
        missing_handlers = [
            node.node_id
            for node in spec.topological_order()
            if node.node_id not in handlers and not self._has_result(spec.run_id, node.node_id)
        ]
        if missing_handlers:
            raise RuntimeContractError(f"missing node handlers: {missing_handlers}")

        snapshot = self._load_or_create(spec, resume=resume)
        if snapshot.state is RunState.COMPLETED:
            return RunResult(
                run_id=spec.run_id,
                status=RunResultStatus.COMPLETED,
                results=self._load_results(spec),
                backend=self.backend_name,
                spec_digest=spec.digest,
            )
        if snapshot.state is not RunState.RUNNING:
            snapshot = self.store.start(spec.run_id, idempotency_key="runtime:start")

        results: list[NodeResult] = []
        try:
            for node in spec.topological_order():
                current = self.store.load(spec.run_id)
                state = current.nodes[node.node_id].state
                if state is NodeState.SUCCEEDED:
                    results.append(self._load_result(spec.run_id, node.node_id))
                    continue
                if self._has_result(spec.run_id, node.node_id):
                    result = self._load_result(spec.run_id, node.node_id)
                    self._apply_persisted_result(spec.run_id, result)
                    results.append(result)
                    if result.status is NodeResultStatus.SUCCEEDED:
                        continue
                    if result.status is NodeResultStatus.SKIPPED:
                        return RunResult(
                            run_id=spec.run_id,
                            status=RunResultStatus.CANCELLED,
                            results=tuple(results),
                            backend=self.backend_name,
                            spec_digest=spec.digest,
                            error=result.error,
                        )
                    return RunResult(
                        run_id=spec.run_id,
                        status=RunResultStatus.FAILED,
                        results=tuple(results),
                        backend=self.backend_name,
                        spec_digest=spec.digest,
                        error=result.error,
                    )
                if any(
                    current.nodes[dependency].state is not NodeState.SUCCEEDED
                    for dependency in node.dependencies
                ):
                    raise RuntimeContractError(
                        f"node {node.node_id!r} has unsatisfied dependencies"
                    )
                if state is NodeState.PENDING:
                    self.store.start_node(
                        spec.run_id,
                        node.node_id,
                        idempotency_key=f"runtime:{node.node_id}:start",
                    )
                result = handlers[node.node_id](node)
                if result.node_id != node.node_id:
                    raise RuntimeContractError(
                        f"handler for {node.node_id!r} returned result for {result.node_id!r}"
                    )
                if result.idempotency_key != (node.idempotency_key or f"runtime:{node.node_id}"):
                    raise RuntimeContractError(
                        f"handler for {node.node_id!r} returned wrong idempotency key"
                    )
                self._write_result(spec.run_id, result)
                results.append(result)
                if result.status is NodeResultStatus.SUCCEEDED:
                    self.store.complete_node(
                        spec.run_id,
                        node.node_id,
                        idempotency_key=f"runtime:{node.node_id}:complete",
                    )
                elif result.status is NodeResultStatus.SKIPPED:
                    self.store.cancel_node(
                        spec.run_id,
                        node.node_id,
                        reason=result.error or "skipped",
                        idempotency_key=f"runtime:{node.node_id}:skip",
                    )
                    self.store.cancel(
                        spec.run_id,
                        reason=result.error or f"{node.node_id} skipped",
                        idempotency_key="runtime:cancel",
                    )
                    return RunResult(
                        run_id=spec.run_id,
                        status=RunResultStatus.CANCELLED,
                        results=tuple(results),
                        backend=self.backend_name,
                        spec_digest=spec.digest,
                        error=result.error,
                    )
                else:
                    self.store.fail_node(
                        spec.run_id,
                        node.node_id,
                        reason=result.error or "failed",
                        idempotency_key=f"runtime:{node.node_id}:fail",
                    )
                    self.store.fail(
                        spec.run_id,
                        reason=result.error or f"{node.node_id} failed",
                        idempotency_key="runtime:fail",
                    )
                    return RunResult(
                        run_id=spec.run_id,
                        status=RunResultStatus.FAILED,
                        results=tuple(results),
                        backend=self.backend_name,
                        spec_digest=spec.digest,
                        error=result.error,
                    )
            self.store.complete(spec.run_id, idempotency_key="runtime:complete")
            return RunResult(
                run_id=spec.run_id,
                status=RunResultStatus.COMPLETED,
                results=tuple(results),
                backend=self.backend_name,
                spec_digest=spec.digest,
            )
        except Exception as exc:
            self._fail_running_node(spec.run_id, str(exc))
            return RunResult(
                run_id=spec.run_id,
                status=RunResultStatus.FAILED,
                results=tuple(results),
                backend=self.backend_name,
                spec_digest=spec.digest,
                error=str(exc),
            )

    def _load_or_create(self, spec: RunSpec, *, resume: bool) -> RunSnapshot:
        try:
            snapshot = self.store.load(spec.run_id)
        except RunNotFoundError:
            if resume:
                raise
            return self.store.create_run(
                spec.run_id,
                node_ids=tuple(node.node_id for node in spec.nodes),
                repo=self.repo_root,
                idempotency_key="runtime:create",
            )
        existing_nodes = tuple(snapshot.nodes)
        requested_nodes = tuple(node.node_id for node in spec.nodes)
        if existing_nodes != requested_nodes:
            raise RuntimeContractError("stored run nodes do not match the RunSpec")
        return snapshot

    def _fail_running_node(self, run_id: str, reason: str) -> None:
        try:
            snapshot = self.store.load(run_id)
        except RunNotFoundError:
            return
        if snapshot.state is not RunState.RUNNING:
            return
        running = next(
            (node for node in snapshot.nodes.values() if node.state is NodeState.RUNNING),
            None,
        )
        try:
            if running is not None:
                self.store.fail_node(
                    run_id,
                    running.node_id,
                    reason=reason,
                    idempotency_key=f"runtime:{running.node_id}:exception",
                )
            self.store.fail(run_id, reason=reason, idempotency_key="runtime:exception")
        except InvalidTransitionError:
            return

    def _apply_persisted_result(self, run_id: str, result: NodeResult) -> None:
        try:
            snapshot = self.store.load(run_id)
            node_state = snapshot.nodes[result.node_id].state
            if snapshot.state is not RunState.RUNNING:
                snapshot = self.store.resume(run_id, idempotency_key="runtime:resume")
            if node_state is NodeState.PENDING:
                self.store.start_node(
                    run_id,
                    result.node_id,
                    idempotency_key=f"runtime:{result.node_id}:start",
                )
            elif node_state is not NodeState.RUNNING:
                self.store.resume_node(
                    run_id,
                    result.node_id,
                    idempotency_key=f"runtime:{result.node_id}:resume",
                )
            if result.status is NodeResultStatus.SUCCEEDED:
                self.store.complete_node(
                    run_id,
                    result.node_id,
                    idempotency_key=f"runtime:{result.node_id}:complete",
                )
            elif result.status is NodeResultStatus.SKIPPED:
                reason = result.error or "skipped"
                self.store.cancel_node(
                    run_id,
                    result.node_id,
                    reason=reason,
                    idempotency_key=f"runtime:{result.node_id}:skip",
                )
                self.store.cancel(run_id, reason=reason, idempotency_key="runtime:cancel")
            else:
                reason = result.error or "failed"
                self.store.fail_node(
                    run_id,
                    result.node_id,
                    reason=reason,
                    idempotency_key=f"runtime:{result.node_id}:fail",
                )
                self.store.fail(run_id, reason=reason, idempotency_key="runtime:fail")
        except InvalidTransitionError:
            return

    def _result_path(self, run_id: str, node_id: str) -> Path:
        return self.store.root / "runs" / run_id / "node-results" / f"{node_id}.json"

    def _has_result(self, run_id: str, node_id: str) -> bool:
        return self._result_path(run_id, node_id).exists()

    def _write_result(self, run_id: str, result: NodeResult) -> None:
        path = self._result_path(run_id, result.node_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _load_result(self, run_id: str, node_id: str) -> NodeResult:
        path = self._result_path(run_id, node_id)
        if not path.exists():
            return NodeResult(
                node_id=node_id,
                status=NodeResultStatus.SKIPPED,
                idempotency_key=f"runtime:{node_id}",
                error="completed node is missing its persisted result",
            )
        return NodeResult.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def _load_results(self, spec: RunSpec) -> tuple[NodeResult, ...]:
        return tuple(
            self._load_result(spec.run_id, node.node_id) for node in spec.topological_order()
        )
