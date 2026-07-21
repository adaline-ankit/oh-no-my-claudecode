"""Tests for memory hygiene in the loop engine.

Verifies that transient/environment failures (permission denied, file-write blocked,
rate limits, timeouts, etc.) are NOT stored as FAILED_APPROACH dead-ends, while
genuine approach/logic failures ARE stored so the guard can surface them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from oh_no_my_claudecode.guard.compiler import compile_guard
from oh_no_my_claudecode.loop.engine import (
    _classify_failure_cause,
    run_loop,
)
from oh_no_my_claudecode.loop.models import (
    AgentRunResult,
    LoopConfig,
    LoopSpec,
    VerifyOutcome,
)
from oh_no_my_claudecode.models.memory import MemoryKind
from oh_no_my_claudecode.storage import SQLiteStorage

_FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def _storage(tmp_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(tmp_path / "onmc.db")
    storage.initialize()
    return storage


def _fake_agent(
    output: str,
    files: list[str] | None = None,
    error: str | None = None,
):
    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output=output,
            prediction="",
            files_touched=files or [],
            tokens=None,
            error=error,
        )

    return _runner


def _fake_verify(*, passes: bool, output: str = ""):
    def _runner(command: str) -> VerifyOutcome:
        del command
        return VerifyOutcome(passed=passes, output=output)

    return _runner


# ---------------------------------------------------------------------------
# Unit tests for _classify_failure_cause
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verify_output",
    [
        "Error: permission denied when writing to src/foo.py",
        "file-writes blocked pending permission approval",
        "file-write blocked",
        "not granted to perform action",
        "pending permission for file system access",
        "connection timed out after 30 seconds",
        "read timed out talking to the registry",
        "network error: connection refused",
        "connection reset by peer",
        "rate limit exceeded — try again",
        "HTTP 429 Too Many Requests",
        "out of memory: killed",
        "[agent-error] Failed to authenticate. API Error: 401",
        "[scope-unverifiable] change probe unavailable",
    ],
)
def test_classifier_returns_environment_for_transient_signals(verify_output: str) -> None:
    assert _classify_failure_cause(verify_output) == "environment"


@pytest.mark.parametrize(
    "verify_output",
    [
        "AssertionError: expected 42 got 0",
        "FAILED test_foo.py::test_bar — AttributeError",
        "query count still 5",
        "Build failed: undefined variable",
        "TypeError: unsupported operand type",
        "1 failed, 3 passed",
        "AssertionError: expected 429, got 430",
        # A verify-command timeout is the agent's own regression (an introduced
        # hang / infinite loop), not a transient environment failure.
        "[verify timed out]",
        "test suite timed out after 120 seconds",
    ],
)
def test_classifier_returns_approach_for_real_failures(verify_output: str) -> None:
    assert _classify_failure_cause(verify_output) == "approach"


def test_classifier_ignores_agent_controlled_narration() -> None:
    """Agent output is untrusted: environment phrases in the agent's own narration
    must NOT downgrade a genuine approach failure to an unrecorded 'environment' loss.

    The classifier keys only on the harness-controlled verify output, so a real test
    failure stays 'approach' even when the agent claims a permission/rate-limit problem.
    """
    assert _classify_failure_cause("AssertionError: expected 1 query, got 12") == "approach"


# ---------------------------------------------------------------------------
# Integration tests: environment failures must NOT produce FAILED_APPROACH memories
# ---------------------------------------------------------------------------


def test_permission_failure_not_stored_as_dead_end(tmp_path: Path) -> None:
    """A loop iteration that fails due to 'permission denied' must NOT produce
    a FAILED_APPROACH memory in storage, so guard is not polluted."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Add logging to auth module")
    config = LoopConfig(max_iterations=2)

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(
            "Attempting to write auth.py — file-writes blocked pending permission approval",
            files=[],
        ),
        verify_runner=_fake_verify(
            passes=False,
            output="permission denied: cannot open auth.py for writing",
        ),
        now=_FIXED_NOW,
    )

    all_memories = storage.list_memories()
    failed_approach_mems = [m for m in all_memories if m.kind == MemoryKind.FAILED_APPROACH]
    assert failed_approach_mems == [], (
        "Environment/permission failure must NOT be stored as a FAILED_APPROACH dead-end"
    )


def test_permission_failure_not_surfaced_in_guard(tmp_path: Path) -> None:
    """Guard must report no dead-ends after an environment-only failure run."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Refactor the payment service")
    config = LoopConfig(max_iterations=1)

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(
            "file-writes blocked pending permission",
            files=[],
        ),
        verify_runner=_fake_verify(
            passes=False,
            output="Error: not granted to write payment_service.py",
        ),
        now=_FIXED_NOW,
    )

    guard = compile_guard(storage, "Refactor the payment service")
    assert not guard.has_dead_ends, (
        "Guard must not surface environment/permission failures as dead-ends"
    )


def test_rate_limit_failure_not_stored_as_dead_end(tmp_path: Path) -> None:
    """HTTP 429 / rate-limit failures must not be stored as dead-ends."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Generate embeddings for all docs")
    config = LoopConfig(max_iterations=1)

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent("Called LLM API", files=[]),
        verify_runner=_fake_verify(
            passes=False,
            output="HTTP 429 Too Many Requests — rate limit exceeded",
        ),
        now=_FIXED_NOW,
    )

    all_memories = storage.list_memories()
    failed = [m for m in all_memories if m.kind == MemoryKind.FAILED_APPROACH]
    assert failed == [], "Rate-limit failure must not be stored as a dead-end"


def test_network_timeout_failure_not_stored_as_dead_end(tmp_path: Path) -> None:
    """Genuine transient network/API timeouts must not be stored as dead-ends."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Fetch and index remote docs")
    config = LoopConfig(max_iterations=1)

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent("Calling the API", files=[]),
        verify_runner=_fake_verify(passes=False, output="connection timed out"),
        now=_FIXED_NOW,
    )

    all_memories = storage.list_memories()
    failed = [m for m in all_memories if m.kind == MemoryKind.FAILED_APPROACH]
    assert failed == [], "Transient network timeout must not be stored as a dead-end"


def test_verify_timeout_stored_as_dead_end(tmp_path: Path) -> None:
    """A verify-command timeout is the agent's own regression (an introduced hang),
    not a transient environment failure, so it MUST be recorded as a dead-end — else
    the loop can repeat the hang-inducing approach every iteration."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Speed up the report generator")
    config = LoopConfig(max_iterations=1)

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent("Rewrote the loop", files=["report.py"]),
        verify_runner=_fake_verify(passes=False, output="[verify timed out]"),
        now=_FIXED_NOW,
    )

    all_memories = storage.list_memories()
    failed = [m for m in all_memories if m.kind == MemoryKind.FAILED_APPROACH]
    assert len(failed) >= 1, "A verify-command timeout must be recorded as a dead-end"


def test_agent_error_not_stored_as_dead_end(tmp_path: Path) -> None:
    """Hard agent invocation errors (auth/API failures) must not be stored as dead-ends."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Do the thing")
    config = LoopConfig(max_iterations=5)

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(
            "Failed to authenticate. API Error: 401",
            error="Failed to authenticate. API Error: 401",
        ),
        verify_runner=_fake_verify(passes=True, output="all good"),
        now=_FIXED_NOW,
    )

    all_memories = storage.list_memories()
    failed = [m for m in all_memories if m.kind == MemoryKind.FAILED_APPROACH]
    assert failed == [], "Agent auth/API error must not be stored as a dead-end"


# ---------------------------------------------------------------------------
# Integration tests: real approach failures MUST produce FAILED_APPROACH memories
# ---------------------------------------------------------------------------


def test_approach_failure_stored_as_dead_end(tmp_path: Path) -> None:
    """A genuine approach failure (test assertion error) MUST be stored as
    a FAILED_APPROACH memory so guard can block it next iteration."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Fix the N+1 query in user listing")
    config = LoopConfig(max_iterations=2)

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(
            "Applied eager loading via select_related",
            files=["views.py"],
        ),
        verify_runner=_fake_verify(
            passes=False,
            output="AssertionError: expected 1 query, got 12",
        ),
        now=_FIXED_NOW,
    )

    all_memories = storage.list_memories()
    failed = [m for m in all_memories if m.kind == MemoryKind.FAILED_APPROACH]
    assert len(failed) >= 1, (
        "A genuine approach failure must be stored as a FAILED_APPROACH dead-end"
    )


def test_approach_failure_surfaced_in_guard(tmp_path: Path) -> None:
    """Guard must report the dead-end after a genuine approach failure."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Fix the N+1 query in user listing")
    config = LoopConfig(max_iterations=1)

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(
            "Applied eager loading via select_related",
            files=["views.py"],
        ),
        verify_runner=_fake_verify(
            passes=False,
            output="AssertionError: expected 1 query, got 12",
        ),
        now=_FIXED_NOW,
    )

    guard = compile_guard(storage, "Fix the N+1 query")
    assert guard.has_dead_ends, "Guard must surface genuine approach failures as dead-ends"


def test_mixed_failures_only_approach_stored(tmp_path: Path) -> None:
    """When a loop has both an environment failure and a real approach failure,
    only the approach failure should be stored as a dead-end."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="Optimize database index on orders table")
    config = LoopConfig(max_iterations=4)

    call_count = [0]

    def _mixed_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        call_count[0] += 1
        return AgentRunResult(
            output=(
                "adding index" if call_count[0] > 1 else "file-writes blocked pending permission"
            ),
            prediction="",
            files_touched=["migrations/001.sql"] if call_count[0] > 1 else [],
            tokens=None,
        )

    def _mixed_verify(command: str) -> VerifyOutcome:
        del command
        if call_count[0] == 1:
            return VerifyOutcome(passed=False, output="permission denied: cannot write migration")
        return VerifyOutcome(passed=False, output="FAILED: index already exists — wrong column")

    run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_mixed_agent,
        verify_runner=_mixed_verify,
        now=_FIXED_NOW,
    )

    all_memories = storage.list_memories()
    failed = [m for m in all_memories if m.kind == MemoryKind.FAILED_APPROACH]

    # Only the real approach failure (iter >= 2) should be stored.
    # The permission failure (iter 1) must NOT be present.
    assert len(failed) >= 1, "Real approach failures must still be stored"

    # None of the stored dead-ends should mention permission errors.
    for mem in failed:
        combined = (mem.summary + " " + mem.details).lower()
        assert "permission denied" not in combined, (
            "Environment failure content must not appear in stored dead-ends"
        )
        assert "file-writes blocked" not in combined, (
            "Environment failure content must not appear in stored dead-ends"
        )
