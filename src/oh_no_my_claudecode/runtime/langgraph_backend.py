"""Optional LangGraph scheduler behind ONMC's canonical runtime contracts.

LangGraph owns graph scheduling and its SQLite checkpoints when the optional
packages are installed. ONMC's ``RuntimeStore`` remains authoritative for
idempotency, approvals, node state, receipts, and replay safety.
"""

from __future__ import annotations

import importlib
import operator
import sqlite3
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Annotated, Any, Protocol, TypedDict

from oh_no_my_claudecode.durable_runtime import NodeState, RunState, RuntimeStore
from oh_no_my_claudecode.runtime.backend import NodeHandler
from oh_no_my_claudecode.runtime.checkpoint_codec import (
    decode_checkpoint,
    encode_checkpoint,
)
from oh_no_my_claudecode.runtime.contracts import (
    NodeResult,
    NodeResultStatus,
    NodeSpec,
    RunResult,
    RunResultStatus,
    RunSpec,
    RuntimeContractError,
)
from oh_no_my_claudecode.runtime.native_backend import NativeExecutionBackend

_Command: Any = None
_END: Any = None
_START: Any = None
_SqliteSaver: Any = None
_StateGraph: Any = None
_interrupt: Any = None
_LANGGRAPH_IMPORT_ERROR: BaseException | None = None

try:  # pragma: no cover - exercised by the optional-extra smoke tests
    _checkpoint_module = importlib.import_module("langgraph.checkpoint.sqlite")
    _graph_module = importlib.import_module("langgraph.graph")
    _types_module = importlib.import_module("langgraph.types")
    _SqliteSaver = _checkpoint_module.SqliteSaver
    _END = _graph_module.END
    _START = _graph_module.START
    _StateGraph = _graph_module.StateGraph
    _Command = _types_module.Command
    _interrupt = _types_module.interrupt
except Exception as exc:  # noqa: BLE001 - a broken optional install is unavailable
    _LANGGRAPH_IMPORT_ERROR = exc


class LangGraphUnavailableError(RuntimeError):
    """Raised when the optional LangGraph scheduler cannot be loaded."""


def langgraph_available() -> bool:
    """Return whether both LangGraph and its SQLite checkpointer are usable."""
    return _LANGGRAPH_IMPORT_ERROR is None


def _unavailable_error(*, native_default: bool) -> LangGraphUnavailableError:
    detail = (
        "unknown import failure"
        if _LANGGRAPH_IMPORT_ERROR is None
        else str(_LANGGRAPH_IMPORT_ERROR)
    )
    default_note = "; the native backend remains the default" if native_default else ""
    return LangGraphUnavailableError(
        "optional LangGraph dependencies are unavailable"
        f"{default_note}; install a repository-pinned LangGraph extra before selecting "
        f"this backend ({detail})"
    )


class _GraphState(TypedDict):
    schema_version: int
    spec_digest: str
    completed_node_ids: Annotated[list[str], operator.add]


class GraphDriver(Protocol):
    """Small scheduling seam that keeps ONMC semantics testable offline."""

    def run(
        self,
        spec: RunSpec,
        execute_node: Callable[[NodeSpec], None],
        *,
        resume: bool,
    ) -> None:
        """Schedule nodes from *spec*, calling *execute_node* for each."""
        ...


class _ApprovalInterruptError(Exception):
    def __init__(self, node: NodeSpec) -> None:
        super().__init__(f"approval required before {node.node_id}")
        self.node = node


class _LangGraphDriver:
    """Compile a ``RunSpec`` to a checkpointed LangGraph graph."""

    def __init__(self, checkpoint_path: Path, *, max_workers: int) -> None:
        self.checkpoint_path = checkpoint_path
        self.max_workers = max_workers

    def run(
        self,
        spec: RunSpec,
        execute_node: Callable[[NodeSpec], None],
        *,
        resume: bool,
    ) -> None:
        if not langgraph_available():
            raise _unavailable_error(native_default=False)

        builder = _StateGraph(_GraphState)
        dependent_ids = {
            dependency for node in spec.nodes for dependency in node.dependencies
        }
        for node in spec.nodes:
            builder.add_node(
                node.node_id,
                self._graph_node(spec, node, execute_node),
            )
            if node.dependencies:
                builder.add_edge(list(node.dependencies), node.node_id)
            else:
                builder.add_edge(_START, node.node_id)
            if node.node_id not in dependent_ids:
                builder.add_edge(node.node_id, _END)

        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.checkpoint_path, check_same_thread=False)) as connection:
            checkpointer = _SqliteSaver(connection)
            graph = builder.compile(checkpointer=checkpointer)
            config: dict[str, object] = {
                "configurable": {"thread_id": spec.run_id},
                "max_concurrency": self.max_workers,
            }
            has_checkpoint = checkpointer.get_tuple(config) is not None
            if resume and has_checkpoint:
                graph_state = graph.get_state(config)
                has_interrupt = any(
                    getattr(task, "interrupts", ()) for task in graph_state.tasks
                )
                value: object = (
                    _Command(resume={"approved": True}) if has_interrupt else None
                )
            else:
                value = encode_checkpoint(spec_digest=spec.digest)
            graph.invoke(value, config)

    @staticmethod
    def _graph_node(
        spec: RunSpec,
        node: NodeSpec,
        execute_node: Callable[[NodeSpec], None],
    ) -> Callable[[_GraphState], dict[str, object]]:
        def invoke(state: _GraphState) -> dict[str, object]:
            decode_checkpoint(state, expected_spec_digest=spec.digest)
            try:
                execute_node(node)
            except _ApprovalInterruptError as exc:
                _interrupt(
                    {
                        "kind": "approval",
                        "node_id": exc.node.node_id,
                        "reason": str(exc),
                        "run_id": spec.run_id,
                    }
                )
                execute_node(node)
            return {"completed_node_ids": [node.node_id]}

        return invoke


class LangGraphExecutionBackend(NativeExecutionBackend):
    """Execute ``RunSpec`` through LangGraph while preserving ONMC authority."""

    backend_name = "langgraph"

    def __init__(
        self,
        store: RuntimeStore,
        *,
        repo_root: Path | None = None,
        max_workers: int = 1,
        checkpoint_path: Path | None = None,
        driver: GraphDriver | None = None,
    ) -> None:
        super().__init__(store, repo_root=repo_root, max_workers=max_workers)
        self.checkpoint_path = (
            store.root / "langgraph-checkpoints.sqlite3"
            if checkpoint_path is None
            else Path(checkpoint_path)
        )
        self.driver = driver

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
        if self.driver is None and not langgraph_available():
            raise _unavailable_error(native_default=True)

        started_at = time.time()
        snapshot = self._load_or_create(spec, resume=resume)
        existing = self._stored_results(spec)
        if snapshot.state is RunState.COMPLETED:
            return self._result_with_run_event(
                spec,
                status=RunResultStatus.COMPLETED,
                results=existing,
                started_at=started_at,
            )
        if snapshot.state is RunState.AWAITING_APPROVAL:
            return self._interrupted_result(
                spec,
                list(existing),
                started_at=started_at,
            )
        if snapshot.state is RunState.CANCELLED:
            return self._cancelled_result(spec, list(existing), started_at=started_at)
        if snapshot.state is not RunState.RUNNING:
            self.store.start(spec.run_id, idempotency_key="runtime:start")

        driver = self.driver or _LangGraphDriver(
            self.checkpoint_path,
            max_workers=self.max_workers,
        )
        try:
            driver.run(
                spec,
                lambda node: self._execute_graph_node(spec, node, handlers[node.node_id]),
                resume=resume,
            )
        except _ApprovalInterruptError as exc:
            return self._interrupted_result(
                spec,
                list(self._stored_results(spec)),
                node=exc.node,
                started_at=started_at,
            )
        except Exception as exc:
            self._fail_running_node(spec.run_id, str(exc))
            return self._result_with_run_event(
                spec,
                status=RunResultStatus.FAILED,
                results=self._stored_results(spec),
                started_at=started_at,
                error=str(exc),
            )

        snapshot = self.store.load(spec.run_id)
        results = self._stored_results(spec)
        if snapshot.state is RunState.AWAITING_APPROVAL:
            return self._interrupted_result(spec, list(results), started_at=started_at)
        if snapshot.state is RunState.CANCELLED:
            return self._cancelled_result(spec, list(results), started_at=started_at)
        if snapshot.state is RunState.FAILED:
            error = next(
                (
                    result.error
                    for result in reversed(results)
                    if result.status is NodeResultStatus.FAILED
                ),
                "run failed",
            )
            return self._result_with_run_event(
                spec,
                status=RunResultStatus.FAILED,
                results=results,
                started_at=started_at,
                error=error,
            )
        if all(node.state is NodeState.SUCCEEDED for node in snapshot.nodes.values()):
            self.store.complete(spec.run_id, idempotency_key="runtime:complete")
            return self._result_with_run_event(
                spec,
                status=RunResultStatus.COMPLETED,
                results=results,
                started_at=started_at,
            )
        raise RuntimeContractError("LangGraph stopped before the ONMC run reached a terminal state")

    def _execute_graph_node(
        self,
        spec: RunSpec,
        node: NodeSpec,
        handler: NodeHandler,
    ) -> None:
        snapshot = self.store.load(spec.run_id)
        if snapshot.state in {RunState.CANCELLED, RunState.FAILED}:
            return
        state = snapshot.nodes[node.node_id].state
        if state is NodeState.SUCCEEDED:
            return
        if state is NodeState.CANCELLED:
            return
        if self._has_result(spec.run_id, node.node_id):
            result = self._load_result(spec.run_id, node.node_id)
            self._validate_node_result(node, result)
            self._apply_persisted_result(spec.run_id, result)
            self._apply_terminal_side_effects(spec, result)
            return
        if any(
            snapshot.nodes[dependency].state is not NodeState.SUCCEEDED
            for dependency in node.dependencies
        ):
            raise RuntimeContractError(f"node {node.node_id!r} has unsatisfied dependencies")
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
            raise _ApprovalInterruptError(node)

        result = self._run_node_with_retries(spec.run_id, node, handler)
        self._write_result(spec.run_id, result)
        self._apply_persisted_result(spec.run_id, result)
        self._apply_terminal_side_effects(spec, result)

    def _apply_terminal_side_effects(self, spec: RunSpec, result: NodeResult) -> None:
        if result.status is not NodeResultStatus.SKIPPED:
            return
        reason = result.error or result.status.value
        self._cancel_pending_nodes(spec, reason=reason)
        self.store.cancel(spec.run_id, reason=reason, idempotency_key="runtime:cancel")

    def _stored_results(self, spec: RunSpec) -> tuple[NodeResult, ...]:
        return tuple(
            self._load_result(spec.run_id, node.node_id)
            for node in spec.topological_order()
            if self._has_result(spec.run_id, node.node_id)
        )
