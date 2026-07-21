"""Tests for the rich verify gate: zero-diff and scope checks.

The gate has three layers (all must hold for a win):
  1. verify command exits 0  (existing)
  2. working tree actually changed  (vacuous-pass gate — guards false-green)
  3. changed files are within scope  (scope gate — optional, config-driven)

These tests verify each layer in isolation and in combination, using only
injected fake runners — no real subprocess, no real agent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from oh_no_my_claudecode.loop.engine import (
    _files_from_git_status,
    _scope_violation,
    run_loop,
)
from oh_no_my_claudecode.loop.models import (
    AgentRunResult,
    LoopConfig,
    LoopSpec,
    VerifyOutcome,
)
from oh_no_my_claudecode.storage import SQLiteStorage

_FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _storage(tmp_path: Path) -> SQLiteStorage:
    db = SQLiteStorage(tmp_path / "onmc.db")
    db.initialize()
    return db


def _fake_agent(
    output: str = "did work",
    files: list[str] | None = None,
) -> object:
    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output=output,
            prediction="",
            files_touched=files or [],
            tokens=None,
        )

    return _runner


def _fake_verify(*, passes: bool, output: str = "") -> object:
    def _runner(command: str) -> VerifyOutcome:
        del command
        return VerifyOutcome(passed=passes, output=output)

    return _runner


def _static_probe(signature: str | None = "unchanged") -> object:
    """ChangeProbe that always returns the same value (no change)."""

    def _probe() -> str | None:
        return signature

    return _probe


def _changing_probe(before: str = "before", after: str = "after") -> object:
    """ChangeProbe that returns a different signature each call (simulates change)."""
    calls = [0]

    def _probe() -> str | None:
        calls[0] += 1
        return before if calls[0] % 2 == 1 else after

    return _probe


def _git_status_probe(
    pre: str,
    post: str,
) -> object:
    """ChangeProbe returning different outputs before/after agent runs.

    First call returns *pre* (captured before agent), subsequent calls return
    *post* (captured after agent).  Simulates a real git status probe without
    shelling out.
    """
    calls = [0]

    def _probe() -> str | None:
        calls[0] += 1
        return pre if calls[0] == 1 else post

    return _probe


# ---------------------------------------------------------------------------
# Unit tests for _files_from_git_status
# ---------------------------------------------------------------------------


class TestFilesFromGitStatus:
    """Pure-function tests: no subprocess, no git."""

    def test_empty_input_returns_empty(self) -> None:
        assert _files_from_git_status("") == frozenset()

    def test_none_input_returns_empty(self) -> None:
        assert _files_from_git_status(None) == frozenset()

    def test_modified_file(self) -> None:
        status = " M src/module.py\n"
        assert _files_from_git_status(status) == frozenset(["src/module.py"])

    def test_untracked_file(self) -> None:
        status = "?? tests/new_test.py\n"
        assert _files_from_git_status(status) == frozenset(["tests/new_test.py"])

    def test_multiple_files(self) -> None:
        status = " M src/a.py\nA  src/b.py\n?? docs/c.md\n"
        assert _files_from_git_status(status) == frozenset(["src/a.py", "src/b.py", "docs/c.md"])

    def test_rename_takes_new_path(self) -> None:
        status = "R  old_name.py -> new_name.py\n"
        result = _files_from_git_status(status)
        assert "new_name.py" in result
        assert "old_name.py" not in result

    def test_deleted_file_is_included(self) -> None:
        status = " D removed.py\n"
        assert "removed.py" in _files_from_git_status(status)

    def test_mixed_statuses(self) -> None:
        status = " M src/foo.py\n?? tests/bar.py\nD  old.py\n"
        result = _files_from_git_status(status)
        assert result == frozenset(["src/foo.py", "tests/bar.py", "old.py"])


# ---------------------------------------------------------------------------
# Unit tests for _scope_violation
# ---------------------------------------------------------------------------


class TestScopeViolation:
    """Pure-function tests for the scope-check helper."""

    def test_no_scope_configured_never_violates(self) -> None:
        files = frozenset(["anywhere/file.py", ".env", "CLAUDE.md"])
        assert _scope_violation(files, allowed_paths=[], protected_paths=[]) is None

    def test_empty_changed_files_never_violates(self) -> None:
        assert _scope_violation(frozenset(), ["src/**"], [".env"]) is None

    # --- allowed_paths ---

    def test_file_within_allowed_path_no_violation(self) -> None:
        files = frozenset(["src/module.py"])
        assert _scope_violation(files, allowed_paths=["src/**"], protected_paths=[]) is None

    def test_file_outside_allowed_path_is_violation(self) -> None:
        files = frozenset(["external/lib.py"])
        result = _scope_violation(files, allowed_paths=["src/**"], protected_paths=[])
        assert result is not None
        assert "out-of-scope" in result
        assert "external/lib.py" in result

    def test_mixed_files_some_out_of_scope(self) -> None:
        files = frozenset(["src/ok.py", "external/bad.py"])
        result = _scope_violation(files, allowed_paths=["src/**"], protected_paths=[])
        assert result is not None
        assert "external/bad.py" in result
        assert "src/ok.py" not in result

    def test_multiple_allowed_patterns_any_match_passes(self) -> None:
        files = frozenset(["src/a.py", "tests/b.py"])
        result = _scope_violation(files, allowed_paths=["src/**", "tests/**"], protected_paths=[])
        assert result is None

    def test_exact_filename_pattern(self) -> None:
        files = frozenset(["README.md"])
        assert _scope_violation(files, allowed_paths=["README.md"], protected_paths=[]) is None

    def test_glob_star_matches_extension(self) -> None:
        files = frozenset(["main.py"])
        assert _scope_violation(files, allowed_paths=["*.py"], protected_paths=[]) is None

    def test_non_python_out_of_scope_when_only_py_allowed(self) -> None:
        files = frozenset(["config.json"])
        result = _scope_violation(files, allowed_paths=["*.py"], protected_paths=[])
        assert result is not None

    # --- protected_paths ---

    def test_protected_file_not_modified_no_violation(self) -> None:
        files = frozenset(["src/module.py"])
        assert _scope_violation(files, allowed_paths=[], protected_paths=[".env"]) is None

    def test_protected_file_modified_is_violation(self) -> None:
        files = frozenset([".env"])
        result = _scope_violation(files, allowed_paths=[], protected_paths=[".env"])
        assert result is not None
        assert "protected file modified" in result
        assert ".env" in result

    def test_protected_glob_matches(self) -> None:
        files = frozenset(["secrets/prod.key"])
        result = _scope_violation(files, allowed_paths=[], protected_paths=["secrets/**"])
        assert result is not None

    # --- both checks together ---

    def test_both_checks_independent(self) -> None:
        """A file can be in-scope AND the protected check can fire on a different file."""
        files = frozenset(["src/ok.py", ".env"])
        result = _scope_violation(files, allowed_paths=["src/**"], protected_paths=[".env"])
        assert result is not None
        assert "protected" in result
        assert "out-of-scope" in result  # .env fails allowed_paths too


# ---------------------------------------------------------------------------
# Integration tests: zero-diff gate (vacuous-pass)
# ---------------------------------------------------------------------------

# These replicate / extend the measured false-green bug: a no-op agent that
# changes nothing but whose verify exits 0 must NOT converge.


class TestZeroDiffGate:
    """Verify that a zero-diff (no working-tree change) can never converge."""

    def test_zero_diff_with_green_verify_does_not_converge(self, tmp_path: Path) -> None:
        """THE measured bug: verify passes but tree unchanged → NOT converged."""
        storage = _storage(tmp_path)
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="implement the feature"),
            LoopConfig(max_iterations=1),
            agent_runner=_fake_agent("claimed victory, touched nothing"),
            verify_runner=_fake_verify(passes=True, output="5 passed"),
            change_probe=_static_probe("same-sig"),  # tree NEVER changes
            now=_FIXED_NOW,
        )

        assert result.converged is False, (
            "A no-op run (zero diff) must NEVER converge even when verify exits 0. "
            "This is the false-green bug the gate exists to close."
        )
        assert result.iterations[0].outcome == "loss"
        assert "[no-op]" in result.iterations[0].verify_output

    def test_zero_diff_with_failing_verify_is_also_loss(self, tmp_path: Path) -> None:
        """No change + failing verify → loss (consistent with existing behaviour)."""
        storage = _storage(tmp_path)
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="fix tests"),
            LoopConfig(max_iterations=1),
            agent_runner=_fake_agent("did nothing"),
            verify_runner=_fake_verify(passes=False, output="tests failed"),
            change_probe=_static_probe("same"),
            now=_FIXED_NOW,
        )
        assert result.converged is False
        assert result.iterations[0].outcome == "loss"
        # The [no-op] prefix should NOT be present when verify also fails.
        assert "[no-op]" not in result.iterations[0].verify_output

    def test_real_change_plus_green_verify_converges(self, tmp_path: Path) -> None:
        """Real change + passing verify → converged. The healthy path must still work."""
        storage = _storage(tmp_path)
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="add divide function"),
            LoopConfig(max_iterations=3),
            agent_runner=_fake_agent("wrote divide() + tests", files=["src/math.py"]),
            verify_runner=_fake_verify(passes=True, output="3 passed"),
            change_probe=_changing_probe(),
            now=_FIXED_NOW,
        )
        assert result.converged is True
        assert result.stop_reason == "converged"

    def test_undeterminable_probe_preserves_legacy_behaviour(self, tmp_path: Path) -> None:
        """When the probe returns None (git unavailable) the zero-diff gate is skipped."""
        storage = _storage(tmp_path)
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="fix lint"),
            LoopConfig(max_iterations=1),
            agent_runner=_fake_agent("fixed"),
            verify_runner=_fake_verify(passes=True, output="ok"),
            change_probe=_static_probe(None),  # probe undeterminable → skip gate
            now=_FIXED_NOW,
        )
        assert result.converged is True


# ---------------------------------------------------------------------------
# Integration tests: scope gate (allowed_paths / protected_paths)
# ---------------------------------------------------------------------------


class TestScopeGate:
    """Verify the optional scope gate wired into run_loop."""

    def test_scope_not_configured_does_not_affect_win(self, tmp_path: Path) -> None:
        """Empty allowed/protected (defaults) → gate disabled → converges normally."""
        storage = _storage(tmp_path)
        git_status_after = " M anywhere/file.py\n"
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="do anything"),
            LoopConfig(max_iterations=1),  # no allowed_paths / protected_paths
            agent_runner=_fake_agent("did work"),
            verify_runner=_fake_verify(passes=True, output="ok"),
            change_probe=_git_status_probe(pre="", post=git_status_after),
            now=_FIXED_NOW,
        )
        assert result.converged is True

    def test_changes_within_allowed_paths_converge(self, tmp_path: Path) -> None:
        """Files inside the allowed scope + green verify → converges."""
        storage = _storage(tmp_path)
        git_status_after = " M src/module.py\n"
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="implement the module"),
            LoopConfig(max_iterations=1, allowed_paths=["src/**", "tests/**"]),
            agent_runner=_fake_agent("wrote module"),
            verify_runner=_fake_verify(passes=True, output="ok"),
            change_probe=_git_status_probe(pre="", post=git_status_after),
            now=_FIXED_NOW,
        )
        assert result.converged is True, (
            "A change inside the declared allowed_paths with green verify must converge."
        )

    def test_out_of_scope_change_prevents_convergence(self, tmp_path: Path) -> None:
        """File outside allowed_paths → scope violation → NOT converged even if verify passes."""
        storage = _storage(tmp_path)
        git_status_after = " M external/lib.py\n"
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="add feature"),
            LoopConfig(max_iterations=1, allowed_paths=["src/**"]),
            agent_runner=_fake_agent("modified external lib"),
            verify_runner=_fake_verify(passes=True, output="ok"),
            change_probe=_git_status_probe(pre="", post=git_status_after),
            now=_FIXED_NOW,
        )
        assert result.converged is False, (
            "An out-of-scope file change must NOT converge even when verify exits 0."
        )
        it = result.iterations[0]
        assert it.outcome == "loss"
        assert "[scope-violation]" in it.verify_output
        assert "external/lib.py" in it.verify_output

    def test_protected_file_modified_prevents_convergence(self, tmp_path: Path) -> None:
        """Modifying a protected file → scope violation → NOT converged."""
        storage = _storage(tmp_path)
        git_status_after = " M .env\n M src/app.py\n"
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="update app"),
            LoopConfig(max_iterations=1, protected_paths=[".env", "secrets/**"]),
            agent_runner=_fake_agent("updated app and env"),
            verify_runner=_fake_verify(passes=True, output="ok"),
            change_probe=_git_status_probe(pre="", post=git_status_after),
            now=_FIXED_NOW,
        )
        assert result.converged is False, (
            "Modifying a protected file must NOT converge even when verify exits 0."
        )
        it = result.iterations[0]
        assert it.outcome == "loss"
        assert "[scope-violation]" in it.verify_output
        assert ".env" in it.verify_output

    def test_protected_glob_prevents_convergence(self, tmp_path: Path) -> None:
        """Protected glob pattern matches a file under a directory."""
        storage = _storage(tmp_path)
        git_status_after = " M secrets/prod.key\n"
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="task"),
            LoopConfig(max_iterations=1, protected_paths=["secrets/**"]),
            agent_runner=_fake_agent("oops touched secrets"),
            verify_runner=_fake_verify(passes=True, output="ok"),
            change_probe=_git_status_probe(pre="", post=git_status_after),
            now=_FIXED_NOW,
        )
        assert result.converged is False

    def test_scope_violation_only_fires_when_verify_passes(self, tmp_path: Path) -> None:
        """When verify FAILS, it's already a loss — scope message is not added."""
        storage = _storage(tmp_path)
        git_status_after = " M external/lib.py\n"
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="task"),
            LoopConfig(max_iterations=1, allowed_paths=["src/**"]),
            agent_runner=_fake_agent("modified bad file"),
            verify_runner=_fake_verify(passes=False, output="tests failed"),
            change_probe=_git_status_probe(pre="", post=git_status_after),
            now=_FIXED_NOW,
        )
        assert result.converged is False
        # The loss is due to verify failing, not scope — no scope-violation prefix.
        assert "[scope-violation]" not in result.iterations[0].verify_output

    def test_allowed_and_protected_both_active(self, tmp_path: Path) -> None:
        """File is in-scope (matches allowed) but also protected → loss."""
        storage = _storage(tmp_path)
        # src/config.py is inside src/** (allowed) but also protected
        git_status_after = " M src/config.py\n"
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="task"),
            LoopConfig(
                max_iterations=1,
                allowed_paths=["src/**"],
                protected_paths=["src/config.py"],
            ),
            agent_runner=_fake_agent("modified config"),
            verify_runner=_fake_verify(passes=True, output="ok"),
            change_probe=_git_status_probe(pre="", post=git_status_after),
            now=_FIXED_NOW,
        )
        assert result.converged is False
        assert "[scope-violation]" in result.iterations[0].verify_output

    def test_scope_gate_disabled_when_probe_returns_none(self, tmp_path: Path) -> None:
        """When change probe is undeterminable, scope gate cannot fire (no file list)."""
        storage = _storage(tmp_path)
        # probe returns None → changed_files is empty → no scope violation
        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="task"),
            LoopConfig(max_iterations=1, allowed_paths=["src/**"]),
            agent_runner=_fake_agent("did something"),
            verify_runner=_fake_verify(passes=True, output="ok"),
            change_probe=_static_probe(None),  # undeterminable
            now=_FIXED_NOW,
        )
        # Undeterminable probe → zero-diff gate skipped → verify pass accepted
        assert result.converged is True

    def test_multiple_iterations_scope_violation_then_fix(self, tmp_path: Path) -> None:
        """Scope violation on first iteration, valid change on second → converges."""
        storage = _storage(tmp_path)
        calls = [0]

        def _changing_status_probe() -> str | None:
            calls[0] += 1
            if calls[0] <= 2:  # pre/post for iteration 1
                return "" if calls[0] == 1 else " M external/lib.py\n"
            else:  # pre/post for iteration 2
                if calls[0] == 3:
                    return " M external/lib.py\n"
                return " M external/lib.py\n M src/good.py\n"

        # Second iteration verify passes; scope also passes (src/good.py is in scope)
        verify_count = [0]

        def _verify_runner(command: str) -> VerifyOutcome:
            del command
            verify_count[0] += 1
            return VerifyOutcome(passed=True, output="ok")

        result = run_loop(
            storage,
            tmp_path,
            LoopSpec(goal="fix things"),
            LoopConfig(max_iterations=3, allowed_paths=["src/**"]),
            agent_runner=_fake_agent("worked"),
            verify_runner=_verify_runner,
            change_probe=_changing_status_probe,
            now=_FIXED_NOW,
        )
        # First iteration: scope violation (external/lib.py not in src/**)
        assert result.iterations[0].outcome == "loss"
        assert "[scope-violation]" in result.iterations[0].verify_output
        # The old dirty file remains in post-status, but only the new src change
        # belongs to iteration 2 and should be scope-checked.
        assert result.converged is True
        assert result.iterations[1].outcome == "win"
        assert "[scope-violation]" not in result.iterations[1].verify_output
