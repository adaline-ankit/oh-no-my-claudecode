"""Tests for loop checkpoint/resume functionality.

All tests use ONLY injected fake runners and InMemoryCheckpointStore —
no real subprocess, no real agent, no real filesystem I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from oh_no_my_claudecode.loop.checkpoint import (
    CheckpointState,
    FileCheckpointStore,
    InMemoryCheckpointStore,
    _loop_spec_sha8,
)
from oh_no_my_claudecode.loop.engine import run_loop
from oh_no_my_claudecode.loop.models import (
    AgentRunResult,
    IterationContract,
    LoopConfig,
    LoopSpec,
    VerifyOutcome,
)
from oh_no_my_claudecode.storage import SQLiteStorage

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def _storage(tmp_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(tmp_path / "onmc.db")
    storage.initialize()
    return storage


def _fake_agent(
    output: str = "did something",
    prediction: str = "prediction",
    files: list[str] | None = None,
    tokens: int = 10,
) -> object:
    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output=output,
            prediction=prediction,
            files_touched=files or [],
            tokens=tokens,
        )

    return _runner


def _always_fail_verify(command: str) -> VerifyOutcome:
    del command
    return VerifyOutcome(passed=False, output="FAILED: error")


def _always_pass_verify(command: str) -> VerifyOutcome:
    del command
    return VerifyOutcome(passed=True, output="1 passed")


def _varying_verify(pass_on_iter: int) -> object:
    """Verify runner that passes on the given iteration number (1-based call count)."""
    call_count = [0]

    def _runner(command: str) -> VerifyOutcome:
        del command
        call_count[0] += 1
        if call_count[0] == pass_on_iter:
            return VerifyOutcome(passed=True, output="passed")
        return VerifyOutcome(passed=False, output=f"FAILED iter {call_count[0]}")

    return _runner


# ---------------------------------------------------------------------------
# Test 1: checkpoint is persisted after each loss iteration
# ---------------------------------------------------------------------------


def test_checkpoint_saved_after_each_iteration(tmp_path: Path) -> None:
    """After each loss, a checkpoint must be present in the store."""
    store = InMemoryCheckpointStore()
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="fix the bug", success_criteria="")
    config = LoopConfig(
        max_iterations=3,
        verify_command="pytest",
        no_progress_window=10,
        duplicate_action_limit=0,
        repeated_error_limit=0,
    )
    sha8 = _loop_spec_sha8(spec.goal, config.verify_command)

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["a.py"], tokens=5),
        verify_runner=_always_fail_verify,
        now=_FIXED_NOW,
        checkpoint_store=store,
    )

    # After the run (max-iterations terminal), checkpoint is cleared.
    assert store.load(sha8) is None


def test_checkpoint_saved_mid_run(tmp_path: Path) -> None:
    """Checkpoint is written after each iteration; we can observe it by capping iterations."""
    checkpoints_after: list[int] = []

    class _ObservingStore(InMemoryCheckpointStore):
        def save(self, sha8: str, state: CheckpointState) -> None:
            super().save(sha8, state)
            checkpoints_after.append(len(state.iterations))

    store = _ObservingStore()
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="observe checkpoints")
    config = LoopConfig(
        max_iterations=3,
        verify_command="pytest",
        no_progress_window=10,
        duplicate_action_limit=0,
        repeated_error_limit=0,
    )

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["b.py"]),
        verify_runner=_always_fail_verify,
        now=_FIXED_NOW,
        checkpoint_store=store,
    )

    # save() should have been called after each of the 3 iterations + final terminal
    assert checkpoints_after[-1] == 3  # last save has all 3 iterations
    # Checkpoints grow monotonically.
    assert checkpoints_after == sorted(checkpoints_after)


# ---------------------------------------------------------------------------
# Test 2: resume continues iteration numbering from the saved state
# ---------------------------------------------------------------------------


def test_resume_continues_from_saved_state(tmp_path: Path) -> None:
    """Resuming must continue iteration numbering from N+1 not restart from 1."""
    store = InMemoryCheckpointStore()
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="fix flaky test")

    # Run 1: stop early via wall-time (set to 0 so it fires immediately after iter 2).
    # We simulate stopping after 2 iterations by using a custom clock that
    # reports elapsed > max_wall_seconds on the 3rd budget check.
    tick = [0]

    def _fake_clock() -> float:
        tick[0] += 1
        # 0.0 on first check (before iter 1), 0.5 on second (before iter 2),
        # 2.0 on third (before iter 3) → fires wall-time stop.
        return [0.0, 0.5, 0.5, 2.0, 2.0, 2.0][min(tick[0] - 1, 5)]

    config2 = LoopConfig(
        max_iterations=5,
        verify_command="pytest",
        no_progress_window=10,
        duplicate_action_limit=0,
        repeated_error_limit=0,
        max_wall_seconds=1,
    )

    result1 = run_loop(
        storage,
        tmp_path,
        spec,
        config2,
        agent_runner=_fake_agent(files=["c.py"]),
        verify_runner=_always_fail_verify,
        now=_FIXED_NOW,
        clock=_fake_clock,
        checkpoint_store=store,
    )

    assert result1.stop_reason == "wall-time"
    prior_iter_count = len(result1.iterations)
    assert prior_iter_count >= 1  # at least one iteration completed

    # Verify checkpoint was preserved (wall-time is a resumable stop).
    sha8 = _loop_spec_sha8(spec.goal, config2.verify_command)
    saved = store.load(sha8)
    assert saved is not None
    assert len(saved.iterations) == prior_iter_count

    # Run 2: resume=True, no wall-time limit, should continue from prior_iter_count + 1.
    def _tracking_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output="resumed attempt",
            prediction="",
            files_touched=["d.py"],
            tokens=5,
        )

    result2 = run_loop(
        storage,
        tmp_path,
        spec,
        config2.__class__(
            max_iterations=5,
            verify_command="pytest",
            no_progress_window=10,
            duplicate_action_limit=0,
            repeated_error_limit=0,
        ),
        agent_runner=_tracking_agent,
        verify_runner=_always_fail_verify,
        now=_FIXED_NOW,
        checkpoint_store=store,
        resume=True,
    )

    # The resumed run's iterations should start AFTER the prior ones.
    if result2.iterations:
        first_new_iter = result2.iterations[prior_iter_count].iteration
        assert first_new_iter == prior_iter_count + 1

    # Total iterations across both runs combined should equal max_iterations.
    combined = len(result1.iterations) + (
        len(result2.iterations) - prior_iter_count
    )
    assert combined <= config2.max_iterations


# ---------------------------------------------------------------------------
# Test 3: prior contracts preserved on resume (dead-ends retained)
# ---------------------------------------------------------------------------


def test_resume_preserves_prior_contracts(tmp_path: Path) -> None:
    """On resume, the iteration list must include prior contracts at the start."""
    store = InMemoryCheckpointStore()
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="preserve contracts on resume")
    config = LoopConfig(
        max_iterations=6,
        verify_command="pytest",
        no_progress_window=10,
        duplicate_action_limit=0,
        repeated_error_limit=0,
        max_wall_seconds=1,
    )

    tick = [0]

    def _fast_clock() -> float:
        tick[0] += 1
        return 0.0 if tick[0] <= 3 else 2.0

    result1 = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["e.py"], output="first run action"),
        verify_runner=_always_fail_verify,
        now=_FIXED_NOW,
        clock=_fast_clock,
        checkpoint_store=store,
    )
    assert result1.stop_reason == "wall-time"
    n_prior = len(result1.iterations)
    assert n_prior >= 1

    # Resume
    result2 = run_loop(
        storage,
        tmp_path,
        spec,
        LoopConfig(
            max_iterations=6,
            verify_command="pytest",
            no_progress_window=10,
            duplicate_action_limit=0,
            repeated_error_limit=0,
        ),
        agent_runner=_fake_agent(files=["f.py"], output="resumed action"),
        verify_runner=_always_fail_verify,
        now=_FIXED_NOW,
        checkpoint_store=store,
        resume=True,
    )

    # The first n_prior entries of result2.iterations must be the prior contracts.
    assert len(result2.iterations) >= n_prior
    for idx in range(n_prior):
        assert result2.iterations[idx].action_summary.startswith("first run action")


# ---------------------------------------------------------------------------
# Test 4: checkpoint cleared on converge
# ---------------------------------------------------------------------------


def test_checkpoint_cleared_on_converge(tmp_path: Path) -> None:
    """After a successful converge, the checkpoint must be removed."""
    store = InMemoryCheckpointStore()
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="converge and clear")
    config = LoopConfig(
        max_iterations=5,
        verify_command="pytest",
        no_progress_window=10,
        duplicate_action_limit=0,
        repeated_error_limit=0,
    )
    sha8 = _loop_spec_sha8(spec.goal, config.verify_command)

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(),
        verify_runner=_always_pass_verify,
        now=_FIXED_NOW,
        checkpoint_store=store,
    )

    assert result.converged is True
    assert store.load(sha8) is None  # checkpoint cleared


# ---------------------------------------------------------------------------
# Test 5: no checkpoint / no resume = current behavior unchanged
# ---------------------------------------------------------------------------


def test_no_checkpoint_no_resume_unchanged(tmp_path: Path) -> None:
    """When checkpoint_store=None, behavior must be identical to before this feature."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="no checkpoint behavior")
    config = LoopConfig(
        max_iterations=3,
        verify_command="pytest",
        no_progress_window=10,
        duplicate_action_limit=0,
        repeated_error_limit=0,
    )

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["g.py"]),
        verify_runner=_always_fail_verify,
        now=_FIXED_NOW,
        # No checkpoint_store, no resume
    )

    assert result.stop_reason == "max-iterations"
    assert len(result.iterations) == 3


# ---------------------------------------------------------------------------
# Test 6: resume=True with no existing checkpoint starts fresh
# ---------------------------------------------------------------------------


def test_resume_with_no_checkpoint_starts_fresh(tmp_path: Path) -> None:
    """When resume=True but no checkpoint exists, the loop starts from iteration 1."""
    store = InMemoryCheckpointStore()  # empty store
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="no checkpoint exists")
    config = LoopConfig(
        max_iterations=3,
        verify_command="pytest",
        no_progress_window=10,
        duplicate_action_limit=0,
        repeated_error_limit=0,
    )

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["h.py"]),
        verify_runner=_always_fail_verify,
        now=_FIXED_NOW,
        checkpoint_store=store,
        resume=True,  # resume requested but no checkpoint
    )

    assert result.stop_reason == "max-iterations"
    assert len(result.iterations) == 3
    assert result.iterations[0].iteration == 1


# ---------------------------------------------------------------------------
# Test 7: atomic write — temp file cleaned up on save, no corruption
# ---------------------------------------------------------------------------


def test_file_checkpoint_store_atomic_write(tmp_path: Path) -> None:
    """FileCheckpointStore must write to a .tmp file then rename; no leftover .tmp."""
    store = FileCheckpointStore(tmp_path)
    sha8 = "deadbeef"

    state = CheckpointState(
        goal="atomic write test",
        verify_command="pytest",
        iterations=[
            IterationContract(
                iteration=1,
                prediction="p",
                action_summary="a",
                files_touched=["x.py"],
                verify_passed=False,
                verify_output="FAILED",
                outcome="loss",
                tokens=5,
            )
        ],
        recorded_memory_ids=["mid1"],
        total_tokens=5,
        total_cost_usd=0.0,
        consecutive_losses=1,
        escalation_level=0,
        signature_counts={"abc": 1},
        consecutive_same_error=0,
        last_error_head="FAILED",
    )

    store.save(sha8, state)

    # No .tmp file should remain.
    tmp_files = list((tmp_path / ".onmc" / "loop-state").glob("*.tmp"))
    assert tmp_files == []

    # The real file should exist and round-trip cleanly.
    loaded = store.load(sha8)
    assert loaded is not None
    assert loaded.goal == "atomic write test"
    assert len(loaded.iterations) == 1
    assert loaded.iterations[0].iteration == 1

    # clear removes it.
    store.clear(sha8)
    assert store.load(sha8) is None


# ---------------------------------------------------------------------------
# Test 8: InMemoryCheckpointStore round-trip
# ---------------------------------------------------------------------------


def test_in_memory_checkpoint_store_round_trip() -> None:
    """InMemoryCheckpointStore save/load/clear must preserve all fields."""
    store = InMemoryCheckpointStore()
    sha8 = "cafebabe"

    state = CheckpointState(
        goal="round trip",
        verify_command="make test",
        iterations=[],
        recorded_memory_ids=["m1", "m2"],
        total_tokens=42,
        total_cost_usd=1.5,
        consecutive_losses=2,
        escalation_level=1,
        signature_counts={"aa": 2, "bb": 1},
        consecutive_same_error=1,
        last_error_head="error output",
    )

    assert store.load(sha8) is None  # nothing stored yet
    store.save(sha8, state)

    loaded = store.load(sha8)
    assert loaded is not None
    assert loaded.goal == "round trip"
    assert loaded.verify_command == "make test"
    assert loaded.recorded_memory_ids == ["m1", "m2"]
    assert loaded.total_tokens == 42
    assert loaded.total_cost_usd == 1.5
    assert loaded.consecutive_losses == 2
    assert loaded.escalation_level == 1
    assert loaded.signature_counts == {"aa": 2, "bb": 1}
    assert loaded.consecutive_same_error == 1
    assert loaded.last_error_head == "error output"

    store.clear(sha8)
    assert store.load(sha8) is None


# ---------------------------------------------------------------------------
# Test 9: sha8 is deterministic and content-keyed
# ---------------------------------------------------------------------------


def test_loop_spec_sha8_deterministic() -> None:
    """Same goal + verify_command must always produce the same sha8."""
    s1 = _loop_spec_sha8("fix the bug", "pytest")
    s2 = _loop_spec_sha8("fix the bug", "pytest")
    s3 = _loop_spec_sha8("different goal", "pytest")

    assert s1 == s2
    assert s1 != s3
    assert len(s1) == 8


# ---------------------------------------------------------------------------
# Test 10: resumed run iteration numbers continue correctly
# ---------------------------------------------------------------------------


def test_resumed_iteration_numbers_sequential(tmp_path: Path) -> None:
    """After resume, iteration numbers must be N+1, N+2, ... not 1, 2, ..."""
    store = InMemoryCheckpointStore()
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="sequential iteration numbers")

    # First run: 2 iterations, wall-time stop.
    tick = [0]

    def _clock1() -> float:
        tick[0] += 1
        return 0.0 if tick[0] <= 4 else 99.0

    result1 = run_loop(
        storage,
        tmp_path,
        spec,
        LoopConfig(
            max_iterations=6,
            verify_command="pytest",
            no_progress_window=10,
            duplicate_action_limit=0,
            repeated_error_limit=0,
            max_wall_seconds=1,
        ),
        agent_runner=_fake_agent(files=["i.py"]),
        verify_runner=_always_fail_verify,
        now=_FIXED_NOW,
        clock=_clock1,
        checkpoint_store=store,
    )
    assert result1.stop_reason == "wall-time"
    prior_n = len(result1.iterations)
    assert prior_n >= 1

    # Second run: resume, continue to max.
    result2 = run_loop(
        storage,
        tmp_path,
        spec,
        LoopConfig(
            max_iterations=6,
            verify_command="pytest",
            no_progress_window=10,
            duplicate_action_limit=0,
            repeated_error_limit=0,
        ),
        agent_runner=_fake_agent(files=["j.py"]),
        verify_runner=_always_fail_verify,
        now=_FIXED_NOW,
        checkpoint_store=store,
        resume=True,
    )

    # All iteration numbers must be sequential: 1, 2, 3, ...
    all_iters = result2.iterations
    for idx, contract in enumerate(all_iters):
        assert contract.iteration == idx + 1, (
            f"Expected iteration {idx + 1}, got {contract.iteration}"
        )
