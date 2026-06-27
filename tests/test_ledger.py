"""Tests for onmc ledger: summarize_receipts, roi, and the CLI group.

The aggregation core is exercised by injecting receipt dicts directly — no
files, no real loop/agent/clock.  All numbers are deterministic.  The CLI tests
seed synthetic ``run-*.json`` receipts in a temp onmc project and assert exit
codes and ``--json`` shape; they never assert Rich ``--help`` output.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.ledger.accounting import (
    LedgerSummary,
    load_receipts,
    roi,
    summarize_receipts,
)

_RUNNER = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receipt(
    *,
    agent: str = "claude",
    model: str | None = "claude-opus-4-8",
    verified: bool = True,
    cost_usd: float | None = 0.10,
    wall_seconds: float = 60.0,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> dict[str, Any]:
    """Build a minimal receipt dict matching schema_version "2" keys."""
    return {
        "schema_version": "2",
        "goal": "do a thing",
        "agent": agent,
        "model": model,
        "verified": verified,
        "stop_reason": "converged" if verified else "max-iterations",
        "iterations": 3,
        "tokens_used": 1000,
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


def _write_receipt(receipts_dir: Path, filename: str, **kw: Any) -> Path:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    dest = receipts_dir / filename
    dest.write_text(json.dumps(_receipt(**kw)), encoding="utf-8")
    return dest


def _make_onmc_project(tmp_path: Path) -> None:
    """Initialize a git repo + onmc project in tmp_path."""
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
    OnmcService(tmp_path).init_project()


# ---------------------------------------------------------------------------
# Test 1 — aggregation: totals, success_rate, by_model
# ---------------------------------------------------------------------------


def test_aggregates_totals_success_rate_and_by_model() -> None:
    """Seeded receipts aggregate to correct totals, success_rate, breakdown."""
    receipts = [
        _receipt(model="opus", agent="claude", verified=True, cost_usd=0.10, wall_seconds=60.0),
        _receipt(model="opus", agent="claude", verified=False, cost_usd=0.20, wall_seconds=120.0),
        _receipt(model="sonnet", agent="codex", verified=True, cost_usd=0.05, wall_seconds=30.0),
    ]

    summary = summarize_receipts(receipts, scope="project")

    assert summary.run_count == 3
    assert summary.success_count == 2
    assert summary.success_rate == pytest.approx(2 / 3, abs=1e-4)
    assert summary.total_cost_usd == pytest.approx(0.35, abs=1e-6)
    assert summary.total_wall_seconds == pytest.approx(210.0, abs=1e-6)
    assert summary.cost_unknown_count == 0
    assert summary.cost_label == "$0.3500"

    # by_model breakdown
    assert set(summary.by_model) == {"opus", "sonnet"}
    assert summary.by_model["opus"]["runs"] == 2
    assert summary.by_model["opus"]["cost_usd"] == pytest.approx(0.30, abs=1e-6)
    assert summary.by_model["opus"]["success_count"] == 1
    assert summary.by_model["sonnet"]["runs"] == 1
    assert summary.by_model["sonnet"]["success_count"] == 1

    # by_agent breakdown
    assert set(summary.by_agent) == {"claude", "codex"}
    assert summary.by_agent["claude"]["runs"] == 2
    assert summary.by_agent["codex"]["runs"] == 1


# ---------------------------------------------------------------------------
# Test 2 — empty input → zeroes, no division by zero
# ---------------------------------------------------------------------------


def test_empty_input_zeroes_no_div_by_zero() -> None:
    """No receipts → all-zero summary, success_rate 0.0, no ZeroDivisionError."""
    summary = summarize_receipts([], scope="today")

    assert isinstance(summary, LedgerSummary)
    assert summary.run_count == 0
    assert summary.success_count == 0
    assert summary.success_rate == 0.0  # not a crash
    assert summary.total_cost_usd == 0.0
    assert summary.total_wall_seconds == 0.0
    assert summary.by_model == {}
    assert summary.by_agent == {}
    assert summary.cost_label == "n/a"
    assert "No run receipts" in summary.note


# ---------------------------------------------------------------------------
# Test 3 — null cost handled honestly, never faked
# ---------------------------------------------------------------------------


def test_null_cost_handled_not_faked() -> None:
    """Receipts with cost_usd=None are excluded from the total, counted honestly."""
    receipts = [
        _receipt(cost_usd=None, wall_seconds=60.0),
        _receipt(cost_usd=None, wall_seconds=60.0),
    ]

    summary = summarize_receipts(receipts, scope="project")

    assert summary.run_count == 2
    assert summary.cost_unknown_count == 2
    assert summary.total_cost_usd == 0.0
    # Honest headline — never a fabricated dollar figure.
    assert summary.cost_label == "n/a"
    assert "n/a" in summary.note
    # Per-model bucket also flags unknown cost.
    bucket = next(iter(summary.by_model.values()))
    assert bucket["cost_unknown_count"] == 2
    assert bucket["cost_usd"] == 0.0


def test_partial_cost_is_flagged_in_note() -> None:
    """A mix of known and null cost → partial note, only known cost summed."""
    receipts = [
        _receipt(cost_usd=0.10),
        _receipt(cost_usd=None),
    ]

    summary = summarize_receipts(receipts, scope="project")

    assert summary.cost_unknown_count == 1
    assert summary.total_cost_usd == pytest.approx(0.10, abs=1e-6)
    assert "partial" in summary.note.lower()
    assert summary.cost_label == "$0.1000"


# ---------------------------------------------------------------------------
# Test 4 — roi is labelled est
# ---------------------------------------------------------------------------


def test_roi_is_labelled_est() -> None:
    """ROI is explicitly an estimate: estimated flag, 'est' label, assumption."""
    summary = summarize_receipts(
        [_receipt(wall_seconds=60.0), _receipt(wall_seconds=60.0)],
        scope="project",
    )

    estimate = roi(summary, assumed_human_minutes_per_run=30.0)

    assert estimate.estimated is True
    assert estimate.label == "est"
    assert "est" in estimate.assumption_note
    assert "Not a measurement" in estimate.assumption_note
    # 2 runs * 60s = 120s = 2.0 agent min; 2 runs * 30 = 60 human min.
    assert estimate.agent_wall_minutes == pytest.approx(2.0, abs=1e-6)
    assert estimate.estimated_human_minutes == pytest.approx(60.0, abs=1e-6)
    assert estimate.estimated_minutes_saved == pytest.approx(58.0, abs=1e-6)


def test_roi_reports_negative_saving_honestly() -> None:
    """When the agent is slower than the human baseline, saving goes negative."""
    summary = summarize_receipts(
        [_receipt(wall_seconds=3600.0)],  # 60 agent minutes for 1 run
        scope="project",
    )

    estimate = roi(summary, assumed_human_minutes_per_run=10.0)

    # 10 human min - 60 agent min = -50, not clamped to zero.
    assert estimate.estimated_minutes_saved == pytest.approx(-50.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Test 5 — deterministic
# ---------------------------------------------------------------------------


def test_summary_is_deterministic() -> None:
    """Same input → identical summary across repeated calls."""
    receipts = [
        _receipt(model="opus", verified=True, cost_usd=0.10),
        _receipt(model="sonnet", verified=False, cost_usd=0.20),
    ]

    a = summarize_receipts(receipts, scope="project")
    b = summarize_receipts(receipts, scope="project")

    assert a == b


# ---------------------------------------------------------------------------
# Test 6 — load_receipts today-scope filtering (impure boundary, injected now)
# ---------------------------------------------------------------------------


def test_load_receipts_today_scope_filters_by_date(tmp_path: Path) -> None:
    """`today` scope keeps only receipts dated on the injected current date."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-old.json", ended_at="2024-01-01T10:00:00+00:00")
    _write_receipt(receipts_dir, "run-new.json", ended_at="2024-06-15T10:00:00+00:00")

    now = datetime(2024, 6, 15, 23, 0, 0, tzinfo=UTC)
    today = load_receipts(tmp_path, scope="today", now=now)
    project = load_receipts(tmp_path, scope="project", now=now)

    assert len(today) == 1
    assert today[0]["ended_at"].startswith("2024-06-15")
    assert len(project) == 2


def test_load_receipts_missing_dir_returns_empty(tmp_path: Path) -> None:
    """No receipts directory → empty list (no crash)."""
    assert load_receipts(tmp_path, scope="project") == []


# ---------------------------------------------------------------------------
# Test 7 — CLI: exit codes and --json shape (never assert Rich --help)
# ---------------------------------------------------------------------------


def test_cli_ledger_project_exits_zero(tmp_path: Path) -> None:
    """`onmc ledger project` exits 0 with receipts present."""
    import os

    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-01.json", cost_usd=0.10)
    _write_receipt(receipts_dir, "run-02.json", cost_usd=None)
    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["ledger", "project"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 0


def test_cli_ledger_project_json_shape(tmp_path: Path) -> None:
    """`onmc ledger project --json` emits valid JSON with expected keys."""
    import os

    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-a.json", model="opus", cost_usd=0.20)
    _write_receipt(receipts_dir, "run-b.json", model="sonnet", cost_usd=0.05)
    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(
            app, ["ledger", "project", "--json"], catch_exceptions=False
        )
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
    data = json.loads(result.output)
    for key in (
        "scope",
        "run_count",
        "total_cost_usd",
        "cost_unknown_count",
        "total_wall_seconds",
        "success_count",
        "success_rate",
        "by_model",
        "by_agent",
        "note",
        "cost_label",
    ):
        assert key in data, f"missing key: {key}"
    assert data["scope"] == "project"
    assert data["run_count"] == 2
    assert data["total_cost_usd"] == pytest.approx(0.25, abs=1e-6)


def test_cli_ledger_roi_json_is_labelled_est(tmp_path: Path) -> None:
    """`onmc ledger roi --json` emits an estimate flagged est."""
    import os

    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-01.json", wall_seconds=60.0)
    _write_receipt(receipts_dir, "run-02.json", wall_seconds=60.0)
    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["ledger", "roi", "--json"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["estimated"] is True
    assert data["label"] == "est"
    assert "est" in data["assumption_note"]


def test_cli_ledger_today_exits_zero_when_empty(tmp_path: Path) -> None:
    """`onmc ledger today` exits 0 even with no receipts dated today."""
    import os

    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["ledger", "today"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
