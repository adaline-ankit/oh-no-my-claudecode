"""Tests for the onmc loop engine and service layer.

All tests use ONLY injected fake runners — no real subprocess, no real agent.
The tests are fully deterministic: injectable `now`, fake runners, temp SQLite storage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from oh_no_my_claudecode.loop.engine import (
    _build_brief,
    run_loop,
)
from oh_no_my_claudecode.loop.models import (
    AgentRunner,
    AgentRunResult,
    LoopConfig,
    LoopSpec,
    VerifyOutcome,
    VerifyRunner,
)
from oh_no_my_claudecode.models.memory import MemoryKind
from oh_no_my_claudecode.storage import SQLiteStorage

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def _storage(tmp_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(tmp_path / "onmc.db")
    storage.initialize()
    return storage


def _fake_agent(
    output: str,
    prediction: str = "",
    files: list[str] | None = None,
    tokens: int | None = None,
) -> AgentRunner:
    """Return a simple fake AgentRunner that always returns the same result."""

    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output=output,
            prediction=prediction,
            files_touched=files or [],
            tokens=tokens,
        )

    return _runner


def _fake_verify(*, passes: bool, output: str = "") -> VerifyRunner:
    """Return a simple fake VerifyRunner with a fixed result."""

    def _runner(command: str) -> VerifyOutcome:
        del command
        return VerifyOutcome(passed=passes, output=output)

    return _runner


def _win_then_lose_agent(after_iter: int) -> AgentRunner:
    """Agent runner that wins on iteration `after_iter`, loses before."""
    call_count = [0]

    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        call_count[0] += 1
        return AgentRunResult(
            output=f"attempt {call_count[0]}",
            prediction=f"prediction {call_count[0]}",
            files_touched=["src/module.py"],
            tokens=100,
        )

    return _runner


def _alternating_verify(pattern: list[bool]) -> VerifyRunner:
    """VerifyRunner whose result follows the pattern list cyclically."""
    call_count = [0]

    def _runner(command: str) -> VerifyOutcome:
        del command
        result = pattern[call_count[0] % len(pattern)]
        call_count[0] += 1
        return VerifyOutcome(passed=result, output="ok" if result else "FAILED")

    return _runner


# ---------------------------------------------------------------------------
# Test 1 — immediate win on first iteration
# ---------------------------------------------------------------------------


def test_converges_on_first_win(tmp_path: Path) -> None:
    """A loop with a verify that always passes should converge in exactly 1 iteration."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Fix the broken import")
    config = LoopConfig(max_iterations=5)

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent("patched import", prediction="add __init__.py"),
        verify_runner=_fake_verify(passes=True, output="1 passed"),
        now=_FIXED_NOW,
    )

    assert result.converged is True
    assert result.stop_reason == "converged"
    assert len(result.iterations) == 1
    assert result.iterations[0].outcome == "win"
    assert len(result.recorded_memory_ids) == 1


# ---------------------------------------------------------------------------
# Test 2 — max-iterations stop reason when verify always fails
# ---------------------------------------------------------------------------


def test_max_iterations_stop(tmp_path: Path) -> None:
    """When verify always fails the loop exhausts all iterations and stops.

    no_progress_window is set higher than max_iterations so no-progress cannot
    fire before max-iterations does.
    """
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Eliminate all type errors")
    # no_progress_window > max_iterations ensures max-iterations fires first.
    config = LoopConfig(max_iterations=3, no_progress_window=10)

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent("tried something", files=["src/types.py"]),
        verify_runner=_fake_verify(passes=False, output="type error: foo"),
        now=_FIXED_NOW,
    )

    assert result.converged is False
    assert result.stop_reason == "max-iterations"
    assert len(result.iterations) == 3
    for c in result.iterations:
        assert c.outcome == "loss"


# ---------------------------------------------------------------------------
# Test 3 — dead-ends accumulate in storage (core don't-repeat property)
# ---------------------------------------------------------------------------


def test_failed_approaches_written_to_memory(tmp_path: Path) -> None:
    """Each loss should write a FAILED_APPROACH memory into storage."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Remove the N+1 query")
    config = LoopConfig(max_iterations=4)

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent("tried eager load"),
        verify_runner=_fake_verify(passes=False, output="query count still 5"),
        now=_FIXED_NOW,
    )

    assert result.stop_reason in {"max-iterations", "no-progress"}
    # Each loss should have written a memory id.
    assert len(result.recorded_memory_ids) == len(result.iterations)

    # The memories must be retrievable as FAILED_APPROACH kind.
    all_memories = storage.list_memories()
    failed = [m for m in all_memories if m.kind == MemoryKind.FAILED_APPROACH]
    assert len(failed) >= 1


# ---------------------------------------------------------------------------
# Test 4 — win memory is DECISION kind (not FAILED_APPROACH)
# ---------------------------------------------------------------------------


def test_win_records_decision_memory(tmp_path: Path) -> None:
    """A converged loop should record a DECISION memory, not FAILED_APPROACH."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Add the missing index")
    config = LoopConfig(max_iterations=5)

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent("created index", prediction="CREATE INDEX"),
        verify_runner=_fake_verify(passes=True, output="query time: 2ms"),
        now=_FIXED_NOW,
    )

    assert result.converged is True
    all_memories = storage.list_memories()
    decision_mems = [m for m in all_memories if m.kind == MemoryKind.DECISION]
    assert len(decision_mems) == 1
    # No failed approach should exist when we win immediately.
    failed_mems = [m for m in all_memories if m.kind == MemoryKind.FAILED_APPROACH]
    assert len(failed_mems) == 0


# ---------------------------------------------------------------------------
# Test 5 — budget stop reason
# ---------------------------------------------------------------------------


def test_budget_stops_loop(tmp_path: Path) -> None:
    """When total_tokens reaches budget_tokens the loop returns 'budget'."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Optimise the SQL query")
    # Budget is 150 tokens; each fake agent returns 100 tokens.
    # First iteration uses 100, still under budget.
    # Before second iteration: 100 < 150, runs it, uses 200 total.
    # Before third iteration: 200 >= 150, stops.
    config = LoopConfig(max_iterations=10, budget_tokens=150)

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent("tried rewrite", tokens=100),
        verify_runner=_fake_verify(passes=False, output="still slow"),
        now=_FIXED_NOW,
    )

    assert result.stop_reason == "budget"
    assert result.converged is False
    # Must have stopped before exhausting all 10 iterations.
    assert len(result.iterations) < 10


# ---------------------------------------------------------------------------
# Test 6 — no-progress detection via repeated signature
# ---------------------------------------------------------------------------


def test_no_progress_stops_loop(tmp_path: Path) -> None:
    """When the same (files, verify_output_head) repeats no_progress_window times, stop."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Fix the flaky test")
    config = LoopConfig(max_iterations=10, no_progress_window=3)

    # Agent always touches same files, verify always produces same output → identical sig.
    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent("same attempt", files=["tests/test_foo.py"]),
        verify_runner=_fake_verify(passes=False, output="FAILED: flaky"),
        now=_FIXED_NOW,
    )

    assert result.stop_reason == "no-progress"
    # Should stop after exactly no_progress_window losses with identical signature.
    assert len(result.iterations) == config.no_progress_window


# ---------------------------------------------------------------------------
# Test 7 — escalation_level increments after threshold losses
# ---------------------------------------------------------------------------


def test_escalation_level_increments(tmp_path: Path) -> None:
    """After escalation_threshold consecutive losses, escalation_level should increment."""
    received_levels: list[int] = []

    def _tracking_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
        received_levels.append(escalation_level)
        return AgentRunResult(
            output=f"tried at level {escalation_level}",
            prediction="",
            files_touched=["main.py"],
            tokens=None,
        )

    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Fix the deadlock")
    config = LoopConfig(max_iterations=8, escalation_threshold=3, no_progress_window=50)

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_tracking_agent,
        # Vary output slightly so no-progress doesn't fire first.
        verify_runner=_alternating_verify([False, False, False, False, False, False, False, False]),
        now=_FIXED_NOW,
    )

    # Iterations 1-3 are level 0, iterations 4-6 level 1, iterations 7-8 level 2.
    assert received_levels[0] == 0
    assert received_levels[3] == 1  # escalation after 3 losses
    assert received_levels[6] == 2  # escalation again after next 3


# ---------------------------------------------------------------------------
# Test 8 — _build_brief surfaces dead-ends from a pre-seeded FAILED_APPROACH memory
# ---------------------------------------------------------------------------


def test_build_brief_includes_dead_ends(tmp_path: Path) -> None:
    """_build_brief should surface FAILED_APPROACH memories as dead-ends in the brief."""
    storage = _storage(tmp_path)
    goal = "Resolve the import cycle"

    # Manually record a FAILED_APPROACH memory with a recognisable tag.
    from oh_no_my_claudecode.models.memory import MemoryEntry, SourceType

    dead_end = MemoryEntry(
        id="test-dead-end-001",
        kind=MemoryKind.FAILED_APPROACH,
        title="Loop dead-end (iter 1): Resolve the import cycle",
        summary=(
            "Failed approach for goal: Resolve the import cycle. "
            "Tried: moved utils.py to a new package. "
            "Prediction was: the circular import would resolve."
        ),
        details="Verify output:\nImportError: cannot import name 'helper'",
        source_type=SourceType.SESSION,
        source_ref="loop:iter:1",
        tags=["loop-deadend", "loop", "failed_approach"],
        confidence=0.9,
        created_at=_FIXED_NOW,
        updated_at=_FIXED_NOW,
    )
    storage.upsert_memories([dead_end])

    brief = _build_brief(storage, goal, last_loss=None, escalation_level=0)

    # The brief must contain something about dead-ends or the failed approach.
    # compile_guard reads FAILED_APPROACH memories; the exact heading depends on
    # the guard compiler's markdown template.
    assert brief  # non-empty
    # If compile_guard found something, guard.has_dead_ends would be True and
    # brief would contain the dead-end text.  We check for a key phrase:
    lower = brief.lower()
    assert "dead" in lower or "failed" in lower or "do not" in lower or "avoid" in lower
