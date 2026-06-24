"""Tests for onmc evolution: compile_evolution, CLI, and edge cases.

All tests use synthetic RunReceipt JSON files written to a temp directory.
No real loop/agent is ever run.

Test coverage:
1. Negative cost+iteration trend on 6 improving receipts (with cost_usd).
2. Chronological sort handles null timestamps (falls back to filename/mtime).
3. Fewer than 2 receipts → insufficient_data=True (no fabricated trend).
4. Malformed JSON file is skipped, not crashed.
5. Cost-unavailable receipts → trend on iterations only, cost flagged.
6. CLI exit code and --json shape.
7. Empty directory → insufficient_data, run_count=0, friendly render.
8. Non-existent directory → insufficient_data, run_count=0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.evolution.compiler import (
    compile_evolution,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RUNNER = CliRunner()


def _write_receipt(
    receipts_dir: Path,
    filename: str,
    *,
    goal: str = "test goal",
    agent: str = "claude",
    verified: bool = True,
    iterations: int = 3,
    tokens_used: int = 1000,
    cost_usd: float | None = 0.10,
    wall_seconds: float = 30.0,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> Path:
    """Write a minimal synthetic receipt JSON to *receipts_dir*."""
    receipts_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "1",
        "goal": goal,
        "agent": agent,
        "model": None,
        "verified": verified,
        "stop_reason": "converged" if verified else "max-iterations",
        "iterations": iterations,
        "tokens_used": tokens_used,
        "cost_usd": cost_usd,
        "wall_seconds": wall_seconds,
        "verifier_command": "pytest",
        "verifier_final_exit": 0 if verified else 1,
        "git_tree_sha": None,
        "diff_sha": None,
        "loop_spec_sha": "abc12345",
        "output_digest": "def67890",
        "onmc_version": "0.1.0",
        "started_at": started_at,
        "ended_at": ended_at,
        "iteration_hashes": [],
        "receipt_hash": "0" * 64,
    }
    dest = receipts_dir / filename
    dest.write_text(json.dumps(data), encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Test 1 — negative trend on improving receipts
# ---------------------------------------------------------------------------


def test_negative_trend_on_improving_receipts(tmp_path: Path) -> None:
    """Six receipts with decreasing cost + iterations must show negative deltas."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"

    # Early window: 3 expensive, slow runs
    _write_receipt(
        receipts_dir, "run-01.json",
        iterations=8, cost_usd=0.40,
        ended_at="2024-01-01T10:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-02.json",
        iterations=7, cost_usd=0.35,
        ended_at="2024-01-02T10:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-03.json",
        iterations=9, cost_usd=0.45,
        ended_at="2024-01-03T10:00:00+00:00",
    )
    # Recent window: 3 cheaper, faster runs
    _write_receipt(
        receipts_dir, "run-04.json",
        iterations=3, cost_usd=0.12,
        ended_at="2024-01-04T10:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-05.json",
        iterations=2, cost_usd=0.10,
        ended_at="2024-01-05T10:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-06.json",
        iterations=2, cost_usd=0.08,
        ended_at="2024-01-06T10:00:00+00:00",
    )

    report = compile_evolution(receipts_dir)

    assert report.insufficient_data is False
    assert report.run_count == 6
    assert report.cost_unavailable is False

    # Cost improved → negative pct
    assert report.cost_change_pct is not None
    assert report.cost_change_pct < 0, (
        f"Expected negative cost delta, got {report.cost_change_pct}"
    )

    # Iterations improved → negative pct
    assert report.iterations_change_pct is not None
    assert report.iterations_change_pct < 0, (
        f"Expected negative iterations delta, got {report.iterations_change_pct}"
    )

    # Verify window means make sense
    assert report.early_mean_iterations is not None
    assert report.recent_mean_iterations is not None
    assert report.recent_mean_iterations < report.early_mean_iterations

    # Verified rate (all verified=True by default)
    assert report.verified_rate == pytest.approx(1.0, abs=0.01)

    # Totals
    assert report.total_tokens == 6000
    expected_total = 0.40 + 0.35 + 0.45 + 0.12 + 0.10 + 0.08
    assert report.total_cost_usd == pytest.approx(expected_total, abs=0.001)


# ---------------------------------------------------------------------------
# Test 2 — chronological sort with null timestamps falls back to filename
# ---------------------------------------------------------------------------


def test_chronological_sort_null_timestamps_uses_filename(tmp_path: Path) -> None:
    """When timestamps are null, sort is deterministic via filename order."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"

    # Write three receipts with NO timestamps — sort must use filename/mtime
    _write_receipt(
        receipts_dir, "run-aaa.json",
        iterations=10, cost_usd=0.50,
        started_at=None, ended_at=None,
    )
    _write_receipt(
        receipts_dir, "run-bbb.json",
        iterations=8, cost_usd=0.30,
        started_at=None, ended_at=None,
    )
    _write_receipt(
        receipts_dir, "run-ccc.json",
        iterations=3, cost_usd=0.10,
        started_at=None, ended_at=None,
    )

    report = compile_evolution(receipts_dir)

    # Sort should be deterministic — exactly 3 runs loaded
    assert report.run_count == 3
    assert report.insufficient_data is False
    # Indices must be 0, 1, 2 in order
    indices = [p.index for p in report.runs]
    assert indices == [0, 1, 2]
    # No crash, no fabrication
    assert report.iterations_change_pct is not None


# ---------------------------------------------------------------------------
# Test 3 — fewer than 2 receipts → insufficient_data, no trend
# ---------------------------------------------------------------------------


def test_single_receipt_produces_insufficient_data(tmp_path: Path) -> None:
    """A single receipt must set insufficient_data=True with no trend numbers."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(
        receipts_dir, "run-only.json",
        iterations=5, cost_usd=0.20,
        ended_at="2024-01-01T10:00:00+00:00",
    )

    report = compile_evolution(receipts_dir)

    assert report.insufficient_data is True
    assert report.run_count == 1
    assert report.cost_change_pct is None
    assert report.iterations_change_pct is None
    assert report.early_mean_iterations is None
    assert report.recent_mean_iterations is None


def test_zero_receipts_produces_insufficient_data(tmp_path: Path) -> None:
    """An empty receipts directory must set insufficient_data=True."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)

    report = compile_evolution(receipts_dir)

    assert report.insufficient_data is True
    assert report.run_count == 0
    assert report.cost_change_pct is None


# ---------------------------------------------------------------------------
# Test 4 — malformed JSON file is skipped, not crashed
# ---------------------------------------------------------------------------


def test_malformed_json_file_is_skipped(tmp_path: Path) -> None:
    """A malformed JSON receipt must be silently skipped; valid ones still load."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)

    # Write one malformed file
    bad_file = receipts_dir / "run-bad.json"
    bad_file.write_text("{this is not valid JSON[[[ ---", encoding="utf-8")

    # Write two valid ones (need ≥2 for a trend)
    _write_receipt(
        receipts_dir, "run-good-a.json",
        iterations=6, cost_usd=0.30,
        ended_at="2024-01-01T10:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-good-b.json",
        iterations=2, cost_usd=0.10,
        ended_at="2024-01-02T10:00:00+00:00",
    )

    # Must not raise, must load the 2 valid ones
    report = compile_evolution(receipts_dir)
    assert report.run_count == 2
    assert report.insufficient_data is False


# ---------------------------------------------------------------------------
# Test 5 — cost unavailable → iteration trend still computed
# ---------------------------------------------------------------------------


def test_cost_unavailable_still_shows_iteration_trend(tmp_path: Path) -> None:
    """When no receipt has cost_usd, the iteration trend is still computed."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"

    _write_receipt(
        receipts_dir, "run-01.json",
        iterations=9, cost_usd=None,
        ended_at="2024-01-01T10:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-02.json",
        iterations=8, cost_usd=None,
        ended_at="2024-01-02T10:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-03.json",
        iterations=2, cost_usd=None,
        ended_at="2024-01-03T10:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-04.json",
        iterations=1, cost_usd=None,
        ended_at="2024-01-04T10:00:00+00:00",
    )

    report = compile_evolution(receipts_dir)

    assert report.cost_unavailable is True
    assert report.cost_change_pct is None
    assert report.total_cost_usd == 0.0

    # Iteration trend must still be computed
    assert report.iterations_change_pct is not None
    assert report.iterations_change_pct < 0  # improved


# ---------------------------------------------------------------------------
# Test 6a — CLI evolution exit code 0 on success
# ---------------------------------------------------------------------------


def _make_onmc_project(tmp_path: Path) -> None:
    """Initialize a git repo and onmc project in tmp_path."""
    import subprocess

    from oh_no_my_claudecode.core.service import OnmcService

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


def test_cli_evolution_exits_zero_with_receipts(tmp_path: Path) -> None:
    """CLI `onmc evolution` exits 0 when receipts exist."""
    import os

    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(
        receipts_dir, "run-01.json",
        iterations=5, cost_usd=0.25,
        ended_at="2024-01-01T10:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-02.json",
        iterations=2, cost_usd=0.10,
        ended_at="2024-01-02T10:00:00+00:00",
    )
    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(
            app,
            ["evolution"],
            catch_exceptions=False,
        )
    finally:
        os.chdir(orig)

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Test 6b — CLI --json shape
# ---------------------------------------------------------------------------


def test_cli_evolution_json_shape(tmp_path: Path) -> None:
    """CLI `onmc evolution --json` emits valid JSON with expected keys."""
    import os

    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(
        receipts_dir, "run-a.json",
        iterations=4, cost_usd=0.20,
        ended_at="2024-01-01T10:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-b.json",
        iterations=2, cost_usd=0.08,
        ended_at="2024-01-02T10:00:00+00:00",
    )
    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(
            app,
            ["evolution", "--json"],
            catch_exceptions=False,
        )
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
    data = json.loads(result.output)

    # Check required top-level keys
    required_keys = [
        "run_count",
        "insufficient_data",
        "cost_change_pct",
        "iterations_change_pct",
        "cost_unavailable",
        "verified_rate",
        "total_cost_usd",
        "total_tokens",
        "total_runs",
        "runs",
        "run_summary",
    ]
    for key in required_keys:
        assert key in data, f"Missing key in --json output: {key}"

    assert data["run_count"] == 2
    assert data["insufficient_data"] is False
    assert isinstance(data["runs"], list)
    assert len(data["runs"]) == 2


# ---------------------------------------------------------------------------
# Test 7 — empty directory → insufficient_data + friendly card render
# ---------------------------------------------------------------------------


def test_empty_directory_friendly_message(tmp_path: Path) -> None:
    """An empty receipts dir must not crash the renderer and must show hint."""
    from oh_no_my_claudecode.rendering.console import render_evolution_card

    empty_dir = tmp_path / ".agent-memory" / "receipts"
    empty_dir.mkdir(parents=True, exist_ok=True)

    report = compile_evolution(empty_dir)
    assert report.insufficient_data is True

    # render must not raise
    from io import StringIO

    from rich.console import Console
    buf = StringIO()
    con = Console(file=buf, no_color=True)

    # Patch console temporarily to capture output
    import oh_no_my_claudecode.rendering.console as _console_mod
    original_console = _console_mod.console
    _console_mod.console = con
    try:
        render_evolution_card(report)
    finally:
        _console_mod.console = original_console

    output = buf.getvalue()
    assert "not enough data" in output or "onmc loop" in output or "autopilot" in output


# ---------------------------------------------------------------------------
# Test 8 — non-existent directory → insufficient_data, no crash
# ---------------------------------------------------------------------------


def test_nonexistent_directory_returns_insufficient_data(tmp_path: Path) -> None:
    """compile_evolution must not crash when receipts_dir does not exist."""
    nonexistent = tmp_path / ".agent-memory" / "receipts"
    assert not nonexistent.exists()

    report = compile_evolution(nonexistent)

    assert report.insufficient_data is True
    assert report.run_count == 0
    assert report.cost_change_pct is None
    assert report.iterations_change_pct is None


# ---------------------------------------------------------------------------
# Test 9 — RunPoint fields are correct
# ---------------------------------------------------------------------------


def test_run_points_have_correct_fields(tmp_path: Path) -> None:
    """RunPoint objects must carry the right field values from receipts."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(
        receipts_dir, "run-x.json",
        goal="fix the login bug",
        agent="codex",
        verified=False,
        iterations=7,
        tokens_used=2500,
        cost_usd=0.18,
        wall_seconds=95.0,
        ended_at="2024-06-01T12:00:00+00:00",
    )
    _write_receipt(
        receipts_dir, "run-y.json",
        goal="add rate limiting",
        agent="claude",
        verified=True,
        iterations=2,
        tokens_used=800,
        cost_usd=0.05,
        wall_seconds=22.0,
        ended_at="2024-06-02T12:00:00+00:00",
    )

    report = compile_evolution(receipts_dir)

    assert len(report.runs) == 2
    first = report.runs[0]
    assert first.agent == "codex"
    assert first.verified is False
    assert first.iterations == 7
    assert first.tokens == 2500
    assert first.cost_usd == pytest.approx(0.18)
    assert "fix the login bug" in first.goal_short

    second = report.runs[1]
    assert second.agent == "claude"
    assert second.verified is True
    assert second.iterations == 2


# ---------------------------------------------------------------------------
# Test 10 — proxy label is honest
# ---------------------------------------------------------------------------


def test_iterations_proxy_label_is_honest(tmp_path: Path) -> None:
    """EvolutionReport must carry the honest proxy label."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-1.json", ended_at="2024-01-01T00:00:00+00:00")
    _write_receipt(receipts_dir, "run-2.json", ended_at="2024-01-02T00:00:00+00:00")

    report = compile_evolution(receipts_dir)
    assert "iterations" in report.iterations_proxy_label
    assert "converge" in report.iterations_proxy_label
