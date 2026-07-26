"""Native ONMC execution backend backed by the durable event store."""

from __future__ import annotations

import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from oh_no_my_claudecode.durable_runtime import (
    InvalidTransitionError,
    NodeState,
    RetryClass,
    RunNotFoundError,
    RunSnapshot,
    RunState,
    RuntimeStore,
    classify_retry,
)
from oh_no_my_claudecode.runtime.backend import NodeHandler
from oh_no_my_claudecode.runtime.contracts import (
    NodeResult,
    NodeResultStatus,
    NodeSpec,
    RunResult,
    RunResultStatus,
    RunSpec,
    RuntimeContractError,
)
from oh_no_my_claudecode.runtime.fanout import dependency_layers


class NativeExecutionBackend:
    """Execute a ``RunSpec`` with local event-sourced replay semantics."""

    backend_name = "native"

    def __init__(
        self,
        store: RuntimeStore,
        *,
        repo_root: Path | None = None,
        max_workers: int = 1,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self.store = store
        self.repo_root = None if repo_root is None else Path(repo_root)
        self.max_workers = max_workers

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
        if snapshot.state is RunState.AWAITING_APPROVAL:
            return self._interrupted_result(spec, results=[])
        if snapshot.state is not RunState.RUNNING:
            snapshot = self.store.start(spec.run_id, idempotency_key="runtime:start")

        results: list[NodeResult] = []
        try:
            for layer in dependency_layers(spec):
                current = self.store.load(spec.run_id)
                ready_nodes: list[NodeSpec] = []
                for node in layer:
                    state = current.nodes[node.node_id].state
                    if state is NodeState.SUCCEEDED:
                        result = self._load_result(spec.run_id, node.node_id)
                        self._validate_node_result(node, result)
                        results.append(result)
                        continue
                    if state is NodeState.AWAITING_APPROVAL:
                        return self._interrupted_result(spec, results, node=node)
                    if self._has_result(spec.run_id, node.node_id):
                        result = self._load_result(spec.run_id, node.node_id)
                        self._validate_node_result(node, result)
                        self._apply_persisted_result(spec.run_id, result)
                        results.append(result)
                        if result.status is NodeResultStatus.SUCCEEDED:
                            continue
                        return self._terminal_result_from_node_result(spec, results, result)
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
                        state = NodeState.RUNNING
                    if (
                        node.approval_required
                        and state is NodeState.RUNNING
                        and not self._node_has_approval(spec.run_id, node.node_id)
                    ):
                        self.store.request_node_approval(
                            spec.run_id,
                            node.node_id,
                            reason=f"approval required before {node.node_id}",
                            idempotency_key=f"runtime:{node.node_id}:approval-request",
                        )
                        self.store.request_approval(
                            spec.run_id,
                            reason=f"approval required before {node.node_id}",
                            idempotency_key=f"runtime:{node.node_id}:run-approval-request",
                        )
                        return self._interrupted_result(spec, results, node=node)
                    ready_nodes.append(node)
                for node, result in self._run_ready_nodes(spec.run_id, ready_nodes, handlers):
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
                        return self._terminal_result_from_node_result(spec, results, result)
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
                        return self._terminal_result_from_node_result(spec, results, result)
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
            snapshot = self.store.create_run(
                spec.run_id,
                node_ids=tuple(node.node_id for node in spec.nodes),
                repo=self.repo_root,
                idempotency_key="runtime:create",
            )
            self._write_spec_manifest(spec)
            return snapshot
        existing_nodes = tuple(snapshot.nodes)
        requested_nodes = tuple(node.node_id for node in spec.nodes)
        if existing_nodes != requested_nodes:
            raise RuntimeContractError("stored run nodes do not match the RunSpec")
        self._validate_stored_spec_manifest(spec)
        return snapshot

    def _fail_running_node(self, run_id: str, reason: str) -> None:
        try:
            snapshot = self.store.load(run_id)
        except RunNotFoundError:
            return
        if snapshot.state is not RunState.RUNNING:
            return
        running_nodes = tuple(
            node for node in snapshot.nodes.values() if node.state is NodeState.RUNNING
        )
        try:
            for running in running_nodes:
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

    def _run_ready_nodes(
        self,
        run_id: str,
        nodes: list[NodeSpec],
        handlers: Mapping[str, NodeHandler],
    ) -> list[tuple[NodeSpec, NodeResult]]:
        if not nodes:
            return []
        if self.max_workers == 1 or len(nodes) == 1:
            results: list[tuple[NodeSpec, NodeResult]] = []
            for node in nodes:
                result = self._run_node_with_retries(run_id, node, handlers[node.node_id])
                results.append((node, result))
                if result.status is not NodeResultStatus.SUCCEEDED:
                    break
            return results
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(nodes))) as executor:
            futures = [
                executor.submit(
                    self._run_node_with_retries,
                    run_id,
                    node,
                    handlers[node.node_id],
                )
                for node in nodes
            ]
            return [(node, future.result()) for node, future in zip(nodes, futures, strict=True)]

    def _terminal_result_from_node_result(
        self,
        spec: RunSpec,
        results: list[NodeResult],
        result: NodeResult,
    ) -> RunResult:
        status = (
            RunResultStatus.CANCELLED
            if result.status is NodeResultStatus.SKIPPED
            else RunResultStatus.FAILED
        )
        return RunResult(
            run_id=spec.run_id,
            status=status,
            results=tuple(results),
            backend=self.backend_name,
            spec_digest=spec.digest,
            error=result.error,
        )

    def _interrupted_result(
        self,
        spec: RunSpec,
        results: list[NodeResult],
        *,
        node: NodeSpec | None = None,
    ) -> RunResult:
        target = "run" if node is None else f"node {node.node_id}"
        return RunResult(
            run_id=spec.run_id,
            status=RunResultStatus.INTERRUPTED,
            results=tuple(results),
            backend=self.backend_name,
            spec_digest=spec.digest,
            error=f"approval required for {target}",
        )

    def _node_has_approval(self, run_id: str, node_id: str) -> bool:
        for event in self.store.events(run_id):
            if event.event_type != "node_transition":
                continue
            if event.payload.get("node_id") != node_id:
                continue
            if event.payload.get("to") == NodeState.RUNNING.value and event.payload.get(
                "approved_by"
            ):
                return True
        return False

    def _run_node_with_retries(
        self,
        run_id: str,
        node: NodeSpec,
        handler: NodeHandler,
    ) -> NodeResult:
        """Run one node, recording retry attempts before any terminal result."""
        while True:
            try:
                result = handler(node)
                self._validate_node_result(node, result)
            except RuntimeContractError:
                raise
            except Exception as exc:
                if self._record_retry_if_allowed(run_id, node, exc):
                    continue
                return NodeResult(
                    node_id=node.node_id,
                    status=NodeResultStatus.FAILED,
                    idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
                    error=str(exc),
                )
            if result.status is not NodeResultStatus.FAILED:
                return result
            reason = result.error or "failed"
            if self._record_retry_if_allowed(run_id, node, reason):
                continue
            return result

    def _record_retry_if_allowed(
        self,
        run_id: str,
        node: NodeSpec,
        error: BaseException | str,
    ) -> bool:
        policy = node.retry_policy
        if policy is None:
            return False
        classification = classify_retry(error)
        if classification is RetryClass.PERMANENT:
            return False
        snapshot = self.store.load(run_id)
        retries_used = snapshot.nodes[node.node_id].attempts
        if retries_used + 1 >= policy.max_attempts:
            return False
        self.store.record_retry(
            run_id,
            node.node_id,
            classification=classification,
            reason=str(error),
            base_delay_seconds=policy.backoff_seconds,
            max_delay_seconds=policy.backoff_seconds,
            idempotency_key=f"runtime:{node.node_id}:retry:{retries_used + 1}",
        )
        return True

    def _validate_node_result(self, node: NodeSpec, result: NodeResult) -> None:
        node_id = node.node_id
        if result.node_id != node_id:
            raise RuntimeContractError(
                f"handler for {node_id!r} returned result for {result.node_id!r}"
            )
        expected_key = node.idempotency_key or f"runtime:{node_id}"
        if result.idempotency_key != expected_key:
            raise RuntimeContractError(f"handler for {node_id!r} returned wrong idempotency key")
        if (
            node.side_effecting
            and result.status is NodeResultStatus.SUCCEEDED
            and not any(item.kind == "completion" and item.digest for item in result.evidence)
        ):
            raise RuntimeContractError(
                f"successful side-effecting node {node_id!r} requires digest-backed "
                "completion evidence"
            )

    def _spec_path(self, run_id: str) -> Path:
        return self.store.root / "runs" / run_id / "runtime-spec.json"

    def _write_spec_manifest(self, spec: RunSpec) -> None:
        path = self._spec_path(spec.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": spec.schema_version,
            "run_id": spec.run_id,
            "spec_digest": spec.digest,
            "spec": spec.to_dict(),
        }
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _validate_stored_spec_manifest(self, spec: RunSpec) -> None:
        path = self._spec_path(spec.run_id)
        if not path.exists():
            raise RuntimeContractError("stored run is missing its RunSpec manifest")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeContractError("stored RunSpec manifest must be an object")
        if raw.get("run_id") != spec.run_id:
            raise RuntimeContractError("stored RunSpec manifest run_id mismatch")
        if raw.get("schema_version") != spec.schema_version:
            raise RuntimeContractError("stored RunSpec schema mismatch")
        if raw.get("spec_digest") != spec.digest:
            raise RuntimeContractError("stored RunSpec digest does not match requested spec")

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
        results: list[NodeResult] = []
        for node in spec.topological_order():
            result = self._load_result(spec.run_id, node.node_id)
            self._validate_node_result(node, result)
            results.append(result)
        return tuple(results)
