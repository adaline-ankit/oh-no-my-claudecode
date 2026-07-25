"""M4 wiring: the reference monitor + independent verifier in `onmc run`.

Proves the live-run integration end-to-end: an advisory monitor records a
decision trace without blocking, an enforced monitor blocks a denied effect
(run not verified), and an independent-verifier false-green downgrades an
otherwise-converged run — all through the real HarnessController.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from oh_no_my_claudecode.context_engine import ContextEngine
from oh_no_my_claudecode.durable_runtime import RuntimeStore
from oh_no_my_claudecode.enforcement import ReferenceMonitor
from oh_no_my_claudecode.harness_run import (
    ControllerDependencies,
    HarnessController,
    HarnessStatus,
    RunRequest,
)
from oh_no_my_claudecode.harness_run.controller import ChangeSet
from oh_no_my_claudecode.loop.models import IterationContract, LoopResult
from oh_no_my_claudecode.tool_broker import (
    Decision,
    DecisionEffect,
    Policy,
    TokenAuthority,
    ToolBroker,
)


class _AllowCaps:
    def decide(self, action: object) -> Decision:
        del action
        return Decision(DecisionEffect.ALLOW, "test_allow")


class _FakeLoop:
    def __init__(self, result: LoopResult) -> None:
        self.result = result

    def __call__(self, invocation: object) -> LoopResult:
        del invocation
        return self.result


def _loop(*, converged: bool = True) -> LoopResult:
    return LoopResult(
        iterations=[
            IterationContract(
                iteration=1,
                prediction="the change satisfies the task",
                action_summary="applied the change",
                files_touched=["src/app.py"],
                verify_passed=converged,
                verify_output="1 passed" if converged else "1 failed",
                outcome="win" if converged else "loss",
            )
        ],
        converged=converged,
        stop_reason="converged" if converged else "max-iterations",
    )


def _deny_all_broker() -> ToolBroker:
    # Empty policy → deny-by-default for every action (incl. filesystem writes).
    return ToolBroker(policy=Policy(()), token_authority=TokenAuthority(secrets.token_bytes(32)))


def _changes(*paths: str) -> object:
    def _reader(root: Path) -> ChangeSet:
        del root
        return ChangeSet(tuple(paths), len(paths), "\n".join(f"+{p}" for p in paths))

    return _reader


def _controller(
    tmp_path: Path,
    *,
    monitor_factory: object | None = None,
    false_green: object | None = None,
    changes: object | None = None,
    converged: bool = True,
) -> HarnessController:
    deps = ControllerDependencies(
        context_engine=ContextEngine(),
        runtime_store=RuntimeStore(tmp_path / ".onmc" / "harness-runtime"),
        policy_decider=_AllowCaps(),
        loop_executor=_FakeLoop(_loop(converged=converged)),
        reference_monitor_factory=monitor_factory,  # type: ignore[arg-type]
        verifier_false_green_check=false_green,  # type: ignore[arg-type]
        changes_reader=changes or _changes("src/app.py"),  # type: ignore[arg-type]
    )
    return HarnessController(tmp_path, dependencies=deps)


def test_advisory_monitor_records_trace_without_blocking(tmp_path: Path) -> None:
    controller = _controller(
        tmp_path,
        monitor_factory=lambda: ReferenceMonitor(_deny_all_broker(), enforced=False),
    )
    result = controller.run(RunRequest(task="add helper", execute=True))
    # Advisory: even though the deny-all broker denies the fs write, the run
    # still completes — the monitor only records.
    assert result.status is HarnessStatus.COMPLETED
    assert result.enforcement_trace, "expected the monitor to record a decision trace"
    assert all(record["enforced"] is False for record in result.enforcement_trace)


def test_enforced_monitor_blocks_denied_effect(tmp_path: Path) -> None:
    controller = _controller(
        tmp_path,
        monitor_factory=lambda: ReferenceMonitor(_deny_all_broker(), enforced=True),
    )
    result = controller.run(RunRequest(task="write a file", execute=True))
    # Enforced: the denied fs write blocks completion and is never verified.
    assert result.status is HarnessStatus.BLOCKED
    assert result.verified is False


def test_enforced_monitor_allows_when_broker_allows(tmp_path: Path) -> None:
    # A broker that allows everything → enforced monitor does not block.
    class _AllowAll:
        def decide(self, action: object, **kwargs: object) -> Decision:
            del action, kwargs
            return Decision(DecisionEffect.ALLOW, "allow_all")

    monitor = ReferenceMonitor(_AllowAll(), enforced=True)  # type: ignore[arg-type]
    controller = _controller(tmp_path, monitor_factory=lambda: monitor)
    result = controller.run(RunRequest(task="ok change", execute=True))
    assert result.status is HarnessStatus.COMPLETED
    assert result.verified is True


def test_verifier_false_green_downgrades_to_failed(tmp_path: Path) -> None:
    controller = _controller(
        tmp_path,
        false_green=lambda request, signals, change_set: True,
    )
    result = controller.run(RunRequest(task="sneaky green", execute=True))
    # A converged, proof-graph-complete run is still failed when the independent
    # verifier flags a false green — and is never verified.
    assert result.status is HarnessStatus.FAILED
    assert result.proof_complete is False
    assert result.verified is False


def test_monitor_policy_allows_repo_run_but_denies_traversal(tmp_path: Path) -> None:
    # The default monitor policy makes enforced mode usable for a real run:
    # repo-scoped writes and verifier commands ALLOW; out-of-repo writes DENY.
    from oh_no_my_claudecode.enforcement import Effect
    from oh_no_my_claudecode.harness_run.controller import _monitor_policy

    monitor = ReferenceMonitor(_monitor_policy(tmp_path), enforced=True)
    in_repo = monitor.guard(Effect.filesystem("write", str(tmp_path / "calc.py")))
    verifier = monitor.guard(Effect.command(("python", "-m", "pytest", "-q")))
    traversal = monitor.guard(Effect.filesystem("write", str(tmp_path / ".." / "etc" / "passwd")))
    assert in_repo.effect is DecisionEffect.ALLOW
    assert verifier.effect is DecisionEffect.ALLOW
    assert traversal.effect is not DecisionEffect.ALLOW


def test_no_monitor_and_no_checker_is_behavior_preserving(tmp_path: Path) -> None:
    controller = _controller(tmp_path)  # both seams unset
    result = controller.run(RunRequest(task="plain run", execute=True))
    assert result.status is HarnessStatus.COMPLETED
    assert result.verified is True
    assert result.enforcement_trace == ()


def test_default_dependencies_monitor_is_enforced_by_default(tmp_path: Path) -> None:
    # Production wiring now enforces: the default monitor blocks denied effects.
    from oh_no_my_claudecode.harness_run.controller import default_dependencies

    deps = default_dependencies(tmp_path)
    assert deps.reference_monitor_factory is not None
    monitor = deps.reference_monitor_factory()
    assert monitor.enforced is True
