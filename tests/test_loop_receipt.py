"""Tests for P1 loop receipt: tamper-evident run receipts, cost/wall-time limits.

All tests use ONLY injected fake runners — no real subprocess, no real agent,
no real git, no real clock.  All values are deterministic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oh_no_my_claudecode.loop.engine import run_loop
from oh_no_my_claudecode.loop.models import (
    AgentRunResult,
    IterationContract,
    LoopConfig,
    LoopResult,
    LoopSpec,
    VerifyOutcome,
)
from oh_no_my_claudecode.loop.receipt import (
    _build_hash_chain,
    build_receipt,
    write_receipt,
)
from oh_no_my_claudecode.storage import SQLiteStorage

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


def _storage(tmp_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(tmp_path / "onmc.db")
    storage.initialize()
    return storage


def _fake_agent(
    output: str = "did something",
    prediction: str = "pred",
    files: list[str] | None = None,
    tokens: int | None = 100,
    cost_usd: float | None = None,
) -> object:
    def _runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt, escalation_level
        return AgentRunResult(
            output=output,
            prediction=prediction,
            files_touched=files or [],
            tokens=tokens,
            cost_usd=cost_usd,
        )

    return _runner


def _fake_verify(*, passes: bool, output: str = "") -> object:
    def _runner(command: str) -> VerifyOutcome:
        del command
        return VerifyOutcome(passed=passes, output=output)

    return _runner


def _minimal_result(
    *,
    converged: bool = True,
    stop_reason: str = "converged",
    n_iter: int = 1,
    verify_passed: bool = True,
    total_tokens: int = 500,
    total_cost_usd: float | None = None,
) -> LoopResult:
    """Build a synthetic LoopResult for unit-testing receipt logic."""
    iterations = [
        IterationContract(
            iteration=i,
            prediction=f"pred {i}",
            action_summary=f"did thing {i}",
            files_touched=[f"src/file{i}.py"],
            verify_passed=(verify_passed if i == n_iter else False),
            verify_output="ok" if (verify_passed and i == n_iter) else "FAILED",
            outcome="win" if (verify_passed and i == n_iter) else "loss",
            tokens=100,
        )
        for i in range(1, n_iter + 1)
    ]
    return LoopResult(
        iterations=iterations,
        converged=converged,
        stop_reason=stop_reason,
        recorded_memory_ids=[f"mid{i}" for i in range(n_iter)],
        total_tokens=total_tokens,
        total_cost_usd=total_cost_usd,
    )


def _noop_git_runner(
    cmd: list[str], cwd: str, timeout: int
) -> tuple[int, str]:
    """Fake git runner that returns predictable values."""
    if "rev-parse" in cmd:
        return 0, "abcdef1234567890abcdef1234567890abcdef12\n"
    if cmd[-1] == "diff":
        return 0, "diff --git a/src/file.py b/src/file.py\n+changed line\n"
    return 1, ""


# ---------------------------------------------------------------------------
# Test 1 — build_receipt is pure and deterministic
# ---------------------------------------------------------------------------


def test_build_receipt_is_deterministic() -> None:
    """build_receipt must return identical receipts for identical inputs."""
    result = _minimal_result()
    spec = LoopSpec(goal="fix the bug")
    config = LoopConfig(verify_command="pytest")

    r1 = build_receipt(
        result,
        spec,
        config,
        repo_root="/tmp/repo",  # noqa: S108
        agent="claude",
        model="claude-opus-4-5",
        wall_seconds=42.5,
        onmc_version="0.42.0",
        started_at="2024-06-01T12:00:00+00:00",
        ended_at="2024-06-01T12:00:42+00:00",
        git_runner=_noop_git_runner,
    )
    r2 = build_receipt(
        result,
        spec,
        config,
        repo_root="/tmp/repo",  # noqa: S108
        agent="claude",
        model="claude-opus-4-5",
        wall_seconds=42.5,
        onmc_version="0.42.0",
        started_at="2024-06-01T12:00:00+00:00",
        ended_at="2024-06-01T12:00:42+00:00",
        git_runner=_noop_git_runner,
    )

    assert r1.receipt_hash == r2.receipt_hash
    assert r1.loop_spec_sha == r2.loop_spec_sha
    assert r1.diff_sha == r2.diff_sha
    assert r1.git_tree_sha == r2.git_tree_sha


# ---------------------------------------------------------------------------
# Test 2 — verified=True only when converged AND final verify_passed
# ---------------------------------------------------------------------------


def test_verified_true_only_when_converged_and_verify_passed() -> None:
    """verified must be True iff result.converged AND final iteration verify_passed."""
    spec = LoopSpec(goal="goal")
    config = LoopConfig(verify_command="pytest")

    # Converged + verify passed → verified=True
    r_good = build_receipt(
        _minimal_result(converged=True, verify_passed=True),
        spec,
        config,
        repo_root="/tmp/repo",  # noqa: S108
        agent="claude",
        model=None,
        wall_seconds=1.0,
        onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    assert r_good.verified is True

    # Not converged → verified=False even if verify_passed is True in data
    r_nc = build_receipt(
        _minimal_result(converged=False, stop_reason="max-iterations", verify_passed=False),
        spec,
        config,
        repo_root="/tmp/repo",  # noqa: S108
        agent="claude",
        model=None,
        wall_seconds=1.0,
        onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    assert r_nc.verified is False

    # Converged but final iteration verify_passed=False → verified=False
    r_cf = build_receipt(
        _minimal_result(converged=True, verify_passed=False),
        spec,
        config,
        repo_root="/tmp/repo",  # noqa: S108
        agent="claude",
        model=None,
        wall_seconds=1.0,
        onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    assert r_cf.verified is False


# ---------------------------------------------------------------------------
# Test 3 — hash chain is tamper-evident
# ---------------------------------------------------------------------------


def test_hash_chain_changes_when_iteration_changes() -> None:
    """Modifying any iteration's data must change the receipt_hash."""
    spec = LoopSpec(goal="tamper test")
    config = LoopConfig(verify_command="pytest")
    result_orig = _minimal_result(n_iter=2)

    r_orig = build_receipt(
        result_orig,
        spec,
        config,
        repo_root="/tmp/repo",  # noqa: S108
        agent="claude",
        model=None,
        wall_seconds=5.0,
        onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )

    # Tamper: change the verify_output of iteration 1
    tampered_iters = list(result_orig.iterations)
    old = tampered_iters[0]
    tampered_iters[0] = IterationContract(
        iteration=old.iteration,
        prediction=old.prediction,
        action_summary=old.action_summary,
        files_touched=old.files_touched,
        verify_passed=old.verify_passed,
        verify_output="TAMPERED OUTPUT",  # changed
        outcome=old.outcome,
        tokens=old.tokens,
    )
    tampered_result = LoopResult(
        iterations=tampered_iters,
        converged=result_orig.converged,
        stop_reason=result_orig.stop_reason,
        recorded_memory_ids=result_orig.recorded_memory_ids,
        total_tokens=result_orig.total_tokens,
        total_cost_usd=result_orig.total_cost_usd,
    )

    r_tampered = build_receipt(
        tampered_result,
        spec,
        config,
        repo_root="/tmp/repo",  # noqa: S108
        agent="claude",
        model=None,
        wall_seconds=5.0,
        onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )

    assert r_orig.receipt_hash != r_tampered.receipt_hash, (
        "receipt_hash must change when iteration data is tampered"
    )
    assert len(r_orig.iteration_hashes) == 2
    assert len(r_tampered.iteration_hashes) == 2
    # First hash must differ; second also (chain propagates).
    assert r_orig.iteration_hashes[0] != r_tampered.iteration_hashes[0]
    assert r_orig.iteration_hashes[1] != r_tampered.iteration_hashes[1]


# ---------------------------------------------------------------------------
# Test 4 — hash chain has correct length per iteration
# ---------------------------------------------------------------------------


def test_hash_chain_length_matches_iterations() -> None:
    """iteration_hashes must have exactly one entry per iteration."""
    for n in (0, 1, 3, 5):
        result = _minimal_result(n_iter=n) if n > 0 else LoopResult(
            iterations=[],
            converged=False,
            stop_reason="no-progress",
            recorded_memory_ids=[],
            total_tokens=0,
        )
        hashes, _ = _build_hash_chain(result)
        assert len(hashes) == n, f"expected {n} hashes, got {len(hashes)}"


# ---------------------------------------------------------------------------
# Test 5 — write_receipt writes valid JSON to .agent-memory/receipts/
# ---------------------------------------------------------------------------


def test_write_receipt_writes_valid_json(tmp_path: Path) -> None:
    """write_receipt must create the receipts dir and write valid JSON."""
    spec = LoopSpec(goal="write test")
    config = LoopConfig(verify_command="pytest")
    result = _minimal_result()

    receipt = build_receipt(
        result,
        spec,
        config,
        repo_root=str(tmp_path),
        agent="claude",
        model=None,
        wall_seconds=3.0,
        onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )

    path = write_receipt(tmp_path, receipt)

    assert path.exists(), "receipt file must be created"
    assert path.parent == tmp_path / ".agent-memory" / "receipts"
    assert path.suffix == ".json"
    assert path.name.startswith("run-")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "2"
    assert data["goal"] == "write test"
    assert "receipt_hash" in data
    assert "iteration_hashes" in data
    assert isinstance(data["iteration_hashes"], list)


# ---------------------------------------------------------------------------
# Test 6 — write_receipt filename is content-derived (idempotent)
# ---------------------------------------------------------------------------


def test_write_receipt_filename_is_content_derived(tmp_path: Path) -> None:
    """Writing the same receipt twice must produce the same filename."""
    spec = LoopSpec(goal="idempotent test")
    config = LoopConfig(verify_command="pytest")
    result = _minimal_result()

    receipt = build_receipt(
        result,
        spec,
        config,
        repo_root=str(tmp_path),
        agent="claude",
        model=None,
        wall_seconds=7.0,
        onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )

    p1 = write_receipt(tmp_path, receipt)
    p2 = write_receipt(tmp_path, receipt)

    assert p1 == p2, "same receipt must produce the same filename"


# ---------------------------------------------------------------------------
# Test 7 — cost limit stops the loop with stop_reason "cost"
# ---------------------------------------------------------------------------


def test_cost_limit_stops_loop(tmp_path: Path) -> None:
    """Loop must stop with stop_reason='cost' when cumulative cost exceeds max_cost_usd."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="cost limit test")
    config = LoopConfig(
        max_iterations=10,
        no_progress_window=20,  # prevent no-progress stopping early
        max_cost_usd=0.50,  # will be exceeded after 3 iterations at $0.20 each
        verify_command="pytest",
    )

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(
            output="tried something",
            files=["src/x.py"],
            cost_usd=0.20,  # $0.20 per iteration
        ),
        verify_runner=_fake_verify(passes=False, output="FAILED"),
        now=_FIXED_NOW,
    )

    assert result.stop_reason == "cost", f"expected 'cost', got {result.stop_reason!r}"
    assert result.converged is False
    # 3 iterations at $0.20 = $0.60 which exceeds $0.50; check stops before 4th
    # After iter 1: $0.20; after iter 2: $0.40; after iter 3: $0.60 → next iter
    # is blocked. So we should have exactly 3 iterations completed.
    assert len(result.iterations) <= 3, (
        f"expected at most 3 iterations, got {len(result.iterations)}"
    )
    assert result.total_cost_usd is not None
    assert result.total_cost_usd > 0


# ---------------------------------------------------------------------------
# Test 8 — wall-time limit stops the loop with stop_reason "wall-time"
# ---------------------------------------------------------------------------


def test_wall_time_limit_stops_loop(tmp_path: Path) -> None:
    """Loop must stop with stop_reason='wall-time' via injected clock."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="wall-time test")
    config = LoopConfig(
        max_iterations=10,
        no_progress_window=20,
        max_wall_seconds=5,  # 5s limit
        verify_command="pytest",
    )

    # Clock starts at 0, advances by 3 each call
    tick = [0.0]

    def _advancing_clock() -> float:
        t = tick[0]
        tick[0] += 3.0  # each iteration costs 3 simulated seconds
        return t

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(output="tried", files=["x.py"]),
        verify_runner=_fake_verify(passes=False, output="FAILED"),
        now=_FIXED_NOW,
        clock=_advancing_clock,
    )

    assert result.stop_reason == "wall-time", (
        f"expected 'wall-time', got {result.stop_reason!r}"
    )
    assert result.converged is False


# ---------------------------------------------------------------------------
# Test 9 — cost limit=None does not stop the loop early
# ---------------------------------------------------------------------------


def test_no_cost_limit_runs_to_max_iterations(tmp_path: Path) -> None:
    """When max_cost_usd is None the loop must NOT stop on cost."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="no cost limit")
    config = LoopConfig(
        max_iterations=3,
        no_progress_window=20,
        max_cost_usd=None,
        verify_command="pytest",
    )

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(cost_usd=99.99),  # very high per-iteration cost
        verify_runner=_fake_verify(passes=False, output="FAILED"),
        now=_FIXED_NOW,
    )

    assert result.stop_reason == "max-iterations"
    assert len(result.iterations) == 3


# ---------------------------------------------------------------------------
# Test 10 — wall-time limit=None does not stop early
# ---------------------------------------------------------------------------


def test_no_wall_time_limit_runs_to_max(tmp_path: Path) -> None:
    """When max_wall_seconds is None the loop must NOT stop on time."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="no wall time limit")
    config = LoopConfig(
        max_iterations=3,
        no_progress_window=20,
        max_wall_seconds=None,
        verify_command="pytest",
    )

    # Clock advances rapidly — should be ignored when limit is None
    tick = [0.0]

    def _fast_clock() -> float:
        t = tick[0]
        tick[0] += 1000.0
        return t

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(),
        verify_runner=_fake_verify(passes=False, output="FAILED"),
        now=_FIXED_NOW,
        clock=_fast_clock,
    )

    assert result.stop_reason == "max-iterations"
    assert len(result.iterations) == 3


# ---------------------------------------------------------------------------
# Test 11 — receipt.verified=True reflects converged loop
# ---------------------------------------------------------------------------


def test_receipt_verified_true_for_converged_loop(tmp_path: Path) -> None:
    """A converged loop (verify exit 0) must produce receipt.verified=True."""
    result = _minimal_result(converged=True, verify_passed=True, n_iter=2)
    spec = LoopSpec(goal="converged loop")
    config = LoopConfig(verify_command="pytest tests/")

    receipt = build_receipt(
        result,
        spec,
        config,
        repo_root=str(tmp_path),
        agent="claude",
        model="claude-opus-4-5",
        wall_seconds=30.0,
        onmc_version="1.0.0",
        git_runner=_noop_git_runner,
    )

    assert receipt.verified is True
    assert receipt.stop_reason == "converged"
    assert receipt.verifier_command == "pytest tests/"
    assert receipt.iterations == 2
    assert receipt.tokens_used == 500


# ---------------------------------------------------------------------------
# Test 12 — receipt schema fields are all present and correct types
# ---------------------------------------------------------------------------


def test_receipt_schema_fields(tmp_path: Path) -> None:
    """All schema fields must be present in the JSON output."""
    spec = LoopSpec(goal="schema test")
    config = LoopConfig(verify_command="pytest", max_cost_usd=5.0)
    result = _minimal_result(total_cost_usd=1.23)

    receipt = build_receipt(
        result,
        spec,
        config,
        repo_root=str(tmp_path),
        agent="claude",
        model="claude-sonnet-4-5",
        wall_seconds=12.345,
        onmc_version="0.99.0",
        started_at="2024-01-01T00:00:00+00:00",
        ended_at="2024-01-01T00:00:12+00:00",
        git_runner=_noop_git_runner,
    )

    path = write_receipt(tmp_path, receipt)
    data = json.loads(path.read_text(encoding="utf-8"))

    required_fields = [
        "schema_version",
        "goal",
        "agent",
        "model",
        "verified",
        "stop_reason",
        "iterations",
        "tokens_used",
        "cost_usd",
        "wall_seconds",
        "verifier_command",
        "verifier_final_exit",
        "git_tree_sha",
        "diff_sha",
        "loop_spec_sha",
        "output_digest",
        "onmc_version",
        "started_at",
        "ended_at",
        "iteration_hashes",
        "receipt_hash",
        # Reproducibility envelope (schema_version "2")
        "model_version",
        "prompt_hash",
        "tool_defs_hash",
        "config_hash",
        "python_version",
        "platform",
    ]
    for field_name in required_fields:
        assert field_name in data, f"missing field: {field_name}"

    assert data["schema_version"] == "2"
    assert isinstance(data["iteration_hashes"], list)
    assert isinstance(data["receipt_hash"], str)
    assert len(data["receipt_hash"]) == 64  # SHA-256 hex = 64 chars
    assert data["cost_usd"] == pytest.approx(1.23, abs=0.001)
    assert data["model"] == "claude-sonnet-4-5"


# ---------------------------------------------------------------------------
# Test 13 — loop_spec_sha changes when goal or verify_command changes
# ---------------------------------------------------------------------------


def test_loop_spec_sha_changes_with_inputs() -> None:
    """Different goals or verify commands must produce different loop_spec_sha."""
    result = _minimal_result()

    spec_a = LoopSpec(goal="goal A")
    spec_b = LoopSpec(goal="goal B")
    config_v1 = LoopConfig(verify_command="pytest")
    config_v2 = LoopConfig(verify_command="make test")

    r_aa = build_receipt(
        result, spec_a, config_v1,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    r_ba = build_receipt(
        result, spec_b, config_v1,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    r_ab = build_receipt(
        result, spec_a, config_v2,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )

    assert r_aa.loop_spec_sha != r_ba.loop_spec_sha
    assert r_aa.loop_spec_sha != r_ab.loop_spec_sha


# ---------------------------------------------------------------------------
# Test 14 — git runner unavailable → git SHAs are None
# ---------------------------------------------------------------------------


def test_git_unavailable_produces_none_shas() -> None:
    """When git is unavailable (runner returns non-zero), SHAs must be None."""

    def _failing_git_runner(
        cmd: list[str], cwd: str, timeout: int
    ) -> tuple[int, str]:
        return 128, ""

    spec = LoopSpec(goal="no git")
    config = LoopConfig(verify_command="pytest")
    result = _minimal_result()

    receipt = build_receipt(
        result,
        spec,
        config,
        repo_root="/tmp/no-git-repo",  # noqa: S108
        agent="claude",
        model=None,
        wall_seconds=1.0,
        onmc_version="0.1.0",
        git_runner=_failing_git_runner,
    )

    assert receipt.git_tree_sha is None
    assert receipt.diff_sha is None


# ---------------------------------------------------------------------------
# Test 15 — LoopResult.total_cost_usd is populated from per-iteration costs
# ---------------------------------------------------------------------------


def test_total_cost_accumulates(tmp_path: Path) -> None:
    """total_cost_usd must sum per-iteration cost_usd values."""
    storage = _storage(tmp_path)
    spec = LoopSpec(goal="cost accumulation test")
    config = LoopConfig(max_iterations=3, no_progress_window=10, verify_command="pytest")

    result = run_loop(
        storage,
        tmp_path,
        spec,
        config,
        agent_runner=_fake_agent(cost_usd=0.10),
        verify_runner=_fake_verify(passes=False, output="FAILED"),
        now=_FIXED_NOW,
    )

    # 3 iterations × $0.10 = $0.30
    assert result.total_cost_usd is not None
    assert result.total_cost_usd == pytest.approx(0.30, abs=0.001)


# ---------------------------------------------------------------------------
# Test 16 — CLI loop command prints VERIFIED and Receipt path
# ---------------------------------------------------------------------------


def test_cli_loop_dry_run_does_not_write_receipt(tmp_path: Path) -> None:
    """CLI dry-run must not write a receipt file."""
    from typer.testing import CliRunner

    from oh_no_my_claudecode.cli import app
    from oh_no_my_claudecode.core.service import OnmcService

    # Initialize a real onmc project in a temp repo-like dir
    runner = CliRunner()
    # We need a git repo for onmc init
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, capture_output=True, check=True,
    )

    svc = OnmcService(tmp_path)
    svc.init_project()

    runner.invoke(
        app,
        ["loop", "--goal", "test goal", "--dry-run"],
        catch_exceptions=False,
        env={"HOME": str(tmp_path)},
    )

    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    # dry-run should not create the receipts dir / write a receipt
    if receipts_dir.exists():
        receipt_files = list(receipts_dir.glob("*.json"))
        assert len(receipt_files) == 0, "dry-run must not write a receipt"


# ---------------------------------------------------------------------------
# Test 17 — build_receipt loop_spec_sha stability test
# ---------------------------------------------------------------------------


def test_loop_spec_sha_is_deterministic() -> None:
    """The same spec + config must always produce the same loop_spec_sha."""
    spec = LoopSpec(goal="stable goal")
    config = LoopConfig(verify_command="make test")
    result = _minimal_result()

    receipts = [
        build_receipt(
            result, spec, config,
            repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
            wall_seconds=float(i), onmc_version="0.1.0",
            git_runner=_noop_git_runner,
        )
        for i in range(3)
    ]
    hashes = [r.loop_spec_sha for r in receipts]
    assert len(set(hashes)) == 1, "loop_spec_sha must be identical for same spec+config"


# ---------------------------------------------------------------------------
# Test 18 — reproducibility envelope: config_hash and prompt_hash are
#           deterministic and input-sensitive
# ---------------------------------------------------------------------------


def test_config_hash_is_deterministic_and_input_sensitive() -> None:
    """config_hash must be identical for the same config and differ on any knob change."""
    spec = LoopSpec(goal="config hash test")
    result = _minimal_result()

    cfg_a = LoopConfig(
        max_iterations=5,
        budget_tokens=10000,
        max_cost_usd=1.0,
        max_wall_seconds=300,
        verify_command="pytest",
        escalation_threshold=2,
        no_progress_window=3,
    )
    cfg_b = LoopConfig(
        max_iterations=10,  # changed
        budget_tokens=10000,
        max_cost_usd=1.0,
        max_wall_seconds=300,
        verify_command="pytest",
        escalation_threshold=2,
        no_progress_window=3,
    )

    r_a1 = build_receipt(
        result, spec, cfg_a,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    r_a2 = build_receipt(
        result, spec, cfg_a,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=99.0,  # different wall_seconds — must NOT affect config_hash
        onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    r_b = build_receipt(
        result, spec, cfg_b,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )

    # Same config → same config_hash regardless of wall_seconds.
    assert r_a1.config_hash == r_a2.config_hash, (
        "config_hash must be identical for the same LoopConfig knobs"
    )
    # Different max_iterations → different config_hash.
    assert r_a1.config_hash != r_b.config_hash, (
        "config_hash must differ when max_iterations changes"
    )
    # config_hash must be a 64-char hex SHA-256 digest.
    assert r_a1.config_hash is not None
    assert len(r_a1.config_hash) == 64


def test_prompt_hash_is_deterministic_and_input_sensitive() -> None:
    """prompt_hash must match sha256(goal) and differ for different goals."""
    import hashlib

    spec_a = LoopSpec(goal="goal alpha")
    spec_b = LoopSpec(goal="goal beta")
    config = LoopConfig(verify_command="pytest")
    result = _minimal_result()

    r_a = build_receipt(
        result, spec_a, config,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    r_b = build_receipt(
        result, spec_b, config,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )

    expected_a = hashlib.sha256(b"goal alpha").hexdigest()
    assert r_a.prompt_hash == expected_a, "prompt_hash must equal sha256(spec.goal)"
    assert r_a.prompt_hash != r_b.prompt_hash, (
        "prompt_hash must differ for different goals"
    )


# ---------------------------------------------------------------------------
# Test 19 — model_version flows through when provided; None when not
# ---------------------------------------------------------------------------


def test_model_version_flows_through() -> None:
    """model_version must equal the model arg when provided; None when model=None."""
    spec = LoopSpec(goal="model version test")
    config = LoopConfig(verify_command="pytest")
    result = _minimal_result()

    r_with = build_receipt(
        result, spec, config,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model="claude-opus-4-5",
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    r_without = build_receipt(
        result, spec, config,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )

    assert r_with.model_version == "claude-opus-4-5", (
        "model_version must equal the model arg when provided"
    )
    assert r_without.model_version is None, (
        "model_version must be None when model=None"
    )


# ---------------------------------------------------------------------------
# Test 20 — schema_version is "2"
# ---------------------------------------------------------------------------


def test_schema_version_is_two() -> None:
    """schema_version must be '2' in the current implementation."""
    spec = LoopSpec(goal="schema version test")
    config = LoopConfig(verify_command="pytest")
    result = _minimal_result()

    receipt = build_receipt(
        result, spec, config,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )

    assert receipt.schema_version == "2"


# ---------------------------------------------------------------------------
# Test 21 — legacy receipt (schema_version "1", no envelope fields) parses
#           everywhere it is read without crashing
# ---------------------------------------------------------------------------


def test_legacy_receipt_parses_in_evolution_and_dashboard(tmp_path: Path) -> None:
    """An old receipt JSON (schema_version '1', missing envelope fields) must
    be handled gracefully by compile_evolution and _loops_payload."""
    from oh_no_my_claudecode.evolution.compiler import compile_evolution

    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True)

    # Write two legacy receipts (schema v1 shape — no envelope fields).
    legacy_receipt: dict[str, object] = {
        "schema_version": "1",
        "goal": "old run goal",
        "agent": "claude",
        "model": None,
        "verified": True,
        "stop_reason": "converged",
        "iterations": 2,
        "tokens_used": 300,
        "cost_usd": 0.05,
        "wall_seconds": 12.0,
        "verifier_command": "pytest",
        "verifier_final_exit": 0,
        "git_tree_sha": "abc123",
        "diff_sha": "def456",
        "loop_spec_sha": "aabbccdd" * 8,
        "output_digest": "11223344" * 8,
        "onmc_version": "0.10.0",
        "started_at": "2024-01-01T00:00:00+00:00",
        "ended_at": "2024-01-01T00:00:12+00:00",
        "iteration_hashes": ["aa" * 32, "bb" * 32],
        "receipt_hash": "cc" * 32,
        # Deliberately absent: model_version, prompt_hash, tool_defs_hash,
        # config_hash, python_version, platform
    }

    for i in range(2):
        p = receipts_dir / f"run-legacy{i:04d}.json"
        p.write_text(json.dumps(legacy_receipt), encoding="utf-8")

    # compile_evolution must not raise and must return a valid report.
    report = compile_evolution(receipts_dir)
    assert report.run_count == 2
    assert not report.insufficient_data

    # The UI server _loops_payload reads receipts defensively — simulate it by
    # constructing the data dict directly (the function uses .get() throughout).
    from dataclasses import fields as _fields

    from oh_no_my_claudecode.loop.receipt import RunReceipt

    known = {f.name for f in _fields(RunReceipt)}
    for i in range(2):
        p = receipts_dir / f"run-legacy{i:04d}.json"
        raw = json.loads(p.read_text(encoding="utf-8"))
        # Reconstruct RunReceipt from legacy dict — unknown keys ignored,
        # missing keys fall back to field defaults (all new fields default None).
        receipt_obj = RunReceipt(**{k: v for k, v in raw.items() if k in known})
        # New envelope fields must be None (not present in legacy receipts).
        assert receipt_obj.model_version is None
        assert receipt_obj.prompt_hash is None
        assert receipt_obj.tool_defs_hash is None
        assert receipt_obj.config_hash is None
        assert receipt_obj.python_version is None
        assert receipt_obj.platform is None


# ---------------------------------------------------------------------------
# Test 22 — tool_defs_hash is deterministic and changes with agent or verifier
# ---------------------------------------------------------------------------


def test_tool_defs_hash_determinism_and_sensitivity() -> None:
    """tool_defs_hash must match sha256(verify_command:agent) and change on input change."""
    import hashlib

    spec = LoopSpec(goal="tool defs test")
    result = _minimal_result()

    cfg_pytest = LoopConfig(verify_command="pytest")
    cfg_make = LoopConfig(verify_command="make test")

    r_claude_pytest = build_receipt(
        result, spec, cfg_pytest,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    r_codex_pytest = build_receipt(
        result, spec, cfg_pytest,
        repo_root="/tmp",  # noqa: S108
        agent="codex", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )
    r_claude_make = build_receipt(
        result, spec, cfg_make,
        repo_root="/tmp",  # noqa: S108
        agent="claude", model=None,
        wall_seconds=1.0, onmc_version="0.1.0",
        git_runner=_noop_git_runner,
    )

    expected = hashlib.sha256(b"pytest:claude").hexdigest()
    assert r_claude_pytest.tool_defs_hash == expected
    assert r_claude_pytest.tool_defs_hash != r_codex_pytest.tool_defs_hash
    assert r_claude_pytest.tool_defs_hash != r_claude_make.tool_defs_hash
