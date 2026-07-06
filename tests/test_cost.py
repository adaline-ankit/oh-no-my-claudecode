"""Tests for onmc cost: build_cost_report, render_text, and the CLI.

The pure core is exercised by injecting receipt dicts directly with a fixed
``now`` — no files, no clock, no LLM. The CLI tests seed synthetic
``run-*.json`` receipts in a temp onmc project and assert exit codes and
``--json`` shape; they never assert Rich/Typer ``--help`` output.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.cost.cost import (
    DEFAULT_DAYS,
    build_cost_report,
    render_text,
)

_RUNNER = CliRunner()
_NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receipt(
    *,
    goal: str = "do a thing",
    model: str | None = "claude-opus-4-8",
    verified: bool = True,
    cost_usd: float | None = 0.10,
    wall_seconds: float = 60.0,
    started_at: str | None = "2026-07-06T10:00:00Z",
    ended_at: str | None = "2026-07-06T10:01:00Z",
) -> dict[str, Any]:
    """Build a minimal receipt dict matching schema_version "2" keys."""
    return {
        "schema_version": "2",
        "goal": goal,
        "agent": "claude",
        "model": model,
        "verified": verified,
        "stop_reason": "converged" if verified else "max-iterations",
        "iterations": 3,
        "tokens_used": 1000,
        "cost_usd": cost_usd,
        "wall_seconds": wall_seconds,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def _write_receipt(receipts_dir: Path, filename: str, **kw: Any) -> Path:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    dest = receipts_dir / filename
    dest.write_text(json.dumps(_receipt(**kw)), encoding="utf-8")
    return dest


def _make_onmc_project(tmp_path: Path) -> None:
    """Initialize a git repo + onmc project in tmp_path."""
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
# build_cost_report — windowing + defaults
# ---------------------------------------------------------------------------


def test_default_days_is_30() -> None:
    assert DEFAULT_DAYS == 30
    report = build_cost_report([_receipt()], now=_NOW)
    assert report.days == 30


def test_windowing_excludes_runs_before_cutoff() -> None:
    inside = _receipt(goal="inside", ended_at="2026-07-05T00:00:00Z")
    outside = _receipt(goal="outside", ended_at="2026-06-01T00:00:00Z")
    report = build_cost_report([inside, outside], now=_NOW, days=30)
    assert report.total_runs == 1


def test_days_less_than_one_is_clamped() -> None:
    report = build_cost_report([_receipt()], now=_NOW, days=0)
    assert report.days == 1


def test_undated_receipts_excluded_and_noted() -> None:
    dated = _receipt(goal="dated")
    undated = _receipt(goal="undated", started_at=None, ended_at=None)
    report = build_cost_report([dated, undated], now=_NOW, days=30)
    assert report.total_runs == 1
    assert report.excluded_undated_count == 1
    assert any("timestamp" in note for note in report.notes)


# ---------------------------------------------------------------------------
# build_cost_report — totals, by-model, by-day
# ---------------------------------------------------------------------------


def test_total_spend_sums_known_costs_only() -> None:
    receipts = [
        _receipt(goal="a", cost_usd=0.10),
        _receipt(goal="b", cost_usd=None),
        _receipt(goal="c", cost_usd=0.25),
    ]
    report = build_cost_report(receipts, now=_NOW, days=30)
    assert report.total_cost_usd == pytest.approx(0.35, abs=1e-6)
    assert report.cost_unknown_count == 1
    assert report.total_runs == 3


def test_by_model_sorted_by_cost_desc_then_name() -> None:
    receipts = [
        _receipt(goal="a", model="sonnet", cost_usd=0.05),
        _receipt(goal="b", model="opus", cost_usd=0.40),
        _receipt(goal="c", model="haiku", cost_usd=0.01),
    ]
    report = build_cost_report(receipts, now=_NOW, days=30)
    assert [m.model for m in report.by_model] == ["opus", "sonnet", "haiku"]
    assert report.by_model[0].cost_usd == pytest.approx(0.40, abs=1e-6)


def test_by_model_ties_break_by_name_ascending() -> None:
    receipts = [
        _receipt(goal="a", model="zeta", cost_usd=0.10),
        _receipt(goal="b", model="alpha", cost_usd=0.10),
    ]
    report = build_cost_report(receipts, now=_NOW, days=30)
    assert [m.model for m in report.by_model] == ["alpha", "zeta"]


def test_by_day_covers_full_window_zero_filled() -> None:
    receipts = [_receipt(goal="only-one", ended_at="2026-07-06T10:00:00Z")]
    report = build_cost_report(receipts, now=_NOW, days=3)
    # window is 3 days -> 4 zero-filled buckets (since..now inclusive)
    assert len(report.by_day) == 4
    non_zero = [d for d in report.by_day if d.runs > 0]
    assert len(non_zero) == 1
    assert non_zero[0].day == "2026-07-06"
    assert non_zero[0].cost_usd == pytest.approx(0.10, abs=1e-6)


def test_by_day_chronological_order() -> None:
    report = build_cost_report([_receipt()], now=_NOW, days=5)
    days = [d.day for d in report.by_day]
    assert days == sorted(days)


def test_by_day_aggregates_multiple_runs_same_day() -> None:
    receipts = [
        _receipt(goal="a", ended_at="2026-07-06T09:00:00Z", cost_usd=0.10),
        _receipt(goal="b", ended_at="2026-07-06T10:00:00Z", cost_usd=0.20),
    ]
    report = build_cost_report(receipts, now=_NOW, days=3)
    today = next(d for d in report.by_day if d.day == "2026-07-06")
    assert today.runs == 2
    assert today.cost_usd == pytest.approx(0.30, abs=1e-6)


# ---------------------------------------------------------------------------
# build_cost_report — cost per verified run
# ---------------------------------------------------------------------------


def test_cost_per_verified_run() -> None:
    receipts = [
        _receipt(goal="a", verified=True, cost_usd=0.20),
        _receipt(goal="b", verified=True, cost_usd=0.40),
        _receipt(goal="c", verified=False, cost_usd=0.10),
    ]
    report = build_cost_report(receipts, now=_NOW, days=30)
    # total known cost 0.70 / 2 verified runs
    assert report.cost_per_verified_run_usd == pytest.approx(0.35, abs=1e-6)


def test_cost_per_verified_run_none_when_no_verified_runs() -> None:
    receipts = [_receipt(goal="a", verified=False, cost_usd=0.10)]
    report = build_cost_report(receipts, now=_NOW, days=30)
    assert report.cost_per_verified_run_usd is None


# ---------------------------------------------------------------------------
# build_cost_report — forecast
# ---------------------------------------------------------------------------


def test_forecast_math_linear_projection() -> None:
    # 3 known-cost runs totalling $0.30 inside a 30-day window whose elapsed
    # portion is the full 30 days -> daily avg = 0.30 / 30, monthly = *30.
    receipts = [_receipt(goal="a", cost_usd=0.10, ended_at="2026-06-07T00:00:00Z")]
    report = build_cost_report(receipts, now=_NOW, days=30)
    assert report.forecast_daily_avg_usd is not None
    expected_daily = report.total_cost_usd / 30.0
    assert report.forecast_daily_avg_usd == pytest.approx(expected_daily, abs=1e-4)
    assert report.forecast_monthly_usd == pytest.approx(expected_daily * 30, abs=1e-2)


def test_forecast_none_when_all_costs_unknown() -> None:
    receipts = [_receipt(goal="a", cost_usd=None)]
    report = build_cost_report(receipts, now=_NOW, days=30)
    assert report.forecast_daily_avg_usd is None
    assert report.forecast_monthly_usd is None


def test_forecast_none_on_empty_input() -> None:
    report = build_cost_report([], now=_NOW, days=30)
    assert report.forecast_daily_avg_usd is None
    assert report.forecast_monthly_usd is None


# ---------------------------------------------------------------------------
# Empty state / honesty
# ---------------------------------------------------------------------------


def test_empty_state_no_division_by_zero() -> None:
    report = build_cost_report([], now=_NOW, days=30)
    assert report.total_runs == 0
    assert report.total_cost_usd == 0.0
    assert report.cost_per_verified_run_usd is None
    assert "No agent runs" in render_text(report)


def test_render_text_notes_partial_unknown_cost() -> None:
    receipts = [
        _receipt(goal="a", cost_usd=0.10),
        _receipt(goal="b", cost_usd=None),
    ]
    report = build_cost_report(receipts, now=_NOW, days=30)
    assert any("partial" in note for note in report.notes)
    text = render_text(report)
    assert "unknown cost" in text


def test_render_text_all_unknown_cost_is_honest_na() -> None:
    receipts = [_receipt(goal="a", cost_usd=None)]
    report = build_cost_report(receipts, now=_NOW, days=30)
    text = render_text(report)
    assert "n/a" in text
    assert "Cost is n/a" in "\n".join(report.notes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_cost_exits_zero_with_no_receipts(tmp_path: Path) -> None:
    _make_onmc_project(tmp_path)
    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["cost"], catch_exceptions=False)
    finally:
        os.chdir(orig)
    assert result.exit_code == 0
    assert "No agent runs" in result.output


def test_cli_cost_json_shape(tmp_path: Path) -> None:
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-a.json", model="opus", cost_usd=0.20)
    _write_receipt(receipts_dir, "run-b.json", model="sonnet", cost_usd=0.05, verified=False)
    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(
            app, ["cost", "--days", "30", "--json"], catch_exceptions=False
        )
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
    data = json.loads(result.output)
    for key in (
        "since",
        "now",
        "days",
        "total_runs",
        "total_cost_usd",
        "cost_unknown_count",
        "verified_count",
        "cost_per_verified_run_usd",
        "by_model",
        "by_day",
        "forecast_daily_avg_usd",
        "forecast_monthly_usd",
        "excluded_undated_count",
        "notes",
    ):
        assert key in data, f"missing key: {key}"
    assert data["total_runs"] == 2
    assert data["cost_unknown_count"] == 0
    assert data["total_cost_usd"] == pytest.approx(0.25, abs=1e-6)
