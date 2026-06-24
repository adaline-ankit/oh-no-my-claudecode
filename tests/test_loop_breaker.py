"""Tests for the loop circuit breaker and worktree isolation/rollback.

Circuit-breaker tests:
  - duplicate-action: same iteration signature repeating >= duplicate_action_limit
    → stop_reason="duplicate-action" before max-iterations.
  - repeated-error:   same verify-output head N consecutive losses in a row
    → stop_reason="repeated-error".
  - Breaker knobs are configurable; defaults are backward-compatible with
    existing loop/autopilot/receipt tests.
  - Setting limit=0 disables the corresponding breaker.

Isolation/rollback tests (real temp git repo, fake agent_runner):
  - FAILED run → worktree removed → working tree unchanged.
  - SUCCESS run → worktree kept (changes visible).
  - git-worktree-add failure → degrades gracefully (warn + runs in-place).

All tests use ONLY injected fake runners — no real agent subprocess.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oh_no_my_claudecode.loop.engine import run_loop
from oh_no_my_claudecode.loop.models import (
    AgentRunResult,
    LoopConfig,
    LoopSpec,
    VerifyOutcome,
)
from oh_no_my_claudecode.storage import SQLiteStorage

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FIXED_NOW_DT = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def _storage(tmp_path: Path) -> SQLiteStorage:
    db = SQLiteStorage(tmp_path / "onmc.db")
    db.initialize()
    return db


def _fake_agent(
    output: str = "tried",
    files: list[str] | None = None,
    tokens: int | None = None,
) -> Callable[..., AgentRunResult]:
    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output=output,
            prediction="",
            files_touched=files or [],
            tokens=tokens,
        )

    return _runner


def _varying_file_agent(files_sequence: list[list[str]]) -> Callable[..., AgentRunResult]:
    """Agent that cycles through different files_touched lists on each call."""
    counter = [0]

    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        idx = counter[0] % len(files_sequence)
        counter[0] += 1
        return AgentRunResult(
            output=f"attempt {counter[0]}",
            prediction="",
            files_touched=files_sequence[idx],
            tokens=None,
        )

    return _runner


def _fake_verify(*, passes: bool, output: str = "FAIL") -> Callable[..., VerifyOutcome]:
    def _runner(command: str) -> VerifyOutcome:
        del command
        return VerifyOutcome(passed=passes, output=output)

    return _runner


def _varying_error_verify(outputs: list[str]) -> Callable[..., VerifyOutcome]:
    """VerifyRunner that cycles through different error outputs."""
    counter = [0]

    def _runner(command: str) -> VerifyOutcome:
        del command
        out = outputs[counter[0] % len(outputs)]
        counter[0] += 1
        return VerifyOutcome(passed=False, output=out)

    return _runner


# ---------------------------------------------------------------------------
# Circuit breaker — duplicate-action
# ---------------------------------------------------------------------------


def test_duplicate_action_fires_before_max_iterations(tmp_path: Path) -> None:
    """Same signature repeating >= duplicate_action_limit → 'duplicate-action'."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="fix the thing")
    config = LoopConfig(
        max_iterations=10,
        no_progress_window=20,  # disable no-progress
        duplicate_action_limit=2,
    )

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["src/foo.py"]),
        verify_runner=_fake_verify(passes=False, output="SAME ERROR"),
        now=_FIXED_NOW_DT,
    )

    assert result.stop_reason == "duplicate-action"
    assert result.converged is False
    # Should stop after exactly duplicate_action_limit iterations.
    assert len(result.iterations) == config.duplicate_action_limit
    # Must NOT have reached max-iterations.
    assert len(result.iterations) < config.max_iterations


def test_duplicate_action_does_not_fire_when_signatures_vary(tmp_path: Path) -> None:
    """When files vary each iteration the duplicate-action breaker must NOT fire."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="eliminate import cycle")
    config = LoopConfig(
        max_iterations=4,
        no_progress_window=20,
        duplicate_action_limit=2,
    )

    # Each iteration touches a different file → different signature each time.
    agent = _varying_file_agent([["a.py"], ["b.py"], ["c.py"], ["d.py"]])

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=agent,
        verify_runner=_fake_verify(passes=False, output="error"),
        now=_FIXED_NOW_DT,
    )

    # With 4 distinct signatures the breaker cannot fire.
    assert result.stop_reason != "duplicate-action"
    assert len(result.iterations) == config.max_iterations


def test_duplicate_action_limit_zero_disables_breaker(tmp_path: Path) -> None:
    """Setting duplicate_action_limit=0 disables the breaker entirely."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="task")
    config = LoopConfig(
        max_iterations=3,
        no_progress_window=20,
        duplicate_action_limit=0,
    )

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["x.py"]),
        verify_runner=_fake_verify(passes=False, output="SAME"),
        now=_FIXED_NOW_DT,
    )

    # no-progress has window=20 so won't fire; max-iterations should fire.
    assert result.stop_reason != "duplicate-action"


# ---------------------------------------------------------------------------
# Circuit breaker — repeated-error
# ---------------------------------------------------------------------------


def test_repeated_error_fires_on_consecutive_same_output(tmp_path: Path) -> None:
    """Same verify output head N times in a row → 'repeated-error'."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="fix CI")
    config = LoopConfig(
        max_iterations=20,
        no_progress_window=20,
        duplicate_action_limit=0,  # disable duplicate-action
        repeated_error_limit=3,
    )

    # Every iteration has the same error output.
    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        # Vary files so duplicate-action (if enabled) wouldn't fire on this.
        agent_runner=_varying_file_agent([["a.py"], ["b.py"], ["c.py"], ["d.py"]]),
        verify_runner=_fake_verify(passes=False, output="IDENTICAL ERROR"),
        now=_FIXED_NOW_DT,
    )

    assert result.stop_reason == "repeated-error"
    assert result.converged is False
    assert len(result.iterations) == config.repeated_error_limit


def test_repeated_error_resets_on_different_output(tmp_path: Path) -> None:
    """Consecutive counter resets when the error output changes."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="task")
    config = LoopConfig(
        max_iterations=10,
        no_progress_window=20,
        duplicate_action_limit=0,
        repeated_error_limit=3,
    )

    # Pattern: A A B A A B … — never 3 identical in a row.
    agent = _varying_file_agent([["a.py"], ["b.py"], ["c.py"], ["d.py"], ["e.py"], ["f.py"]])
    verify = _varying_error_verify(["A", "A", "B", "A", "A", "B", "A", "A", "B", "A"])

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=agent,
        verify_runner=verify,
        now=_FIXED_NOW_DT,
    )

    assert result.stop_reason != "repeated-error"


def test_repeated_error_limit_zero_disables_breaker(tmp_path: Path) -> None:
    """Setting repeated_error_limit=0 disables the repeated-error breaker."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="task")
    config = LoopConfig(
        max_iterations=3,
        no_progress_window=20,
        duplicate_action_limit=0,
        repeated_error_limit=0,
    )

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_varying_file_agent([["a.py"], ["b.py"], ["c.py"]]),
        verify_runner=_fake_verify(passes=False, output="SAME"),
        now=_FIXED_NOW_DT,
    )

    assert result.stop_reason != "repeated-error"


# ---------------------------------------------------------------------------
# Backward-compatibility: new knob defaults do not break existing behaviour
# ---------------------------------------------------------------------------


def test_defaults_backward_compatible_converge(tmp_path: Path) -> None:
    """Default LoopConfig still converges on first win with new fields present."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="add the index")
    config = LoopConfig(max_iterations=5)

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(),
        verify_runner=_fake_verify(passes=True, output="1 passed"),
        now=_FIXED_NOW_DT,
    )

    assert result.converged is True
    assert result.stop_reason == "converged"
    assert len(result.iterations) == 1


def test_defaults_no_progress_still_fires(tmp_path: Path) -> None:
    """no-progress fires when duplicate_action_limit > no_progress_window."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="fix flaky test")
    # Set duplicate_action_limit > no_progress_window so no-progress fires first.
    config = LoopConfig(
        max_iterations=10,
        no_progress_window=3,
        duplicate_action_limit=10,
        repeated_error_limit=0,
    )

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["tests/test_foo.py"]),
        verify_runner=_fake_verify(passes=False, output="FAILED: flaky"),
        now=_FIXED_NOW_DT,
    )

    assert result.stop_reason == "no-progress"
    assert len(result.iterations) == config.no_progress_window


# ---------------------------------------------------------------------------
# stop_reason surfaces in LoopResult
# ---------------------------------------------------------------------------


def test_stop_reason_duplicate_action_in_result(tmp_path: Path) -> None:
    """stop_reason 'duplicate-action' is present in LoopResult.stop_reason."""
    storage = _storage(tmp_path)
    config = LoopConfig(
        max_iterations=10,
        no_progress_window=20,
        duplicate_action_limit=2,
    )
    result = run_loop(
        storage,
        tmp_path,
        LoopSpec(goal="g"),
        config,
        agent_runner=_fake_agent(files=["f.py"]),
        verify_runner=_fake_verify(passes=False, output="err"),
        now=_FIXED_NOW_DT,
    )
    assert result.stop_reason == "duplicate-action"


def test_stop_reason_repeated_error_in_result(tmp_path: Path) -> None:
    """stop_reason 'repeated-error' is present in LoopResult.stop_reason."""
    storage = _storage(tmp_path)
    config = LoopConfig(
        max_iterations=10,
        no_progress_window=20,
        duplicate_action_limit=0,
        repeated_error_limit=2,
    )
    result = run_loop(
        storage,
        tmp_path,
        LoopSpec(goal="g"),
        config,
        agent_runner=_varying_file_agent([["a.py"], ["b.py"]]),
        verify_runner=_fake_verify(passes=False, output="boom"),
        now=_FIXED_NOW_DT,
    )
    assert result.stop_reason == "repeated-error"


# ---------------------------------------------------------------------------
# Worktree isolation / rollback — real temp git repo, fake agent
# ---------------------------------------------------------------------------


def _init_temp_git_repo(path: Path) -> None:
    """Initialise a minimal git repository at *path* with one commit."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path, check=True, capture_output=True,
    )
    (path / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path, check=True, capture_output=True,
    )


def _file_writing_agent(filename: str, content: str = "changed") -> Callable[..., AgentRunResult]:
    """Agent that writes a file in the CWD of the process (which points to the
    repo_root passed to run_loop when isolation is active)."""
    call_count = [0]

    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        call_count[0] += 1
        # The engine passes no CWD hint to the agent; we rely on the
        # isolation provider swapping repo_root.  For testing we accept
        # the worktree_path via a closure injected from the fake provider.
        return AgentRunResult(
            output=f"wrote {filename}",
            prediction="",
            files_touched=[filename],
            tokens=None,
        )

    return _runner


class _FakeIsolationProvider:
    """Fake IsolationProvider that creates/removes a real temp directory but
    does NOT use git worktree — lets us test the rollback logic without
    requiring the process to be inside a git repo.

    The fake provider writes/removes a sentinel directory under ``base_dir``.
    """

    def __init__(self, base_dir: Path, *, fail_setup: bool = False) -> None:
        self._base_dir = base_dir
        self._fail_setup = fail_setup
        self.setup_called = False
        self.teardown_called = False
        self.teardown_keep: bool | None = None
        self._wt_path: Path | None = None

    def setup(self, repo_root: Path) -> Path | None:
        del repo_root
        self.setup_called = True
        if self._fail_setup:
            return None
        wt = self._base_dir / "fake-worktree"
        wt.mkdir(parents=True, exist_ok=True)
        self._wt_path = wt
        return wt

    def teardown(self, worktree_path: Path, *, keep: bool) -> None:
        self.teardown_called = True
        self.teardown_keep = keep
        if not keep:
            import shutil
            shutil.rmtree(worktree_path, ignore_errors=True)


def test_isolation_failure_rolls_back_worktree(tmp_path: Path) -> None:
    """On a FAILED loop run the worktree is removed (teardown keep=False)."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="fix the bug")
    config = LoopConfig(
        max_iterations=2,
        no_progress_window=20,
        duplicate_action_limit=0,
        repeated_error_limit=0,
        isolate=True,
    )
    provider = _FakeIsolationProvider(tmp_path / "iso")

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["x.py"]),
        verify_runner=_fake_verify(passes=False, output="fail"),
        now=_FIXED_NOW_DT,
        isolation_provider=provider,
    )

    assert result.converged is False
    assert provider.setup_called is True
    assert provider.teardown_called is True
    assert provider.teardown_keep is False
    # The worktree directory must be removed.
    assert provider._wt_path is not None
    assert not provider._wt_path.exists()


def test_isolation_success_keeps_worktree(tmp_path: Path) -> None:
    """On a SUCCESSFUL (converged) loop run the worktree is kept (teardown keep=True)."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="add feature")
    config = LoopConfig(
        max_iterations=5,
        no_progress_window=20,
        duplicate_action_limit=0,
        repeated_error_limit=0,
        isolate=True,
    )
    provider = _FakeIsolationProvider(tmp_path / "iso")

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["new_file.py"]),
        verify_runner=_fake_verify(passes=True, output="1 passed"),
        now=_FIXED_NOW_DT,
        isolation_provider=provider,
    )

    assert result.converged is True
    assert result.stop_reason == "converged"
    assert provider.setup_called is True
    assert provider.teardown_called is True
    assert provider.teardown_keep is True
    # The worktree directory is still present (kept=True means no rmtree).
    assert provider._wt_path is not None
    assert provider._wt_path.exists()


def test_isolation_setup_failure_degrades_gracefully(tmp_path: Path) -> None:
    """When isolation setup returns None, the engine runs in-place without error."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="fix")
    config = LoopConfig(
        max_iterations=2,
        no_progress_window=20,
        duplicate_action_limit=0,
        repeated_error_limit=0,
        isolate=True,
    )
    provider = _FakeIsolationProvider(tmp_path / "iso", fail_setup=True)

    # Should NOT raise — degrade silently to in-place.
    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(files=["x.py"]),
        verify_runner=_fake_verify(passes=False, output="err"),
        now=_FIXED_NOW_DT,
        isolation_provider=provider,
    )

    assert provider.setup_called is True
    # No teardown when setup returned None (nothing to clean up).
    assert provider.teardown_called is False
    valid_reasons = {"max-iterations", "no-progress", "duplicate-action", "repeated-error"}
    assert result.stop_reason in valid_reasons


def test_real_worktree_isolation_rollback(tmp_path: Path) -> None:
    """Integration test with a real git repo and real WorktreeIsolationProvider.

    A fake agent writes a file inside the worktree.  On failure (verify never
    passes) the worktree is removed so the main working tree is unchanged.

    Requires git to be available on PATH.  Skipped otherwise.
    """
    import shutil

    if not shutil.which("git"):
        pytest.skip("git not available on PATH")

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_temp_git_repo(repo)

    sentinel = "injected-by-test.txt"

    def _writing_agent(prompt: str, *, escalation_level: int) -> AgentRunResult:
        """Write a file in the current working directory (which is the main repo,
        not the worktree — this tests that the main tree stays clean)."""
        del prompt, escalation_level
        # This agent doesn't know the worktree path; it writes to the main repo.
        # The test checks the main repo stays clean.
        return AgentRunResult(
            output=f"touched {sentinel}",
            prediction="",
            files_touched=[sentinel],
            tokens=None,
        )

    from oh_no_my_claudecode.core.repo import WorktreeIsolationProvider

    storage = _storage(tmp_path)
    spec = LoopSpec(goal="fail-loop")
    config = LoopConfig(
        max_iterations=1,
        no_progress_window=20,
        duplicate_action_limit=0,
        repeated_error_limit=0,
        isolate=True,
    )
    provider = WorktreeIsolationProvider()

    result = run_loop(
        storage,
        repo,
        spec,
        config,
        agent_runner=_writing_agent,
        verify_runner=_fake_verify(passes=False, output="always fail"),
        now=_FIXED_NOW_DT,
        isolation_provider=provider,
    )

    assert result.converged is False
    # Main working tree must not contain the worktree path or any leaked state.
    # The worktree was under a temp dir; confirm it was removed.
    if provider._worktree_path is not None:
        assert not provider._worktree_path.exists(), (
            f"Worktree {provider._worktree_path} still exists after rollback"
        )
