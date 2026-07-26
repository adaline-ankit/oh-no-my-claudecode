"""Swarm orchestrator: parallel accountable agent loops.

Honest concurrency model
------------------------
``run_swarm`` submits one ``run_loop`` call per SwarmUnit to a
``concurrent.futures.ThreadPoolExecutor`` whose ``max_workers`` is capped at
``config.concurrency`` (default: min(cpu_count-1, 8)).  This is a BOUNDED
POOL draining a QUEUE — NOT unbounded true parallelism.  100 queued tasks
means at most ``config.concurrency`` run simultaneously; the rest wait.

Abort protocol
--------------
A sentinel file ``.onmc/swarm/<swarm_id>/ABORT`` is the kill-switch.  Any
code can write the file to request graceful abort.  The ``should_continue``
callback injected into each ``run_loop`` checks this file at the start of
every iteration.  Queued units that have not yet started are never launched
once the ABORT file exists.

State persistence
-----------------
``run_swarm`` writes ``.onmc/swarm/<swarm_id>/manifest.json`` at the start
(with all unit ids and "pending" status) and updates it atomically after each
unit completes.  This gives external tooling a live view into swarm progress.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import secrets
import shlex
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from oh_no_my_claudecode.durable_runtime import RuntimeStore
from oh_no_my_claudecode.loop.models import (
    AgentRunner,
    ChangeProbe,
    LoopResult,
    VerifyOutcome,
    VerifyRunner,
)
from oh_no_my_claudecode.runtime import (
    EvidenceRef,
    NativeExecutionBackend,
    NodeHandler,
    NodeResult,
    NodeResultStatus,
    NodeSpec,
    RunResult,
    RunResultStatus,
    RunSpec,
    RuntimeContractError,
)
from oh_no_my_claudecode.swarm.models import (
    SwarmConfig,
    SwarmResult,
    SwarmUnit,
    SwarmUnitResult,
)
from oh_no_my_claudecode.swarm.runtime_contract import (
    SwarmContractUnit,
    build_swarm_run_spec,
)

# ---------------------------------------------------------------------------
# Typing aliases
# ---------------------------------------------------------------------------

#: Factory that produces an AgentRunner for a given unit/repo_root.
#: Signature: (unit: SwarmUnit, repo_root: Path) -> AgentRunner
AgentRunnerFactory = Callable[[SwarmUnit, Path], AgentRunner]

#: Factory that produces a VerifyRunner for a given unit/repo_root.
#: Signature: (unit: SwarmUnit, repo_root: Path) -> VerifyRunner
VerifyRunnerFactory = Callable[[SwarmUnit, Path], VerifyRunner]

#: Factory that produces a ChangeProbe for a given unit/repo_root.
#: Signature: (unit: SwarmUnit, repo_root: Path) -> ChangeProbe
ChangeProbeFactory = Callable[[SwarmUnit, Path], ChangeProbe]


# ---------------------------------------------------------------------------
# State directory helpers
# ---------------------------------------------------------------------------


def _swarm_dir(repo_root: Path, swarm_id: str) -> Path:
    """Return .onmc/swarm/<swarm_id>/ directory, creating if needed."""
    d = repo_root / ".onmc" / "swarm" / swarm_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _abort_path(repo_root: Path, swarm_id: str) -> Path:
    """Return the ABORT sentinel file path for a specific swarm."""
    return _swarm_dir(repo_root, swarm_id) / "ABORT"


def _global_abort_path(repo_root: Path) -> Path:
    """Return the global ABORT sentinel file path (aborts all swarms)."""
    d = repo_root / ".onmc" / "swarm"
    d.mkdir(parents=True, exist_ok=True)
    return d / "ABORT"


def _manifest_path(repo_root: Path, swarm_id: str) -> Path:
    """Return the manifest.json path for a swarm."""
    return _swarm_dir(repo_root, swarm_id) / "manifest.json"


def _write_manifest(
    repo_root: Path,
    swarm_id: str,
    units: list[SwarmUnit],
    config: SwarmConfig,
    started_at: str,
) -> RunSpec:
    """Write or validate the idempotent initial swarm manifest."""
    runtime_spec = build_swarm_run_spec(
        swarm_id=swarm_id,
        units=tuple(
            SwarmContractUnit(
                unit_id=unit.id,
                goal=unit.goal,
                verify_command=unit.verify_command,
                allowed_paths=tuple(unit.allowed_paths),
                protected_paths=tuple(unit.protected_paths),
                dependencies=tuple(unit.dependencies),
            )
            for unit in units
        ),
        agent=config.agent,
        mode="process",
        concurrency=config.concurrency,
        max_cost_usd=config.max_cost_usd,
        max_tokens=config.budget_tokens,
        timeout_seconds=float(config.agent_timeout_seconds),
    )
    manifest_path = _manifest_path(repo_root, swarm_id)
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeContractError("existing swarm manifest is unreadable") from exc
        if not isinstance(existing, dict):
            raise RuntimeContractError("existing swarm manifest must be an object")
        if existing.get("runtime_contract_digest") != runtime_spec.digest:
            raise RuntimeContractError(
                f"swarm {swarm_id!r} already exists with a different runtime contract"
            )
        return runtime_spec

    manifest: dict[str, Any] = {
        "swarm_id": swarm_id,
        "mode": "process",
        "started_at": started_at,
        "agent": config.agent,
        "concurrency": config.concurrency,
        "agent_timeout_seconds": config.agent_timeout_seconds,
        "preserve_failed_worktrees": config.preserve_failed_worktrees,
        "runtime_contract": runtime_spec.to_dict(),
        "runtime_contract_digest": runtime_spec.digest,
        "swarm_max_cost_usd": config.swarm_max_cost_usd,
        "units": {
            u.id: {
                "goal": u.goal[:200],
                "status": "pending",
                "cost_usd": 0.0,
                "receipt_path": None,
                "error": None,
                "worktree_path": None,
                "branch": None,
                "dependencies": list(u.dependencies),
                "verify_output": None,
            }
            for u in units
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return runtime_spec


def _update_manifest(
    repo_root: Path,
    swarm_id: str,
    unit_result: SwarmUnitResult,
    lock: threading.Lock,
) -> None:
    """Atomically update one unit's status in the manifest."""
    mpath = _manifest_path(repo_root, swarm_id)
    with lock:
        try:
            manifest: dict[str, Any] = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        uid = unit_result.unit_id
        if uid in manifest.get("units", {}):
            manifest["units"][uid]["status"] = unit_result.status
            manifest["units"][uid]["cost_usd"] = unit_result.cost_usd
            manifest["units"][uid]["receipt_path"] = (
                str(unit_result.receipt_path) if unit_result.receipt_path else None
            )
            manifest["units"][uid]["error"] = unit_result.error
            manifest["units"][uid]["worktree_path"] = (
                str(unit_result.worktree_path) if unit_result.worktree_path else None
            )
            manifest["units"][uid]["branch"] = unit_result.branch
            manifest["units"][uid]["verify_output"] = unit_result.verify_output
        mpath.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _mark_manifest_done(
    repo_root: Path,
    swarm_id: str,
    stop_reason: str,
    *,
    runtime_result: RunResult,
) -> None:
    """Write final stop_reason and ended_at to manifest."""
    mpath = _manifest_path(repo_root, swarm_id)
    try:
        manifest: dict[str, Any] = json.loads(mpath.read_text(encoding="utf-8"))
        manifest["stop_reason"] = stop_reason
        manifest["ended_at"] = datetime.now(UTC).isoformat()
        manifest["runtime_result"] = runtime_result.to_dict()
        mpath.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError):
        pass


def _receipt_evidence(
    swarm_id: str,
    result: SwarmUnitResult,
) -> tuple[EvidenceRef, ...]:
    path = result.receipt_path
    if path is None or not path.is_file():
        return ()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return (
        EvidenceRef(
            evidence_id=f"{swarm_id}:{result.unit_id}:receipt",
            kind="completion" if result.status == "done" else "receipt",
            uri=str(path),
            digest=f"sha256:{digest}",
        ),
    )


def _unit_result_output(result: SwarmUnitResult) -> dict[str, object]:
    loop_result = result.loop_result
    return {
        "branch": result.branch,
        "cost_usd": result.cost_usd,
        "error": result.error,
        "receipt_path": str(result.receipt_path) if result.receipt_path else None,
        "total_tokens": loop_result.total_tokens if loop_result is not None else 0,
        "unit_status": result.status,
        "verify_output": result.verify_output,
        "worktree_path": str(result.worktree_path) if result.worktree_path else None,
    }


def _unit_result_from_node_result(result: NodeResult) -> SwarmUnitResult:
    output = result.output
    raw_receipt = output.get("receipt_path")
    raw_worktree = output.get("worktree_path")
    raw_cost = output.get("cost_usd", 0.0)
    raw_status = output.get("unit_status")
    return SwarmUnitResult(
        unit_id=result.node_id,
        status=raw_status if isinstance(raw_status, str) else "failed",
        loop_result=None,
        receipt_path=Path(raw_receipt) if isinstance(raw_receipt, str) else None,
        cost_usd=float(raw_cost) if isinstance(raw_cost, int | float) else 0.0,
        error=output.get("error") if isinstance(output.get("error"), str) else result.error,
        worktree_path=Path(raw_worktree) if isinstance(raw_worktree, str) else None,
        branch=output.get("branch") if isinstance(output.get("branch"), str) else None,
        verify_output=(
            output.get("verify_output")
            if isinstance(output.get("verify_output"), str)
            else None
        ),
    )


def _build_fan_in_result(
    repo_root: Path,
    swarm_id: str,
    spec: RunSpec,
    node: NodeSpec,
    runtime_root: Path,
    manifest_lock: threading.Lock,
) -> NodeResult:
    """Join receipt-backed dependency outputs in canonical source order."""
    receipts: list[dict[str, object]] = []
    for unit_id in node.dependencies:
        result_path = (
            runtime_root / "runs" / spec.run_id / "node-results" / f"{unit_id}.json"
        )
        if not result_path.is_file():
            raise RuntimeContractError(f"fan-in is missing persisted result for {unit_id!r}")
        unit_result = NodeResult.from_dict(json.loads(result_path.read_text(encoding="utf-8")))
        completion = next(
            (
                evidence
                for evidence in unit_result.evidence
                if evidence.kind == "completion" and evidence.digest
            ),
            None,
        )
        if completion is None:
            raise RuntimeContractError(
                f"fan-in dependency {unit_id!r} lacks completion evidence"
            )
        receipts.append(
            {
                "evidence_id": completion.evidence_id,
                "receipt_digest": completion.digest,
                "receipt_uri": completion.uri,
                "unit_id": unit_id,
            }
        )

    payload = {
        "runtime_contract_digest": spec.digest,
        "schema_version": "1",
        "swarm_id": swarm_id,
        "unit_order": list(node.dependencies),
        "unit_receipts": receipts,
    }
    artifact_path = _swarm_dir(repo_root, swarm_id) / "fan-in.json"
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    artifact_path.write_bytes(encoded)
    evidence = EvidenceRef(
        evidence_id=f"{swarm_id}:fan-in",
        kind="completion",
        uri=str(artifact_path),
        digest=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
    )

    manifest_path = _manifest_path(repo_root, swarm_id)
    with manifest_lock:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise RuntimeContractError("swarm manifest must be an object")
        manifest["fan_in"] = {
            "evidence": evidence.to_dict(),
            "unit_order": list(node.dependencies),
            "unit_receipts": receipts,
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return NodeResult(
        node_id=node.node_id,
        status=NodeResultStatus.SUCCEEDED,
        idempotency_key=node.idempotency_key or f"{swarm_id}:fan-in",
        output={
            "artifact_path": str(artifact_path),
            "unit_order": list(node.dependencies),
            "unit_receipts": receipts,
        },
        evidence=(evidence,),
    )


# ---------------------------------------------------------------------------
# Abort helpers (public)
# ---------------------------------------------------------------------------


def request_abort(repo_root: Path, swarm_id: str | None = None) -> None:
    """Write the ABORT sentinel file for a swarm or for all swarms.

    Parameters
    ----------
    repo_root:
        Repository root.
    swarm_id:
        When provided, only the named swarm is aborted.
        When ``None``, a global ABORT file is written that stops all running
        swarms that check the global sentinel.
    """
    if swarm_id is not None:
        _abort_path(repo_root, swarm_id).write_text("abort", encoding="utf-8")
    else:
        _global_abort_path(repo_root).write_text("abort", encoding="utf-8")


def _is_abort_requested(
    abort_path: Path,
    global_abort_path: Path,
) -> bool:
    """Return True when either the swarm-specific or global ABORT file exists."""
    return abort_path.exists() or global_abort_path.exists()


# ---------------------------------------------------------------------------
# Swarm status / list helpers (public)
# ---------------------------------------------------------------------------


def swarm_state(repo_root: Path, swarm_id: str | None = None) -> dict[str, Any]:
    """Return the manifest dict for a swarm, or all swarms.

    Parameters
    ----------
    repo_root:
        Repository root.
    swarm_id:
        When provided, return only that swarm's manifest.
        When ``None``, return a dict keyed by swarm_id of all available manifests.
    """
    swarm_base = repo_root / ".onmc" / "swarm"
    if swarm_id is not None:
        mpath = _manifest_path(repo_root, swarm_id)
        if not mpath.exists():
            return {}
        try:
            return dict(json.loads(mpath.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return {}

    # Return all swarms.
    result: dict[str, Any] = {}
    if not swarm_base.exists():
        return result
    for d in sorted(swarm_base.iterdir()):
        if d.is_dir():
            mpath = d / "manifest.json"
            if mpath.exists():
                with contextlib.suppress(OSError, json.JSONDecodeError):
                    result[d.name] = json.loads(mpath.read_text(encoding="utf-8"))
    return result


# ---------------------------------------------------------------------------
# Default runner factories (use real adapters in production)
# ---------------------------------------------------------------------------


def _default_agent_runner_factory(unit: SwarmUnit, repo_root: Path) -> AgentRunner:
    """Build a real agent runner using the configured adapter (default factory).

    The agent type is NOT known at this level — the caller (run_swarm) passes
    config.agent down via closure.  This factory is replaced by a real closure
    inside run_swarm.
    """
    # This should never be called directly; run_swarm replaces it with a closure.
    from oh_no_my_claudecode.loop.adapters import make_agent_runner

    return make_agent_runner("claude", repo_root)


def _run_verify_command(command: str, repo_root: Path) -> VerifyOutcome:
    """Run a verify command in a specific repo/worktree root."""
    try:
        argv = shlex.split(command)
        if not argv:
            return VerifyOutcome(passed=False, output="[verify error: empty command]")
        shell_operators = {"&&", "||", ";", "|", ">", ">>", "<", "2>", "2>&1"}
        rejected = next((token for token in argv if token in shell_operators), None)
        if rejected is not None:
            return VerifyOutcome(
                passed=False,
                output=(
                    f"[verify error: shell operator {rejected!r} is not supported; "
                    "provide one structured command]"
                ),
            )
        result = subprocess.run(  # noqa: S603
            argv,
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return VerifyOutcome(
            passed=result.returncode == 0,
            output=(result.stdout + result.stderr)[:2000],
        )
    except subprocess.TimeoutExpired:
        return VerifyOutcome(passed=False, output="[verify timed out]")
    except Exception as exc:  # noqa: BLE001
        return VerifyOutcome(passed=False, output=f"[verify error: {exc}]")


def _default_verify_runner_factory(unit: SwarmUnit, repo_root: Path) -> VerifyRunner:
    """Build a verify runner from the unit's verify_command."""
    verify_cmd = unit.verify_command or "true"

    def _runner(command: str) -> VerifyOutcome:
        # Use the unit's verify_command, ignoring the one from LoopConfig.
        return _run_verify_command(verify_cmd, repo_root)

    return _runner


# ---------------------------------------------------------------------------
# Core: run_swarm
# ---------------------------------------------------------------------------


def run_swarm(
    storage: Any,  # SQLiteStorage — typed as Any to avoid circular import at call site
    repo_root: Path,
    units: list[SwarmUnit],
    config: SwarmConfig,
    *,
    runner_factory: AgentRunnerFactory | None = None,
    verify_factory: VerifyRunnerFactory | None = None,
    change_probe_factory: ChangeProbeFactory | None = None,
    executor: ThreadPoolExecutor | None = None,
    now: datetime | None = None,
    swarm_id: str | None = None,
) -> SwarmResult:
    """Run a bounded pool of accountable loop workers across isolated worktrees.

    Concurrency model
    -----------------
    Tasks are submitted to a ``ThreadPoolExecutor`` with at most
    ``config.concurrency`` workers.  100 units with concurrency=4 means at most
    4 run simultaneously — the remaining 96 wait in the queue.  This is honest
    bounded parallelism, NOT 100 simultaneous agent processes.

    Parameters
    ----------
    storage:
        Initialized SQLiteStorage instance shared across all units.
    repo_root:
        Absolute path to the repository root.
    units:
        List of SwarmUnit tasks to run.  The full list is queued; the pool
        drains it at the bounded concurrency level.
    config:
        Swarm-level configuration (concurrency, agent, per-unit limits, etc.).
    runner_factory:
        Injectable factory ``(unit, repo_root) -> AgentRunner``.  When ``None``,
        builds a real adapter from ``config.agent``.  Tests inject a fake.
    verify_factory:
        Injectable factory ``(unit) -> VerifyRunner``.  When ``None``, uses
        ``unit.verify_command`` with the default subprocess runner in the
        unit's active repo/worktree root.
        Tests inject a fake.
    change_probe_factory:
        Injectable factory ``(unit, repo_root) -> ChangeProbe`` for the
        vacuous-pass gate.  When ``None``, each unit's ``run_loop`` builds the
        default commit-aware git probe over the unit's active repo/worktree
        root — so a unit whose agent changed NOTHING can never be scored "done"
        merely because a lenient verifier exited 0 (the false-green failure
        mode, e.g. edits blocked pending permission approval).
    executor:
        Injectable ``ThreadPoolExecutor``.  When ``None``, creates one with
        ``max_workers=config.concurrency``.  Tests inject a fake or a
        single-threaded executor.
    now:
        Reference timestamp for the swarm start time (injectable for tests).

    Returns
    -------
    SwarmResult
        Aggregated result with per-unit SwarmUnitResult entries.
    """
    from oh_no_my_claudecode.loop.adapters import make_agent_runner
    from oh_no_my_claudecode.loop.engine import run_loop
    from oh_no_my_claudecode.loop.models import LoopConfig, LoopSpec

    swarm_id = swarm_id or secrets.token_hex(8)
    started_at_dt = now if now is not None else datetime.now(UTC)
    started_at = started_at_dt.isoformat()

    abort_path = _abort_path(repo_root, swarm_id)
    global_abort_path = _global_abort_path(repo_root)

    # Write initial manifest.
    runtime_spec = _write_manifest(repo_root, swarm_id, units, config, started_at)

    # Build real runner factories when not injected.
    if config.agent not in {"claude", "codex", "opencode"}:
        raise ValueError(f"unsupported swarm agent: {config.agent!r}")
    _agent = cast(Literal["claude", "codex", "opencode"], config.agent)

    def _real_runner_factory(unit: SwarmUnit, rr: Path) -> AgentRunner:
        return make_agent_runner(
            _agent,
            rr,
            timeout=config.agent_timeout_seconds,
        )

    resolved_runner_factory: AgentRunnerFactory = runner_factory or _real_runner_factory

    def _real_verify_factory(unit: SwarmUnit, rr: Path) -> VerifyRunner:
        cmd = unit.verify_command or "true"

        def _vr(command: str) -> VerifyOutcome:
            return _run_verify_command(cmd, rr)

        return _vr

    resolved_verify_factory: VerifyRunnerFactory = verify_factory or _real_verify_factory

    # Shared mutable state (protected by lock).
    manifest_lock = threading.Lock()
    cost_lock = threading.Lock()
    swarm_total_cost: list[float] = [0.0]  # mutable box
    swarm_total_tokens: list[int] = [0]
    _cost_cap_reached: list[bool] = [False]

    live_unit_results: dict[str, SwarmUnitResult] = {}
    results_lock = threading.Lock()

    def _run_one(unit: SwarmUnit) -> SwarmUnitResult:
        """Execute one unit's run_loop and return SwarmUnitResult."""
        # Pre-start abort check (don't even begin if aborted).
        if _is_abort_requested(abort_path, global_abort_path) or _cost_cap_reached[0]:
            ur = SwarmUnitResult(
                unit_id=unit.id,
                status="aborted",
                loop_result=None,
                receipt_path=None,
                cost_usd=0.0,
            )
            _update_manifest(repo_root, swarm_id, ur, manifest_lock)
            return ur

        # Build per-unit should_continue: checks ABORT sentinel.
        def _should_continue() -> bool:
            return not _is_abort_requested(abort_path, global_abort_path)

        # Build per-unit worktree isolation before creating agent/verify
        # runners. Adapters capture their cwd at construction time, so binding
        # them before isolation would leak edits and verification into the
        # caller's main worktree.
        isolation_provider = None
        worktree_path: Path | None = None
        branch_name: str | None = None
        unit_root = repo_root
        if config.isolate:
            from oh_no_my_claudecode.core.repo import WorktreeIsolationProvider

            isolation_provider = WorktreeIsolationProvider(
                branch_prefix=f"onmc-swarm-{swarm_id[:6]}"
            )
            worktree_path = isolation_provider.setup(repo_root)
            if worktree_path is not None:
                unit_root = worktree_path
                branch_name = isolation_provider.branch_name

        agent_runner = resolved_runner_factory(unit, unit_root)
        verify_runner = resolved_verify_factory(unit, unit_root)
        # None → run_loop builds the default commit-aware git probe over
        # unit_root, so the vacuous-pass gate is active in every real swarm run.
        # Tests inject a fake to exercise the gate deterministically.
        change_probe: ChangeProbe | None = (
            change_probe_factory(unit, unit_root) if change_probe_factory is not None else None
        )

        loop_spec = LoopSpec(goal=unit.goal)
        loop_config = LoopConfig(
            max_iterations=config.max_iterations,
            budget_tokens=config.budget_tokens,
            verify_command=unit.verify_command or "true",
            max_cost_usd=config.max_cost_usd,
            max_wall_seconds=config.max_wall_seconds,
            isolate=False,
            duplicate_action_limit=3,
            repeated_error_limit=3,
            allowed_paths=list(unit.allowed_paths),
            protected_paths=list(unit.protected_paths),
        )

        wall_start = time.monotonic()
        try:
            result: LoopResult = run_loop(
                storage,
                unit_root,
                loop_spec,
                loop_config,
                agent_runner=agent_runner,
                verify_runner=verify_runner,
                isolation_provider=None,
                now=started_at_dt,
                should_continue=_should_continue,
                change_probe=change_probe,
            )
        except Exception as exc:  # noqa: BLE001
            if isolation_provider is not None and worktree_path is not None:
                isolation_provider.teardown(
                    worktree_path,
                    keep=config.preserve_failed_worktrees,
                )
            ur = SwarmUnitResult(
                unit_id=unit.id,
                status="failed",
                loop_result=None,
                receipt_path=None,
                cost_usd=0.0,
                error=str(exc),
                worktree_path=(
                    worktree_path if config.preserve_failed_worktrees else None
                ),
                branch=(branch_name if config.preserve_failed_worktrees else None),
            )
            _update_manifest(repo_root, swarm_id, ur, manifest_lock)
            return ur

        wall_seconds = time.monotonic() - wall_start

        # Build and write receipt.
        receipt_path: Path | None = None
        with contextlib.suppress(Exception):
            from oh_no_my_claudecode.loop.receipt import build_receipt, write_receipt

            receipt = build_receipt(
                result,
                loop_spec,
                loop_config,
                repo_root=str(unit_root),
                agent=config.agent,
                model=None,
                wall_seconds=wall_seconds,
                onmc_version=_installed_onmc_version(),
                started_at=started_at,
            )
            with contextlib.suppress(Exception):
                receipt_path = write_receipt(repo_root, receipt)

        preserve_worktree = result.converged or config.preserve_failed_worktrees
        if isolation_provider is not None and worktree_path is not None:
            isolation_provider.teardown(worktree_path, keep=preserve_worktree)

        unit_cost = result.total_cost_usd or 0.0
        unit_tokens = result.total_tokens

        # Update swarm-level cost and check cap.
        with cost_lock:
            swarm_total_cost[0] += unit_cost
            swarm_total_tokens[0] += unit_tokens
            if (
                config.swarm_max_cost_usd is not None
                and swarm_total_cost[0] >= config.swarm_max_cost_usd
            ):
                _cost_cap_reached[0] = True

        # Determine status.  A unit is "done" ONLY when its loop actually
        # converged (verified).  Any other terminal stop — agent-error,
        # max-iterations, cost, circuit-breaker — is a "failed" unit, never a
        # silent "done".  Abort stays distinct.
        abort_requested = _is_abort_requested(abort_path, global_abort_path)
        if result.stop_reason == "aborted" or (abort_requested and not result.converged):
            status = "aborted"
        elif result.converged:
            status = "done"
        else:
            status = "failed"

        ur = SwarmUnitResult(
            unit_id=unit.id,
            status=status,
            loop_result=result,
            receipt_path=receipt_path,
            cost_usd=unit_cost,
            error=(f"loop stopped: {result.stop_reason}" if status == "failed" else None),
            worktree_path=(worktree_path if preserve_worktree else None),
            branch=(branch_name if preserve_worktree else None),
            verify_output=(
                result.iterations[-1].verify_output if result.iterations else None
            ),
        )
        _update_manifest(repo_root, swarm_id, ur, manifest_lock)
        return ur

    def _unit_handler(unit: SwarmUnit) -> NodeHandler:
        def _handler(node: NodeSpec) -> NodeResult:
            unit_result = _run_one(unit)
            evidence = _receipt_evidence(swarm_id, unit_result)
            if unit_result.status == "done" and not evidence:
                unit_result = SwarmUnitResult(
                    unit_id=unit_result.unit_id,
                    status="failed",
                    loop_result=unit_result.loop_result,
                    receipt_path=unit_result.receipt_path,
                    cost_usd=unit_result.cost_usd,
                    error="verified worker did not produce a digest-backed receipt",
                    worktree_path=unit_result.worktree_path,
                    branch=unit_result.branch,
                    verify_output=unit_result.verify_output,
                )
                _update_manifest(repo_root, swarm_id, unit_result, manifest_lock)
            with results_lock:
                live_unit_results[unit.id] = unit_result
            status = {
                "done": NodeResultStatus.SUCCEEDED,
                "aborted": NodeResultStatus.SKIPPED,
            }.get(unit_result.status, NodeResultStatus.FAILED)
            return NodeResult(
                node_id=node.node_id,
                status=status,
                idempotency_key=node.idempotency_key or f"{swarm_id}:unit:{unit.id}",
                output=_unit_result_output(unit_result),
                evidence=_receipt_evidence(swarm_id, unit_result),
                error=(
                    None
                    if status is NodeResultStatus.SUCCEEDED
                    else unit_result.error or f"swarm unit {unit.id} {unit_result.status}"
                ),
            )

        return _handler

    runtime_root = _swarm_dir(repo_root, swarm_id) / "runtime"
    backend = NativeExecutionBackend(
        RuntimeStore(runtime_root),
        repo_root=repo_root,
        max_workers=config.concurrency,
        executor=executor,
    )
    def _fan_in_handler(node: NodeSpec) -> NodeResult:
        return _build_fan_in_result(
            repo_root,
            swarm_id,
            runtime_spec,
            node,
            runtime_root,
            manifest_lock,
        )

    handlers: dict[str, NodeHandler] = {
        unit.id: _unit_handler(unit) for unit in units
    }
    handlers["fan-in"] = _fan_in_handler
    runtime_result = backend.execute(runtime_spec, handlers)

    persisted = {
        node_result.node_id: node_result
        for node_result in runtime_result.results
        if node_result.node_id != "fan-in"
    }
    unit_results: list[SwarmUnitResult] = []
    for unit in units:
        unit_result = live_unit_results.get(unit.id)
        if unit_result is None and unit.id in persisted:
            unit_result = _unit_result_from_node_result(persisted[unit.id])
        if unit_result is None:
            unit_result = SwarmUnitResult(
                unit_id=unit.id,
                status="aborted",
                loop_result=None,
                receipt_path=None,
                cost_usd=0.0,
                error="not executed because a dependency failed or the parent run stopped",
            )
            _update_manifest(repo_root, swarm_id, unit_result, manifest_lock)
        unit_results.append(unit_result)

    done_count = sum(1 for r in unit_results if r.status == "done")
    failed_count = sum(1 for r in unit_results if r.status == "failed")
    aborted_count = sum(1 for r in unit_results if r.status == "aborted")

    # Determine swarm stop_reason.
    abort_requested = _is_abort_requested(abort_path, global_abort_path)
    if _cost_cap_reached[0]:
        stop_reason = "cost-cap"
    elif abort_requested or runtime_result.status is RunResultStatus.CANCELLED:
        stop_reason = "aborted"
    elif runtime_result.status is RunResultStatus.FAILED or failed_count:
        stop_reason = "failed"
    else:
        stop_reason = "completed"

    _mark_manifest_done(
        repo_root,
        swarm_id,
        stop_reason,
        runtime_result=runtime_result,
    )

    total_tokens = sum(
        int(node_result.output.get("total_tokens", 0))
        for node_result in persisted.values()
        if isinstance(node_result.output.get("total_tokens", 0), int)
    )

    return SwarmResult(
        swarm_id=swarm_id,
        unit_results=unit_results,
        total_cost_usd=sum(result.cost_usd for result in unit_results),
        total_tokens=total_tokens,
        stop_reason=stop_reason,
        units_done=done_count,
        units_failed=failed_count,
        units_aborted=aborted_count,
    )


# ---------------------------------------------------------------------------
# Version helper
# ---------------------------------------------------------------------------


def _installed_onmc_version() -> str:
    """Return the installed onmc version string, or 'unknown'."""
    try:
        from importlib.metadata import version

        return version("oh-no-my-claudecode")
    except Exception:  # noqa: BLE001
        return "unknown"
