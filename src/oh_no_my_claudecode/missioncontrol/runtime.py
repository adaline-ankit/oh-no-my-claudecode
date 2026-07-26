"""Read-only Mission Control projection of canonical durable runtime events."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from oh_no_my_claudecode.durable_runtime import (
    DurableRuntimeError,
    NodeState,
    RunState,
    RuntimeStore,
)
from oh_no_my_claudecode.harness_run.receipt import read_harness_receipt

if TYPE_CHECKING:
    from rich.console import Console

_LIVE_NODE_STATES = frozenset(
    {
        NodeState.RUNNING,
        NodeState.PAUSED,
        NodeState.WAITING,
        NodeState.AWAITING_APPROVAL,
    }
)
_TERMINAL_RUN_STATES = frozenset(
    {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
)


@dataclass(frozen=True, slots=True)
class RuntimeNodeStatus:
    """One node reconstructed from the append-only event stream."""

    node_id: str
    state: str
    attempts: int
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "state": self.state,
            "attempts": self.attempts,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RuntimeRunStatus:
    """User-visible state for one canonical harness run."""

    run_id: str
    state: str
    created_at: str | None
    updated_at: str | None
    event_count: int
    nodes: tuple[RuntimeNodeStatus, ...] = ()
    active_node: str | None = None
    task: str | None = None
    proof_state: str = "pending"
    verified: bool = False
    receipt_hash: str | None = None
    proof_reasons: tuple[str, ...] = ()
    action: str | None = None
    last_event: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "event_count": self.event_count,
            "nodes": [node.to_dict() for node in self.nodes],
            "active_node": self.active_node,
            "task": self.task,
            "proof_state": self.proof_state,
            "verified": self.verified,
            "receipt_hash": self.receipt_hash,
            "proof_reasons": list(self.proof_reasons),
            "action": self.action,
            "last_event": self.last_event,
        }


@dataclass(frozen=True, slots=True)
class RuntimeDashboard:
    """Recent canonical runs, rebuilt without consulting agent summaries."""

    runs: tuple[RuntimeRunStatus, ...] = ()
    corrupt_run_ids: tuple[str, ...] = ()

    @property
    def active_count(self) -> int:
        return sum(
            run.state
            not in {state.value for state in _TERMINAL_RUN_STATES}
            and run.state != "corrupt"
            for run in self.runs
        )

    @property
    def verified_count(self) -> int:
        return sum(run.verified for run in self.runs)

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": {
                "runs": len(self.runs),
                "active": self.active_count,
                "verified": self.verified_count,
                "corrupt": len(self.corrupt_run_ids),
            },
            "runs": [run.to_dict() for run in self.runs],
            "corrupt_run_ids": list(self.corrupt_run_ids),
        }


def _run_ids(store: RuntimeStore) -> list[str]:
    runs_dir = store.root / "runs"
    if not runs_dir.is_dir():
        return []
    return sorted(
        entry.name
        for entry in runs_dir.iterdir()
        if entry.is_dir() and (entry / "events.jsonl").is_file()
    )


def _last_node_reasons(events: tuple[Any, ...]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for event in events:
        payload = event.payload
        node_id = payload.get("node_id")
        reason = payload.get("reason")
        if isinstance(node_id, str) and isinstance(reason, str) and reason:
            reasons[node_id] = reason
    return reasons


def _action_for(state: RunState, active: str | None, verified: bool) -> str | None:
    if state is RunState.AWAITING_APPROVAL:
        return "Review the persisted approval request"
    if state in {RunState.PAUSED, RunState.WAITING}:
        return f"Resume run {active or ''}".rstrip()
    if state in _TERMINAL_RUN_STATES and not verified:
        return "Inspect verifier evidence before retrying"
    return None


def _proof_reasons(proof: dict[str, object]) -> tuple[str, ...]:
    reasons = proof.get("reasons")
    if not isinstance(reasons, list):
        return ()
    return tuple(str(reason) for reason in reasons if str(reason).strip())


def _build_run(repo_root: Path, store: RuntimeStore, run_id: str) -> RuntimeRunStatus:
    snapshot = store.load(run_id)
    events = store.events(run_id)
    reasons = _last_node_reasons(events)
    nodes = tuple(
        RuntimeNodeStatus(
            node_id=node_id,
            state=node.state.value,
            attempts=node.attempts,
            reason=reasons.get(node_id),
        )
        for node_id, node in sorted(snapshot.nodes.items())
    )
    active = next(
        (node.node_id for node in snapshot.nodes.values() if node.state in _LIVE_NODE_STATES),
        None,
    )
    receipt = read_harness_receipt(repo_root, run_id)
    verified = bool(
        receipt is not None
        and receipt.verified
        and snapshot.state is RunState.COMPLETED
    )
    if verified:
        proof_state = "verified"
    elif receipt is not None:
        proof_state = "rejected"
    elif snapshot.state in _TERMINAL_RUN_STATES:
        proof_state = "unproven"
    else:
        proof_state = "pending"
    last_event = events[-1].event_type if events else None
    return RuntimeRunStatus(
        run_id=run_id,
        state=snapshot.state.value,
        created_at=snapshot.created_at.isoformat(),
        updated_at=snapshot.updated_at.isoformat(),
        event_count=len(events),
        nodes=nodes,
        active_node=active,
        task=receipt.task if receipt is not None else None,
        proof_state=proof_state,
        verified=verified,
        receipt_hash=receipt.receipt_hash if receipt is not None else None,
        proof_reasons=_proof_reasons(receipt.proof) if receipt is not None else (),
        action=_action_for(snapshot.state, active, verified),
        last_event=last_event,
    )


def build_runtime_dashboard(repo_root: Path, *, limit: int = 20) -> RuntimeDashboard:
    """Replay recent ``onmc run`` events into a deterministic read model."""
    store = RuntimeStore(repo_root / ".onmc" / "harness-runtime")
    runs: list[RuntimeRunStatus] = []
    corrupt: list[str] = []
    for run_id in _run_ids(store):
        try:
            runs.append(_build_run(repo_root, store, run_id))
        except DurableRuntimeError:
            corrupt.append(run_id)
            runs.append(
                RuntimeRunStatus(
                    run_id=run_id,
                    state="corrupt",
                    created_at=None,
                    updated_at=None,
                    event_count=0,
                    proof_state="unavailable",
                    action="Inspect the durable event log",
                )
            )
    runs.sort(key=lambda run: (run.updated_at or "", run.run_id), reverse=True)
    return RuntimeDashboard(tuple(runs[:limit]), tuple(sorted(corrupt)))


def render_runtime_dashboard(model: RuntimeDashboard, console: Console) -> None:
    """Render canonical run progress and proof state without mutating it."""
    from rich.table import Table

    if not model.runs:
        console.print(
            "[yellow]No canonical runs found.[/yellow] "
            "Preview one with [cyan]onmc run \"your task\"[/cyan]."
        )
        return
    console.print(
        "[bold]Mission Control[/bold] — canonical runtime  "
        f"[dim]{model.active_count} active · {model.verified_count} verified[/dim]"
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("run", no_wrap=True)
    table.add_column("state", no_wrap=True)
    table.add_column("active node", no_wrap=True)
    table.add_column("proof", no_wrap=True)
    table.add_column("task / next action")
    for run in model.runs:
        proof_style = {
            "verified": "bold green",
            "rejected": "bold red",
            "unproven": "yellow",
            "unavailable": "bold red",
        }.get(run.proof_state, "dim")
        detail = run.task or run.action or "(task appears when a receipt is written)"
        table.add_row(
            run.run_id,
            run.state,
            run.active_node or "—",
            f"[{proof_style}]{run.proof_state}[/]",
            detail,
        )
    console.print(table)


__all__ = [
    "RuntimeDashboard",
    "RuntimeNodeStatus",
    "RuntimeRunStatus",
    "build_runtime_dashboard",
    "render_runtime_dashboard",
]
