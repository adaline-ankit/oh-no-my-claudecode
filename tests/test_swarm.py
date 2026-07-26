"""Tests for the onmc swarm orchestrator.

Tests use injected fake agent runners. One isolation regression test creates a
real disposable git worktree; no real coding-agent process is launched.

Coverage:
- run_loop should_continue=False → stop_reason "aborted" (abort hook unit test)
- run_swarm drains all units with bounded concurrency
  (instrumented fake: assert max concurrent <= config.concurrency)
- Each unit produces a status ("done"/"aborted") and a receipt path (or None)
- swarm_max_cost_usd stops launching new units once exceeded
- ABORT flag → running unit stops with "aborted"; queued units don't start
- Swarm state is persisted to .onmc/swarm/<id>/manifest.json
- request_abort / swarm_state / swarm_list work
- CLI: swarm run / status / list / abort exit codes + --json
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.loop.engine import run_loop
from oh_no_my_claudecode.loop.models import (
    AgentRunResult,
    LoopConfig,
    LoopSpec,
    VerifyOutcome,
)
from oh_no_my_claudecode.runtime import RunSpec, RuntimeContractError
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.swarm.models import SwarmConfig, SwarmUnit
from oh_no_my_claudecode.swarm.orchestrator import (
    _run_verify_command,
    request_abort,
    run_swarm,
    swarm_state,
)
from oh_no_my_claudecode.swarm.runtime_contract import (
    SwarmContractUnit,
    build_swarm_run_spec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2024, 8, 1, 10, 0, 0, tzinfo=UTC)


def _storage(tmp_path: Path) -> SQLiteStorage:
    s = SQLiteStorage(tmp_path / "onmc.db")
    s.initialize()
    return s


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _fake_agent(
    output: str = "done",
    tokens: int | None = 10,
    cost: float | None = 0.01,
) -> Callable[..., AgentRunResult]:
    """Fake AgentRunner that immediately returns success."""

    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output=output,
            prediction="ok",
            files_touched=[],
            tokens=tokens,
            cost_usd=cost,
        )

    return _runner


def _fake_verify(passes: bool = True, output: str = "ok") -> Callable[..., VerifyOutcome]:
    """Fake VerifyRunner."""

    def _runner(command: str) -> VerifyOutcome:
        del command
        return VerifyOutcome(passed=passes, output=output)

    return _runner


def test_swarm_contract_compiles_dependencies_and_rejects_unordered_claim_overlap() -> None:
    spec = build_swarm_run_spec(
        swarm_id="contract-dependencies",
        units=(
            SwarmContractUnit(unit_id="plan", goal="plan"),
            SwarmContractUnit(
                unit_id="implement",
                goal="implement",
                dependencies=("plan",),
            ),
        ),
        agent="codex",
        mode="process",
        concurrency=2,
    )

    assert spec.nodes[1].dependencies == ("plan",)
    assert spec.nodes[-1].dependencies == ("plan", "implement")

    with pytest.raises(RuntimeContractError, match="overlapping file claims"):
        build_swarm_run_spec(
            swarm_id="claim-conflict",
            units=(
                SwarmContractUnit(
                    unit_id="a",
                    goal="a",
                    allowed_paths=("src/shared.py",),
                ),
                SwarmContractUnit(
                    unit_id="b",
                    goal="b",
                    allowed_paths=("src/shared.py",),
                ),
            ),
            agent="codex",
            mode="process",
            concurrency=2,
        )


# ---------------------------------------------------------------------------
# run_loop abort hook unit tests
# ---------------------------------------------------------------------------


class TestRunLoopAbortHook:
    """Unit tests for the should_continue abort hook in run_loop."""

    def test_should_continue_none_unchanged_behavior(self, tmp_path: Path) -> None:
        """should_continue=None must not change existing loop behavior."""
        storage = _storage(tmp_path)
        spec = LoopSpec(goal="test goal")
        config = LoopConfig(max_iterations=3)

        result = run_loop(
            storage,
            tmp_path,
            spec,
            config,
            agent_runner=_fake_agent(),
            verify_runner=_fake_verify(passes=True),
            now=_FIXED_NOW,
            should_continue=None,  # explicit None — must be unchanged
        )

        assert result.converged is True
        assert result.stop_reason == "converged"

    def test_should_continue_false_before_first_iteration(self, tmp_path: Path) -> None:
        """A should_continue that returns False immediately → stop_reason='aborted'."""
        storage = _storage(tmp_path)
        spec = LoopSpec(goal="abort immediately")
        config = LoopConfig(max_iterations=10)

        result = run_loop(
            storage,
            tmp_path,
            spec,
            config,
            agent_runner=_fake_agent(),
            verify_runner=_fake_verify(passes=False),
            now=_FIXED_NOW,
            should_continue=lambda: False,
        )

        assert result.stop_reason == "aborted"
        assert result.converged is False
        # Agent should never have run — no iterations recorded.
        assert len(result.iterations) == 0

    def test_should_continue_false_after_one_iteration(self, tmp_path: Path) -> None:
        """Abort after the first iteration: exactly one iteration recorded."""
        storage = _storage(tmp_path)
        spec = LoopSpec(goal="abort after one iter")
        config = LoopConfig(max_iterations=10)

        call_count = [0]

        def _sc() -> bool:
            call_count[0] += 1
            # Allow first iteration (check before iter 1 → True), deny before iter 2.
            return call_count[0] <= 1

        result = run_loop(
            storage,
            tmp_path,
            spec,
            config,
            agent_runner=_fake_agent(),
            verify_runner=_fake_verify(passes=False),  # fail so loop doesn't converge
            now=_FIXED_NOW,
            should_continue=_sc,
        )

        assert result.stop_reason == "aborted"
        assert len(result.iterations) == 1

    def test_should_continue_true_loop_completes_normally(self, tmp_path: Path) -> None:
        """A should_continue that always returns True must not prevent convergence."""
        storage = _storage(tmp_path)
        spec = LoopSpec(goal="complete normally")
        config = LoopConfig(max_iterations=5)

        result = run_loop(
            storage,
            tmp_path,
            spec,
            config,
            agent_runner=_fake_agent(),
            verify_runner=_fake_verify(passes=True),
            now=_FIXED_NOW,
            should_continue=lambda: True,
        )

        assert result.converged is True
        assert result.stop_reason == "converged"


# ---------------------------------------------------------------------------
# run_swarm core tests
# ---------------------------------------------------------------------------


def _make_units(n: int, verify: str | None = None) -> list[SwarmUnit]:
    return [SwarmUnit(id=f"u{i:03d}", goal=f"goal {i}", verify_command=verify) for i in range(n)]


def _make_config(concurrency: int = 2, **kwargs: Any) -> SwarmConfig:
    return SwarmConfig(concurrency=concurrency, **kwargs)


def _fake_runner_factory(
    agent_fn: Callable[..., AgentRunResult] | None = None,
    verify_fn: Callable[..., VerifyOutcome] | None = None,
) -> tuple[Any, Any]:
    """Build injectable runner factories for run_swarm tests."""
    _agent = agent_fn or _fake_agent()
    _verify = verify_fn or _fake_verify(passes=True)

    def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
        del unit, repo_root
        return _agent

    def _vf(unit: SwarmUnit, repo_root: Path) -> Callable[..., VerifyOutcome]:
        del unit, repo_root
        return _verify

    return _af, _vf


class TestRunSwarm:
    """Tests for run_swarm orchestrator logic."""

    def test_drains_all_units(self, tmp_path: Path) -> None:
        """run_swarm must complete all units when no abort/cap."""
        storage = _storage(tmp_path)
        units = _make_units(5)
        cfg = _make_config(concurrency=3)
        af, vf = _fake_runner_factory()

        result = run_swarm(
            storage,
            tmp_path,
            units,
            cfg,
            runner_factory=af,
            verify_factory=vf,
            executor=ThreadPoolExecutor(max_workers=3),
            now=_FIXED_NOW,
        )

        assert len(result.unit_results) == 5
        assert result.units_done == 5
        assert result.units_failed == 0
        assert result.units_aborted == 0
        assert result.stop_reason == "completed"

    def test_vacuous_unit_is_failed_not_done(self, tmp_path: Path) -> None:
        """A unit whose verify passes but whose agent changed NOTHING must be
        scored 'failed' (vacuous pass), never 'done' — the swarm-level port of
        the loop's false-green gate."""
        storage = _storage(tmp_path)
        units = _make_units(3)
        cfg = _make_config(concurrency=2)
        af, vf = _fake_runner_factory()  # verify always passes

        def _static_probe_factory(unit: SwarmUnit, repo_root: Path) -> Any:
            del unit, repo_root

            def _probe() -> str | None:
                return "unchanged"  # tree never changes

            return _probe

        result = run_swarm(
            storage,
            tmp_path,
            units,
            cfg,
            runner_factory=af,
            verify_factory=vf,
            change_probe_factory=_static_probe_factory,
            executor=ThreadPoolExecutor(max_workers=2),
            now=_FIXED_NOW,
        )

        assert result.units_done == 0
        assert result.units_failed == 3
        for ur in result.unit_results:
            assert ur.status == "failed"
            assert ur.loop_result is not None
            assert ur.loop_result.converged is False
            assert ur.loop_result.stop_reason == "no-changes"

    def test_changed_tree_unit_is_done(self, tmp_path: Path) -> None:
        """With a probe that reports a new signature each call (agent changed
        the tree), a passing verify converges the unit as before."""
        storage = _storage(tmp_path)
        units = _make_units(2)
        cfg = _make_config(concurrency=2)
        af, vf = _fake_runner_factory()

        def _changing_probe_factory(unit: SwarmUnit, repo_root: Path) -> Any:
            del unit, repo_root
            counter = [0]

            def _probe() -> str | None:
                counter[0] += 1
                return f"sig-{counter[0]}"

            return _probe

        result = run_swarm(
            storage,
            tmp_path,
            units,
            cfg,
            runner_factory=af,
            verify_factory=vf,
            change_probe_factory=_changing_probe_factory,
            executor=ThreadPoolExecutor(max_workers=2),
            now=_FIXED_NOW,
        )

        assert result.units_done == 2
        assert result.units_failed == 0
        for ur in result.unit_results:
            assert ur.status == "done"
            assert ur.loop_result is not None
            assert ur.loop_result.converged is True

    def test_bounded_concurrency(self, tmp_path: Path) -> None:
        """Max concurrent workers must never exceed config.concurrency."""
        storage = _storage(tmp_path)
        concurrency = 2
        units = _make_units(6)
        cfg = _make_config(concurrency=concurrency)

        # Track peak concurrent executions.
        active_counter = [0]
        peak_active = [0]
        counter_lock = threading.Lock()
        event = threading.Event()

        def _slow_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
            with counter_lock:
                active_counter[0] += 1
                if active_counter[0] > peak_active[0]:
                    peak_active[0] = active_counter[0]
            event.wait(timeout=0.05)  # brief pause so overlap can be measured
            with counter_lock:
                active_counter[0] -= 1
            return AgentRunResult(
                output="done",
                prediction="ok",
                files_touched=[],
                tokens=1,
                cost_usd=0.001,
            )

        def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
            del unit, repo_root
            return _slow_agent

        def _vf(unit: SwarmUnit, repo_root: Path) -> Callable[..., VerifyOutcome]:
            del unit, repo_root
            return _fake_verify(passes=True)

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            result = run_swarm(
                storage,
                tmp_path,
                units,
                cfg,
                runner_factory=_af,
                verify_factory=_vf,
                executor=pool,
                now=_FIXED_NOW,
            )

        assert peak_active[0] <= concurrency, (
            f"Peak concurrent {peak_active[0]} exceeded concurrency={concurrency}"
        )
        assert result.units_done == 6

    def test_each_unit_has_receipt_or_none(self, tmp_path: Path) -> None:
        """Each unit result must have a receipt_path (Path or None) — never unset."""
        storage = _storage(tmp_path)
        units = _make_units(3)
        cfg = _make_config()
        af, vf = _fake_runner_factory()

        result = run_swarm(
            storage, tmp_path, units, cfg, runner_factory=af, verify_factory=vf,
            now=_FIXED_NOW,
        )

        for ur in result.unit_results:
            # receipt_path is either None or an existing Path object.
            assert ur.receipt_path is None or isinstance(ur.receipt_path, Path), (
                f"unit {ur.unit_id}: unexpected receipt_path type {type(ur.receipt_path)}"
            )

    def test_swarm_max_cost_usd_stops_new_units(self, tmp_path: Path) -> None:
        """Once swarm_max_cost_usd is reached, new units should be aborted."""
        storage = _storage(tmp_path)
        # Each unit costs 0.05 USD.  Cap at 0.07 → only 1 unit should complete.
        units = _make_units(10)
        cfg = SwarmConfig(
            concurrency=1,  # sequential so ordering is deterministic
            agent="claude",
            swarm_max_cost_usd=0.07,
        )
        # Agent reports 0.05 USD per run.
        af, vf = _fake_runner_factory(
            agent_fn=_fake_agent(cost=0.05),
            verify_fn=_fake_verify(passes=True),
        )

        result = run_swarm(
            storage,
            tmp_path,
            units,
            cfg,
            runner_factory=af,
            verify_factory=vf,
            executor=ThreadPoolExecutor(max_workers=1),
            now=_FIXED_NOW,
        )

        # At least some units must be aborted due to cost cap.
        assert result.units_aborted > 0, "Expected some units to be aborted by cost cap"
        assert result.stop_reason in {"cost-cap", "completed"}
        # Total cost must not hugely exceed the cap (already-started units finish).
        assert result.total_cost_usd <= 0.07 * 3, (
            f"Total cost {result.total_cost_usd} far exceeds cap"
        )

    def test_abort_flag_stops_queued_units(self, tmp_path: Path) -> None:
        """Writing the ABORT file stops running units and prevents queued ones from starting."""
        storage = _storage(tmp_path)
        units = _make_units(8)
        cfg = _make_config(concurrency=2)

        abort_written = threading.Event()

        def _abort_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
            # Write abort after first call.
            if not abort_written.is_set():
                # Figure out swarm_id from the manifest directory (side-channel).
                # We write the global ABORT so we don't need to know swarm_id.
                (tmp_path / ".onmc" / "swarm" / "ABORT").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (tmp_path / ".onmc" / "swarm" / "ABORT").write_text("abort")
                abort_written.set()
            return AgentRunResult(
                output="done",
                prediction="ok",
                files_touched=[],
                tokens=1,
                cost_usd=0.001,
            )

        def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
            del unit, repo_root
            return _abort_agent

        def _vf(unit: SwarmUnit, repo_root: Path) -> Callable[..., VerifyOutcome]:
            del unit, repo_root
            return _fake_verify(passes=False)  # fail so loop doesn't converge early

        result = run_swarm(
            storage,
            tmp_path,
            units,
            cfg,
            runner_factory=_af,
            verify_factory=_vf,
            executor=ThreadPoolExecutor(max_workers=2),
            now=_FIXED_NOW,
        )

        # Some units must be aborted.
        assert result.units_aborted > 0 or result.stop_reason == "aborted"
        # Not all 8 should be "done" (the abort should prevent some).
        assert result.units_done < 8

    def test_swarm_state_persisted_to_manifest(self, tmp_path: Path) -> None:
        """run_swarm must write manifest.json to .onmc/swarm/<id>/."""
        storage = _storage(tmp_path)
        units = _make_units(3)
        cfg = _make_config(concurrency=2)
        af, vf = _fake_runner_factory()

        result = run_swarm(
            storage, tmp_path, units, cfg, runner_factory=af, verify_factory=vf,
            now=_FIXED_NOW,
        )

        swarm_dir = tmp_path / ".onmc" / "swarm" / result.swarm_id
        assert swarm_dir.exists(), f"Swarm dir not found: {swarm_dir}"
        mpath = swarm_dir / "manifest.json"
        assert mpath.exists(), "manifest.json not written"

        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        assert manifest["swarm_id"] == result.swarm_id
        assert manifest["mode"] == "process"
        assert "units" in manifest
        assert len(manifest["units"]) == 3
        from oh_no_my_claudecode.runtime import RunSpec

        spec = RunSpec.from_dict(manifest["runtime_contract"])
        assert manifest["runtime_contract_digest"] == spec.digest
        assert spec.run_id == f"swarm-{result.swarm_id}"
        assert [node.node_id for node in spec.topological_order()][-1] == "fan-in"

    def test_dependencies_control_execution_and_emit_deterministic_fan_in(
        self,
        tmp_path: Path,
    ) -> None:
        storage = _storage(tmp_path)
        units = [
            SwarmUnit(id="plan", goal="plan", verify_command="true"),
            SwarmUnit(
                id="implement-a",
                goal="implement a",
                verify_command="true",
                dependencies=["plan"],
            ),
            SwarmUnit(
                id="implement-b",
                goal="implement b",
                verify_command="true",
                dependencies=["plan"],
            ),
            SwarmUnit(
                id="verify",
                goal="verify",
                verify_command="true",
                dependencies=["implement-a", "implement-b"],
            ),
        ]
        calls: list[str] = []
        call_lock = threading.Lock()

        def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
            del repo_root

            def _agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
                del prompt, escalation_level
                with call_lock:
                    calls.append(unit.id)
                return AgentRunResult(
                    output="done",
                    prediction="ok",
                    files_touched=[f"{unit.id}.txt"],
                    tokens=1,
                    cost_usd=0.0,
                )

            return _agent

        def _vf(unit: SwarmUnit, repo_root: Path) -> Callable[..., VerifyOutcome]:
            del unit, repo_root
            return _fake_verify(passes=True)

        result = run_swarm(
            storage,
            tmp_path,
            units,
            _make_config(concurrency=2, isolate=False),
            runner_factory=_af,
            verify_factory=_vf,
            now=_FIXED_NOW,
            swarm_id="dependency-order",
        )

        assert result.stop_reason == "completed"
        assert calls.index("plan") < calls.index("implement-a")
        assert calls.index("plan") < calls.index("implement-b")
        assert calls.index("verify") > calls.index("implement-a")
        assert calls.index("verify") > calls.index("implement-b")
        assert [item.unit_id for item in result.unit_results] == [
            "plan",
            "implement-a",
            "implement-b",
            "verify",
        ]

        manifest = swarm_state(tmp_path, result.swarm_id)
        spec = RunSpec.from_dict(manifest["runtime_contract"])
        assert spec.nodes[1].dependencies == ("plan",)
        assert spec.nodes[2].dependencies == ("plan",)
        assert spec.nodes[3].dependencies == ("implement-a", "implement-b")
        fan_in = manifest["fan_in"]
        assert fan_in["unit_order"] == [
            "plan",
            "implement-a",
            "implement-b",
            "verify",
        ]
        assert fan_in["evidence"]["digest"].startswith("sha256:")
        assert Path(fan_in["evidence"]["uri"]).exists()
        assert manifest["runtime_result"]["status"] == "completed"

    def test_failed_worker_cancels_dependents_but_preserves_sibling_receipt(
        self,
        tmp_path: Path,
    ) -> None:
        storage = _storage(tmp_path)
        units = [
            SwarmUnit(id="failed", goal="fail", verify_command="true"),
            SwarmUnit(id="sibling", goal="succeed", verify_command="true"),
            SwarmUnit(
                id="dependent",
                goal="must not start",
                verify_command="true",
                dependencies=["failed"],
            ),
        ]
        started: list[str] = []

        def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
            del repo_root

            def _agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
                del prompt, escalation_level
                started.append(unit.id)
                return AgentRunResult(
                    output="failed" if unit.id == "failed" else "done",
                    prediction="",
                    files_touched=[f"{unit.id}.txt"],
                    tokens=1,
                    error="simulated failure" if unit.id == "failed" else None,
                )

            return _agent

        def _vf(unit: SwarmUnit, repo_root: Path) -> Callable[..., VerifyOutcome]:
            del repo_root
            return _fake_verify(passes=unit.id != "failed")

        result = run_swarm(
            storage,
            tmp_path,
            units,
            _make_config(concurrency=2, isolate=False, max_iterations=1),
            runner_factory=_af,
            verify_factory=_vf,
            now=_FIXED_NOW,
            swarm_id="failure-propagation",
        )

        assert result.stop_reason == "failed"
        assert set(started) == {"failed", "sibling"}
        assert "dependent" not in started
        assert [item.status for item in result.unit_results] == [
            "failed",
            "done",
            "aborted",
        ]
        sibling = result.unit_results[1]
        assert sibling.receipt_path is not None
        assert sibling.receipt_path.exists()
        manifest = swarm_state(tmp_path, result.swarm_id)
        assert manifest["units"]["sibling"]["receipt_path"] == str(sibling.receipt_path)
        assert manifest["units"]["dependent"]["status"] == "aborted"
        assert "fan_in" not in manifest
        assert manifest["runtime_result"]["status"] == "failed"

    def test_swarm_replay_is_idempotent(self, tmp_path: Path) -> None:
        storage = _storage(tmp_path)
        units = [SwarmUnit(id="only", goal="one side effect", verify_command="true")]
        calls = 0

        def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
            del unit, repo_root

            def _agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
                nonlocal calls
                del prompt, escalation_level
                calls += 1
                return AgentRunResult(
                    output="done",
                    prediction="ok",
                    files_touched=["only.txt"],
                    tokens=1,
                )

            return _agent

        def _vf(unit: SwarmUnit, repo_root: Path) -> Callable[..., VerifyOutcome]:
            del unit, repo_root
            return _fake_verify(passes=True)

        kwargs = {
            "runner_factory": _af,
            "verify_factory": _vf,
            "now": _FIXED_NOW,
            "swarm_id": "stable-idempotency",
        }
        first = run_swarm(
            storage,
            tmp_path,
            units,
            _make_config(concurrency=1, isolate=False),
            **kwargs,
        )
        second = run_swarm(
            storage,
            tmp_path,
            units,
            _make_config(concurrency=1, isolate=False),
            **kwargs,
        )

        assert calls == 1
        assert second.stop_reason == "completed"
        assert second.unit_results[0].receipt_path == first.unit_results[0].receipt_path
        assert swarm_state(tmp_path, second.swarm_id)["runtime_result"]["status"] == "completed"

    def test_request_abort_writes_sentinel(self, tmp_path: Path) -> None:
        """request_abort(swarm_id) must write ABORT file."""
        request_abort(tmp_path, swarm_id="test-swarm-123")
        apath = tmp_path / ".onmc" / "swarm" / "test-swarm-123" / "ABORT"
        assert apath.exists()

    def test_request_abort_global(self, tmp_path: Path) -> None:
        """request_abort(swarm_id=None) must write global ABORT file."""
        request_abort(tmp_path, swarm_id=None)
        gpath = tmp_path / ".onmc" / "swarm" / "ABORT"
        assert gpath.exists()

    def test_swarm_state_returns_manifest(self, tmp_path: Path) -> None:
        """swarm_state(repo_root, swarm_id) returns manifest dict after run."""
        storage = _storage(tmp_path)
        units = _make_units(2)
        cfg = _make_config(concurrency=1)
        af, vf = _fake_runner_factory()

        result = run_swarm(
            storage, tmp_path, units, cfg, runner_factory=af, verify_factory=vf,
            now=_FIXED_NOW,
        )

        state = swarm_state(tmp_path, result.swarm_id)
        assert state["swarm_id"] == result.swarm_id
        assert "units" in state

    def test_swarm_state_all_returns_dict(self, tmp_path: Path) -> None:
        """swarm_state(repo_root, None) returns dict keyed by swarm_id."""
        storage = _storage(tmp_path)
        units = _make_units(2)
        cfg = _make_config(concurrency=1)
        af, vf = _fake_runner_factory()

        result = run_swarm(
            storage, tmp_path, units, cfg, runner_factory=af, verify_factory=vf,
            now=_FIXED_NOW,
        )

        all_state = swarm_state(tmp_path, None)
        assert isinstance(all_state, dict)
        assert result.swarm_id in all_state

    def test_unit_fails_gracefully(self, tmp_path: Path) -> None:
        """A unit whose agent raises an exception gets status='failed', not a crash."""
        storage = _storage(tmp_path)
        units = _make_units(3)
        cfg = _make_config(concurrency=1)

        call_count = [0]

        def _boom_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("simulated agent failure")
            return AgentRunResult(
                output="ok", prediction="ok", files_touched=[], tokens=1, cost_usd=0.0
            )

        def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
            del unit, repo_root
            return _boom_agent

        def _vf(unit: SwarmUnit, repo_root: Path) -> Callable[..., VerifyOutcome]:
            del unit, repo_root
            return _fake_verify(passes=True)

        result = run_swarm(
            storage,
            tmp_path,
            units,
            cfg,
            runner_factory=_af,
            verify_factory=_vf,
            executor=ThreadPoolExecutor(max_workers=1),
            now=_FIXED_NOW,
        )

        failed = [ur for ur in result.unit_results if ur.status == "failed"]
        assert len(failed) == 1
        assert failed[0].error is not None
        # Other units must still complete.
        assert result.units_done >= 2

    def test_isolated_swarm_binds_agent_and_verify_to_worktree(
        self,
        tmp_path: Path,
    ) -> None:
        """Process swarm must run agent and verify in the isolated worktree."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        storage = _storage(tmp_path)
        units = _make_units(1)
        cfg = _make_config(concurrency=1, isolate=True)
        seen_roots: list[Path] = []

        def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
            del unit
            seen_roots.append(repo_root)

            def _agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
                del prompt, escalation_level
                marker = repo_root / "worker.txt"
                marker.write_text("ok\n", encoding="utf-8")
                return AgentRunResult(
                    output="wrote marker",
                    prediction="worker marker exists",
                    files_touched=["worker.txt"],
                    tokens=1,
                    cost_usd=0.0,
                )

            return _agent

        def _vf(unit: SwarmUnit, repo_root: Path) -> Callable[..., VerifyOutcome]:
            del unit

            def _verify(command: str) -> VerifyOutcome:
                del command
                return VerifyOutcome(
                    passed=(repo_root / "worker.txt").read_text(encoding="utf-8") == "ok\n",
                    output="checked marker",
                )

            return _verify

        result = run_swarm(
            storage,
            repo,
            units,
            cfg,
            runner_factory=_af,
            verify_factory=_vf,
            executor=ThreadPoolExecutor(max_workers=1),
            now=_FIXED_NOW,
        )

        assert result.units_done == 1
        assert seen_roots and seen_roots[0] != repo
        assert not (repo / "worker.txt").exists()
        assert (seen_roots[0] / "worker.txt").exists()

        subprocess.run(
            ["git", "worktree", "remove", "--force", str(seen_roots[0])],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
        shutil.rmtree(seen_roots[0].parent, ignore_errors=True)

    def test_failed_unit_preserves_recoverable_worktree(self, tmp_path: Path) -> None:
        """Failed agent work must survive with branch/path recovery metadata."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        storage = _storage(tmp_path)
        units = _make_units(1)
        cfg = _make_config(
            concurrency=1,
            isolate=True,
            max_iterations=1,
            preserve_failed_worktrees=True,
        )

        def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
            del unit

            def _agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
                del prompt, escalation_level
                (repo_root / "partial.txt").write_text("recover me\n", encoding="utf-8")
                return AgentRunResult(
                    output="partial work",
                    prediction="tests still fail",
                    files_touched=["partial.txt"],
                    tokens=1,
                )

            return _agent

        def _vf(unit: SwarmUnit, repo_root: Path) -> Callable[..., VerifyOutcome]:
            del unit, repo_root
            return _fake_verify(passes=False, output="still failing")

        result = run_swarm(
            storage,
            repo,
            units,
            cfg,
            runner_factory=_af,
            verify_factory=_vf,
            executor=ThreadPoolExecutor(max_workers=1),
            now=_FIXED_NOW,
        )

        unit = result.unit_results[0]
        assert unit.status == "failed"
        assert unit.worktree_path is not None
        assert unit.worktree_path.exists()
        assert (unit.worktree_path / "partial.txt").read_text(encoding="utf-8") == "recover me\n"
        assert unit.branch
        manifest = swarm_state(repo, result.swarm_id)
        assert manifest["agent_timeout_seconds"] == 1200
        assert manifest["preserve_failed_worktrees"] is True
        saved = manifest["units"][unit.unit_id]
        assert saved["worktree_path"] == str(unit.worktree_path)
        assert saved["branch"] == unit.branch
        assert saved["verify_output"] == "still failing"

        subprocess.run(
            ["git", "worktree", "remove", "--force", str(unit.worktree_path)],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
        shutil.rmtree(unit.worktree_path.parent, ignore_errors=True)

    def test_abort_requested_during_agent_failure_reports_aborted(self, tmp_path: Path) -> None:
        """An agent terminated after ABORT must not be misreported as failed."""
        storage = _storage(tmp_path)
        units = _make_units(1)
        cfg = _make_config(concurrency=1, isolate=False)

        def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
            del unit

            def _agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
                del prompt, escalation_level
                (repo_root / ".onmc" / "swarm" / "ABORT").write_text(
                    "abort", encoding="utf-8"
                )
                return AgentRunResult(
                    output="terminated",
                    prediction="",
                    files_touched=[],
                    error="terminated by user",
                )

            return _agent

        af, vf = _fake_runner_factory(agent_fn=None, verify_fn=_fake_verify(passes=False))
        del af
        result = run_swarm(
            storage,
            tmp_path,
            units,
            cfg,
            runner_factory=_af,
            verify_factory=vf,
            executor=ThreadPoolExecutor(max_workers=1),
            now=_FIXED_NOW,
        )

        assert result.unit_results[0].status == "aborted"
        assert result.units_aborted == 1
        assert result.units_failed == 0


def test_verify_command_does_not_execute_shell_operators(tmp_path: Path) -> None:
    marker = tmp_path / "owned"
    outcome = _run_verify_command(
        f"python3 -c 'print(1)' && touch {marker}",
        tmp_path,
    )

    assert outcome.passed is False
    assert not marker.exists()


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences so substring checks survive Rich styling."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestSwarmCLI:
    """CLI-level tests for `onmc swarm *` commands.

    These tests do NOT invoke real agents.  The CLI needs an onmc-initialized
    repo to run _service()._load_context(); we skip gracefully when not available.
    """

    def _invoke(self, *args: str) -> object:
        runner = _cli_runner()
        return runner.invoke(app, list(args), catch_exceptions=False)

    def test_swarm_help_exits_zero(self) -> None:
        result = _cli_runner().invoke(app, ["swarm", "--help"])
        assert result.exit_code == 0
        assert "swarm" in result.output.lower() or "parallel" in result.output.lower()

    def test_swarm_run_help_exits_zero(self) -> None:
        result = _cli_runner().invoke(app, ["swarm", "run", "--help"])
        assert result.exit_code == 0

    def test_swarm_status_help_exits_zero(self) -> None:
        result = _cli_runner().invoke(app, ["swarm", "status", "--help"])
        assert result.exit_code == 0

    def test_swarm_list_help_exits_zero(self) -> None:
        result = _cli_runner().invoke(app, ["swarm", "list", "--help"])
        assert result.exit_code == 0

    def test_swarm_abort_help_exits_zero(self) -> None:
        result = _cli_runner().invoke(app, ["swarm", "abort", "--help"])
        assert result.exit_code == 0

    def test_swarm_run_no_args_exits_nonzero(self) -> None:
        """Running without --task or --file should fail gracefully."""
        result = _cli_runner().invoke(app, ["swarm", "run"])
        # Exit with non-zero (error) — not a crash.
        assert result.exit_code != 0

    def test_swarm_run_both_task_and_file_exits_nonzero(self, tmp_path: Path) -> None:
        """Providing both --task and --file must exit non-zero."""
        f = tmp_path / "tasks.txt"
        f.write_text("goal A\n", encoding="utf-8")
        result = _cli_runner().invoke(app, ["swarm", "run", "--task", "g", "--file", str(f)])
        assert result.exit_code != 0

    def test_swarm_abort_no_args_exits_nonzero(self) -> None:
        """abort with no args and no --all must fail."""
        result = _cli_runner().invoke(app, ["swarm", "abort"])
        assert result.exit_code != 0

    def test_swarm_abort_both_id_and_all_exits_nonzero(self) -> None:
        """abort with both a swarm_id and --all must fail."""
        result = _cli_runner().invoke(app, ["swarm", "abort", "abc123", "--all"])
        assert result.exit_code != 0

    def test_swarm_run_accepts_json_flag(self) -> None:
        """--json must be a real option (render-independent: not a help-text scrape).

        Rendered --help output flakes in CI (Rich wraps/ANSI by terminal width),
        so prove the option exists functionally: invoking it without --task fails
        for the MISSING TASK, never with 'no such option'.
        """
        result = _cli_runner().invoke(app, ["swarm", "run", "--json"])
        assert result.exit_code != 0
        assert "no such option" not in _strip_ansi(result.output).lower()

    def test_swarm_run_accepts_concurrency_flag(self) -> None:
        """--concurrency must be a real option (functional check, not help scrape)."""
        result = _cli_runner().invoke(app, ["swarm", "run", "--concurrency", "2"])
        assert result.exit_code != 0
        assert "no such option" not in _strip_ansi(result.output).lower()

    def test_swarm_run_accepts_recovery_flags(self) -> None:
        """Timeout and recovery controls must be real CLI options."""
        result = _cli_runner().invoke(
            app,
            [
                "swarm",
                "run",
                "--agent-timeout-seconds",
                "30",
                "--discard-failed-worktrees",
            ],
        )
        assert result.exit_code != 0
        assert "no such option" not in _strip_ansi(result.output).lower()


class TestSwarmHonestStatus:
    """A unit is 'done' only when its loop actually converged."""

    def test_nonconverging_unit_is_failed_not_done(self, tmp_path: Path) -> None:
        """A unit whose loop never converges must report status='failed'."""
        storage = _storage(tmp_path)
        units = _make_units(2)
        cfg = _make_config(concurrency=2)
        # Agent runs fine, but verify NEVER passes → loop hits max-iterations,
        # converged=False. Pre-fix this was silently reported as 'done'.
        af, vf = _fake_runner_factory(verify_fn=_fake_verify(passes=False))

        result = run_swarm(
            storage,
            tmp_path,
            units,
            cfg,
            runner_factory=af,
            verify_factory=vf,
            executor=ThreadPoolExecutor(max_workers=2),
            now=_FIXED_NOW,
        )

        assert result.units_done == 0
        assert result.units_failed == 2
        assert result.stop_reason == "failed"
        for ur in result.unit_results:
            assert ur.status == "failed"
            assert ur.error is not None

    def test_agent_error_unit_is_failed(self, tmp_path: Path) -> None:
        """A unit whose agent returns an error is failed with agent-error."""
        storage = _storage(tmp_path)
        units = _make_units(1)
        cfg = _make_config(concurrency=1)

        def _err_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
            del prompt, escalation_level
            return AgentRunResult(
                output="401 auth error",
                prediction="",
                files_touched=[],
                tokens=None,
                error="401 auth error",
            )

        def _af(unit: SwarmUnit, repo_root: Path) -> Callable[..., AgentRunResult]:
            del unit, repo_root
            return _err_agent

        def _vf(unit: SwarmUnit, repo_root: Path) -> Callable[..., VerifyOutcome]:
            del unit, repo_root
            return _fake_verify(passes=True)  # would falsely pass pre-fix

        result = run_swarm(
            storage,
            tmp_path,
            units,
            cfg,
            runner_factory=_af,
            verify_factory=_vf,
            executor=ThreadPoolExecutor(max_workers=1),
            now=_FIXED_NOW,
        )

        assert result.units_done == 0
        assert result.units_failed == 1
        ur = result.unit_results[0]
        assert ur.status == "failed"
        assert ur.loop_result is not None
        assert ur.loop_result.stop_reason == "agent-error"


# ---------------------------------------------------------------------------
# In-session (inline / subagent) swarm — token-free fan-out ledger
# ---------------------------------------------------------------------------


def _fake_git_runner(cmd: list[str], cwd: str, timeout: int) -> tuple[int, str]:
    """Deterministic git runner so receipts build without a real repo."""
    del cwd, timeout
    if "rev-parse" in cmd or "tree" in " ".join(cmd):
        return (0, "treesha123")
    return (0, "diff body")


class TestInlineSwarm:
    """plan_inline_swarm + record_inline_unit (the token-free path)."""

    def test_plan_writes_inline_manifest(self, tmp_path: Path) -> None:
        from oh_no_my_claudecode.swarm.inline import plan_inline_swarm

        plan = plan_inline_swarm(
            tmp_path,
            ["audit A", "audit B", "audit C"],
            concurrency=2,
            swarm_id="deadbeefdeadbeef",
            now=_FIXED_NOW,
        )
        assert plan["swarm_id"] == "deadbeefdeadbeef"
        assert plan["mode"] == "inline"
        assert len(plan["units"]) == 3
        assert plan["units"][0]["id"] == "unit-0000"

        mpath = tmp_path / ".onmc" / "swarm" / "deadbeefdeadbeef" / "manifest.json"
        assert mpath.exists()
        manifest = json.loads(mpath.read_text())
        assert manifest["mode"] == "inline"
        assert all(u["status"] == "pending" for u in manifest["units"].values())
        from oh_no_my_claudecode.runtime import RunSpec

        spec = RunSpec.from_dict(manifest["runtime_contract"])
        assert manifest["runtime_contract_digest"] == spec.digest
        assert spec.run_id == "swarm-deadbeefdeadbeef"
        assert [node.node_id for node in spec.topological_order()][-1] == "fan-in"
        assert plan["runtime_contract_digest"] == spec.digest

    def test_record_verified_unit_is_done(self, tmp_path: Path) -> None:
        from oh_no_my_claudecode.swarm.inline import plan_inline_swarm, record_inline_unit

        plan_inline_swarm(tmp_path, ["do A"], concurrency=1, swarm_id="aa11", now=_FIXED_NOW)
        res = record_inline_unit(
            tmp_path,
            "aa11",
            "unit-0000",
            goal="do A",
            summary="did A, all good",
            verified=True,
            files_touched=["src/a.py"],
            tokens=42,
            now=_FIXED_NOW,
            git_runner=_fake_git_runner,
        )
        assert res["status"] == "done"
        assert res["verified"] is True
        rp = Path(res["receipt_path"])
        assert rp.exists()
        receipt = json.loads(rp.read_text())
        assert receipt["verified"] is True
        assert receipt["agent"] == "claude-code-subagent"
        assert receipt["receipt_hash"]  # tamper-evident chain present

    def test_record_unverified_unit_is_failed(self, tmp_path: Path) -> None:
        from oh_no_my_claudecode.swarm.inline import plan_inline_swarm, record_inline_unit

        plan_inline_swarm(tmp_path, ["do B"], concurrency=1, swarm_id="bb22", now=_FIXED_NOW)
        res = record_inline_unit(
            tmp_path,
            "bb22",
            "unit-0000",
            goal="do B",
            summary="could not complete",
            verified=False,
            now=_FIXED_NOW,
            git_runner=_fake_git_runner,
        )
        assert res["status"] == "failed"
        receipt = json.loads(Path(res["receipt_path"]).read_text())
        assert receipt["verified"] is False

    def test_record_aborted_unit(self, tmp_path: Path) -> None:
        from oh_no_my_claudecode.swarm.inline import plan_inline_swarm, record_inline_unit

        plan_inline_swarm(tmp_path, ["do C"], concurrency=1, swarm_id="cc33", now=_FIXED_NOW)
        res = record_inline_unit(
            tmp_path,
            "cc33",
            "unit-0000",
            goal="do C",
            summary="cut short",
            verified=False,
            aborted=True,
            now=_FIXED_NOW,
            git_runner=_fake_git_runner,
        )
        assert res["status"] == "aborted"

    def test_inline_status_visible_via_swarm_state(self, tmp_path: Path) -> None:
        """The shared .onmc/swarm layout means swarm_state sees inline swarms."""
        from oh_no_my_claudecode.swarm.inline import plan_inline_swarm, record_inline_unit

        plan_inline_swarm(
            tmp_path, ["x", "y"], concurrency=2, swarm_id="dd44", now=_FIXED_NOW
        )
        record_inline_unit(
            tmp_path, "dd44", "unit-0000", goal="x", summary="done x",
            verified=True, now=_FIXED_NOW, git_runner=_fake_git_runner,
        )
        state = swarm_state(tmp_path, "dd44")
        assert state["mode"] == "inline"
        assert state["units"]["unit-0000"]["status"] == "done"
        assert state["units"]["unit-0000"]["verified"] is True
        assert state["units"]["unit-0001"]["status"] == "pending"

    def test_inline_abort_sentinel_path(self, tmp_path: Path) -> None:
        """request_abort writes the same sentinel the inline fan-out checks."""
        from oh_no_my_claudecode.swarm.inline import plan_inline_swarm

        plan = plan_inline_swarm(tmp_path, ["x"], concurrency=1, swarm_id="ee55")
        assert not Path(plan["abort_path"]).exists()
        request_abort(tmp_path, "ee55")
        assert Path(plan["abort_path"]).exists()
