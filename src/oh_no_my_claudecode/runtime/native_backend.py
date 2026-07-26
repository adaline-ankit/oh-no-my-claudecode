"""Native ONMC execution backend backed by the durable event store."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from oh_no_my_claudecode.durable_runtime import (
    InvalidTransitionError,
    Lease,
    LeaseExpiredError,
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
from oh_no_my_claudecode.trace.models import TraceEvent, TraceEventKind
from oh_no_my_claudecode.trace.recorder import record_trace_event


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

        execute_started_at = time.time()
        snapshot = self._load_or_create(spec, resume=resume)
        if snapshot.state is RunState.COMPLETED:
            return self._result_with_run_event(
                spec,
                status=RunResultStatus.COMPLETED,
                results=self._load_results(spec),
                started_at=execute_started_at,
            )
        if snapshot.state is RunState.AWAITING_APPROVAL:
            return self._interrupted_result(spec, results=[], started_at=execute_started_at)
        if snapshot.state is RunState.CANCELLED:
            return self._cancelled_result(spec, results=[], started_at=execute_started_at)
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
                    if state is NodeState.CANCELLED:
                        return self._cancelled_result(
                            spec,
                            results,
                            started_at=execute_started_at,
                        )
                    if state is NodeState.AWAITING_APPROVAL:
                        return self._interrupted_result(
                            spec,
                            results,
                            node=node,
                            started_at=execute_started_at,
                        )
                    if self._has_result(spec.run_id, node.node_id):
                        result = self._load_result(spec.run_id, node.node_id)
                        self._validate_node_result(node, result)
                        self._apply_persisted_result(spec.run_id, result)
                        results.append(result)
                        if result.status is NodeResultStatus.SUCCEEDED:
                            continue
                        if result.status is NodeResultStatus.SKIPPED:
                            self._cancel_pending_nodes(
                                spec,
                                reason=result.error or f"{node.node_id} skipped",
                            )
                            self.store.cancel(
                                spec.run_id,
                                reason=result.error or f"{node.node_id} skipped",
                                idempotency_key="runtime:cancel",
                            )
                        return self._terminal_result_from_node_result(
                            spec,
                            results,
                            result,
                            started_at=execute_started_at,
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
                        state = NodeState.RUNNING
                    if (
                        node.approval_required
                        and state is NodeState.RUNNING
                        and not self._node_has_approval(spec.run_id, node.node_id)
                    ):
                        reason = f"approval required before {node.node_id}"
                        self.store.request_node_approval(
                            spec.run_id,
                            node.node_id,
                            reason=reason,
                            idempotency_key=f"runtime:{node.node_id}:approval-request",
                        )
                        self.store.request_approval(
                            spec.run_id,
                            reason=reason,
                            idempotency_key=f"runtime:{node.node_id}:run-approval-request",
                        )
                        now = time.time()
                        self._record_runtime_node_event(
                            spec.run_id,
                            node,
                            started_at=now,
                            ended_at=now,
                            result=None,
                            error=reason,
                            status="interrupted",
                        )
                        return self._interrupted_result(
                            spec,
                            results,
                            node=node,
                            started_at=execute_started_at,
                        )
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
                        self._cancel_pending_nodes(
                            spec,
                            reason=result.error or f"{node.node_id} skipped",
                        )
                        self.store.cancel(
                            spec.run_id,
                            reason=result.error or f"{node.node_id} skipped",
                            idempotency_key="runtime:cancel",
                        )
                        return self._terminal_result_from_node_result(
                            spec,
                            results,
                            result,
                            started_at=execute_started_at,
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
                        return self._terminal_result_from_node_result(
                            spec,
                            results,
                            result,
                            started_at=execute_started_at,
                        )
            self.store.complete(spec.run_id, idempotency_key="runtime:complete")
            return self._result_with_run_event(
                spec,
                status=RunResultStatus.COMPLETED,
                results=tuple(results),
                started_at=execute_started_at,
            )
        except Exception as exc:
            self._fail_running_node(spec.run_id, str(exc))
            return self._result_with_run_event(
                spec,
                status=RunResultStatus.FAILED,
                results=tuple(results),
                started_at=execute_started_at,
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
            self._release_active_lease(run_id, result.node_id, idempotency_suffix="replay")
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

    def _result_with_run_event(
        self,
        spec: RunSpec,
        *,
        status: RunResultStatus,
        results: tuple[NodeResult, ...],
        started_at: float,
        error: str | None = None,
    ) -> RunResult:
        self._record_runtime_run_event(
            spec,
            started_at=started_at,
            ended_at=time.time(),
            status=status,
            results=results,
            error=error,
        )
        return RunResult(
            run_id=spec.run_id,
            status=status,
            results=results,
            backend=self.backend_name,
            spec_digest=spec.digest,
            error=error,
        )

    def _terminal_result_from_node_result(
        self,
        spec: RunSpec,
        results: list[NodeResult],
        result: NodeResult,
        *,
        started_at: float,
    ) -> RunResult:
        status = (
            RunResultStatus.CANCELLED
            if result.status is NodeResultStatus.SKIPPED
            else RunResultStatus.FAILED
        )
        return self._result_with_run_event(
            spec,
            status=status,
            results=tuple(results),
            started_at=started_at,
            error=result.error,
        )

    def _cancelled_result(
        self,
        spec: RunSpec,
        results: list[NodeResult],
        *,
        started_at: float,
    ) -> RunResult:
        return self._result_with_run_event(
            spec,
            status=RunResultStatus.CANCELLED,
            results=tuple(results),
            started_at=started_at,
            error="run cancelled",
        )

    def _interrupted_result(
        self,
        spec: RunSpec,
        results: list[NodeResult],
        *,
        started_at: float,
        node: NodeSpec | None = None,
    ) -> RunResult:
        target = "run" if node is None else f"node {node.node_id}"
        return self._result_with_run_event(
            spec,
            status=RunResultStatus.INTERRUPTED,
            results=tuple(results),
            started_at=started_at,
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

    def _cancel_pending_nodes(self, spec: RunSpec, *, reason: str) -> None:
        snapshot = self.store.load(spec.run_id)
        for node in spec.topological_order():
            if snapshot.nodes[node.node_id].state is not NodeState.PENDING:
                continue
            self.store.cancel_node(
                spec.run_id,
                node.node_id,
                reason=reason,
                idempotency_key=f"runtime:{node.node_id}:cancel-pending",
            )
            now = time.time()
            self._record_runtime_node_event(
                spec.run_id,
                node,
                started_at=now,
                ended_at=now,
                result=None,
                error=reason,
                status="cancelled",
            )
            snapshot = self.store.load(spec.run_id)

    def _run_node_with_retries(
        self,
        run_id: str,
        node: NodeSpec,
        handler: NodeHandler,
    ) -> NodeResult:
        """Run one node, recording retry attempts before any terminal result."""
        started_at = time.time()
        ended_at = started_at
        lease: Lease | None = None
        final_result: NodeResult | None = None
        failure: str | None = None
        release_failure: str | None = None
        try:
            lease = self._acquire_node_lease(run_id, node)
            while True:
                try:
                    result = handler(node)
                    self._validate_node_result(node, result)
                except RuntimeContractError:
                    raise
                except Exception as exc:
                    if self._record_retry_if_allowed(run_id, node, exc):
                        continue
                    final_result = NodeResult(
                        node_id=node.node_id,
                        status=NodeResultStatus.FAILED,
                        idempotency_key=node.idempotency_key or f"runtime:{node.node_id}",
                        error=str(exc),
                    )
                    return final_result
                if result.status is not NodeResultStatus.FAILED:
                    final_result = result
                    return result
                reason = result.error or "failed"
                if self._record_retry_if_allowed(run_id, node, reason):
                    continue
                final_result = result
                return result
        except Exception as exc:
            failure = str(exc)
            raise
        finally:
            try:
                if lease is not None:
                    self._release_lease(
                        run_id,
                        node.node_id,
                        token=lease.token,
                        idempotency_key=f"runtime:{node.node_id}:lease-release:{lease.token}",
                    )
            except Exception as exc:
                release_failure = str(exc)
                raise
            finally:
                ended_at = time.time()
                self._record_runtime_node_event(
                    run_id,
                    node,
                    started_at=started_at,
                    ended_at=ended_at,
                    result=final_result,
                    error=release_failure or failure,
                )

    def _record_runtime_run_event(
        self,
        spec: RunSpec,
        *,
        started_at: float,
        ended_at: float,
        status: RunResultStatus,
        results: tuple[NodeResult, ...],
        error: str | None,
    ) -> None:
        if self.repo_root is None:
            return
        evidence = tuple(item for result in results for item in result.evidence)
        evidence_kinds = sorted({item.kind for item in evidence})
        status_counts = {
            status.value: sum(1 for result in results if result.status.value == status.value)
            for status in NodeResultStatus
        }
        record_trace_event(
            self.repo_root,
            TraceEvent(
                kind=TraceEventKind.RUNTIME_RUN,
                ts=started_at,
                payload={
                    "backend": self.backend_name,
                    "run_id": spec.run_id,
                    "status": status.value,
                    "error": error,
                    "spec_digest": spec.digest,
                    "node_count": len(spec.nodes),
                    "result_count": len(results),
                    "node_status_counts": status_counts,
                    "evidence_count": len(evidence),
                    "evidence_kinds": evidence_kinds,
                    "digest_evidence_count": sum(1 for item in evidence if item.digest),
                    "completion_evidence_count": sum(
                        1 for item in evidence if item.kind == "completion"
                    ),
                    "max_workers": self.max_workers,
                    "end_ts": ended_at,
                    "duration_seconds": max(0.0, ended_at - started_at),
                    "title": f"runtime run {spec.run_id} {status.value}",
                },
            ),
        )

    def _record_runtime_node_event(
        self,
        run_id: str,
        node: NodeSpec,
        *,
        started_at: float,
        ended_at: float,
        result: NodeResult | None,
        error: str | None,
        status: str | None = None,
    ) -> None:
        if self.repo_root is None:
            return
        retry_attempts = 0
        try:
            retry_attempts = self.store.load(run_id).nodes[node.node_id].attempts
        except Exception:  # noqa: BLE001
            retry_attempts = 0
        if status is not None:
            status_value = status
        elif result is not None:
            status_value = result.status.value
        else:
            status_value = NodeResultStatus.FAILED.value
        evidence = () if result is None else result.evidence
        evidence_kinds = sorted({item.kind for item in evidence})
        record_trace_event(
            self.repo_root,
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=started_at,
                payload={
                    "backend": self.backend_name,
                    "run_id": run_id,
                    "node_id": node.node_id,
                    "node_kind": node.kind,
                    "status": status_value,
                    "error": error or (result.error if result is not None else None),
                    "side_effecting": node.side_effecting,
                    "approval_required": node.approval_required,
                    "dependencies": list(node.dependencies),
                    "capabilities": node.capabilities.to_dict(),
                    "evidence_count": len(evidence),
                    "evidence_kinds": evidence_kinds,
                    "digest_evidence_count": sum(1 for item in evidence if item.digest),
                    "completion_evidence_count": sum(
                        1 for item in evidence if item.kind == "completion"
                    ),
                    "retry_attempts": retry_attempts,
                    "end_ts": ended_at,
                    "duration_seconds": max(0.0, ended_at - started_at),
                    "title": f"runtime node {node.node_id} {status_value}",
                },
            ),
        )

    def _acquire_node_lease(self, run_id: str, node: NodeSpec) -> Lease:
        snapshot = self.store.load(run_id)
        active = snapshot.nodes[node.node_id].lease
        if active is not None:
            return active
        sequence = 1 + sum(
            1
            for event in self.store.events(run_id)
            if event.event_type == "lease_acquired"
            and event.payload.get("node_id") == node.node_id
        )
        return self.store.acquire_lease(
            run_id,
            node.node_id,
            owner=self.backend_name,
            ttl_seconds=self._lease_ttl(node),
            idempotency_key=f"runtime:{node.node_id}:lease:{sequence}",
        )

    def _lease_ttl(self, node: NodeSpec) -> float:
        if node.timeout_seconds is not None:
            return node.timeout_seconds
        if node.budget is not None:
            return node.budget.timeout_seconds
        return 300.0

    def _release_active_lease(
        self,
        run_id: str,
        node_id: str,
        *,
        idempotency_suffix: str,
    ) -> None:
        snapshot = self.store.load(run_id)
        lease = snapshot.nodes[node_id].lease
        if lease is None:
            return
        self._release_lease(
            run_id,
            node_id,
            token=lease.token,
            idempotency_key=f"runtime:{node_id}:lease-release:{idempotency_suffix}",
        )

    def _release_lease(
        self,
        run_id: str,
        node_id: str,
        *,
        token: str,
        idempotency_key: str,
    ) -> None:
        try:
            self.store.release_lease(
                run_id,
                node_id,
                token=token,
                idempotency_key=idempotency_key,
            )
        except LeaseExpiredError:
            return

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
