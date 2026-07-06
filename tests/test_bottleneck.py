"""Tests for onmc bottleneck: build_bottleneck, render_text, and the CLI.

The pure core is exercised by injecting receipt dicts directly — no files, no
clock, no LLM. The CLI tests seed synthetic ``run-*.json`` receipts in a temp
onmc project and assert exit codes and ``--json`` shape; they never assert
Rich/Typer ``--help`` output.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.bottleneck.bottleneck import (
    DEFAULT_TOP,
    build_bottleneck,
    render_text,
)
from oh_no_my_claudecode.cli import app

_RUNNER = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receipt(
    *,
    goal: str = "do a thing",
    model: str | None = "claude-opus-4-8",
    verified: bool = True,
    wall_seconds: float | None = 60.0,
    iterations: int | None = 3,
) -> dict[str, Any]:
    """Build a minimal receipt dict matching schema_version "2" keys."""
    return {
        "schema_version": "2",
        "goal": goal,
        "agent": "claude",
        "model": model,
        "verified": verified,
        "stop_reason": "converged" if verified else "max-iterations",
        "iterations": iterations,
        "tokens_used": 1000,
        "cost_usd": 0.10,
        "wall_seconds": wall_seconds,
        "started_at": "2026-07-06T10:00:00Z",
        "ended_at": "2026-07-06T10:01:00Z",
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
# build_bottleneck — defaults + exclusions
# ---------------------------------------------------------------------------


def test_default_top_is_5() -> None:
    assert DEFAULT_TOP == 5


def test_top_less_than_one_is_clamped() -> None:
    report = build_bottleneck([_receipt()], top=0)
    assert len(report.by_goal) <= 1


def test_excludes_receipts_missing_wall_seconds() -> None:
    good = _receipt(goal="good")
    bad = _receipt(goal="bad", wall_seconds=None)
    report = build_bottleneck([good, bad])
    assert report.total_runs == 1
    assert report.excluded_count == 1
    assert any("wall_seconds" in note for note in report.notes)


def test_excludes_negative_wall_seconds() -> None:
    receipts = [_receipt(goal="a", wall_seconds=-5.0), _receipt(goal="b", wall_seconds=10.0)]
    report = build_bottleneck(receipts)
    assert report.total_runs == 1
    assert report.excluded_count == 1


def test_excludes_non_numeric_wall_seconds() -> None:
    bad = _receipt(goal="bad")
    bad["wall_seconds"] = "not-a-number"
    report = build_bottleneck([bad, _receipt(goal="ok")])
    assert report.total_runs == 1
    assert report.excluded_count == 1


# ---------------------------------------------------------------------------
# build_bottleneck — slowest goals
# ---------------------------------------------------------------------------


def test_by_goal_ranks_by_total_wall_desc() -> None:
    receipts = [
        _receipt(goal="fast-goal", wall_seconds=10.0),
        _receipt(goal="slow-goal", wall_seconds=100.0),
        _receipt(goal="slow-goal", wall_seconds=50.0),
    ]
    report = build_bottleneck(receipts)
    assert report.by_goal[0].goal == "slow-goal"
    assert report.by_goal[0].total_wall_seconds == pytest.approx(150.0)
    assert report.by_goal[0].runs == 2
    assert report.by_goal[0].avg_wall_seconds == pytest.approx(75.0)
    assert report.by_goal[1].goal == "fast-goal"


def test_by_goal_ties_break_by_name_ascending() -> None:
    receipts = [
        _receipt(goal="zeta", wall_seconds=10.0),
        _receipt(goal="alpha", wall_seconds=10.0),
    ]
    report = build_bottleneck(receipts)
    assert [g.goal for g in report.by_goal] == ["alpha", "zeta"]


def test_by_goal_respects_top_n() -> None:
    receipts = [_receipt(goal=f"goal-{i}", wall_seconds=float(i)) for i in range(10)]
    report = build_bottleneck(receipts, top=3)
    assert len(report.by_goal) == 3


# ---------------------------------------------------------------------------
# build_bottleneck — slowest models
# ---------------------------------------------------------------------------


def test_by_model_ranks_by_avg_wall_desc() -> None:
    receipts = [
        _receipt(goal="a", model="fast-model", wall_seconds=10.0, iterations=2),
        _receipt(goal="b", model="slow-model", wall_seconds=200.0, iterations=8),
    ]
    report = build_bottleneck(receipts)
    assert report.by_model[0].model == "slow-model"
    assert report.by_model[0].avg_wall_seconds == pytest.approx(200.0)
    assert report.by_model[0].avg_iterations == pytest.approx(8.0)


def test_by_model_ties_break_by_name_ascending() -> None:
    receipts = [
        _receipt(goal="a", model="zeta", wall_seconds=10.0),
        _receipt(goal="b", model="alpha", wall_seconds=10.0),
    ]
    report = build_bottleneck(receipts)
    assert [m.model for m in report.by_model] == ["alpha", "zeta"]


def test_by_model_avg_iterations_ignores_missing_iterations() -> None:
    receipts = [
        _receipt(goal="a", model="m", wall_seconds=10.0, iterations=None),
        _receipt(goal="b", model="m", wall_seconds=10.0, iterations=6),
    ]
    report = build_bottleneck(receipts)
    m = next(m for m in report.by_model if m.model == "m")
    assert m.avg_iterations == pytest.approx(6.0)


def test_by_model_avg_iterations_zero_when_all_missing() -> None:
    receipts = [_receipt(goal="a", model="m", wall_seconds=10.0, iterations=None)]
    report = build_bottleneck(receipts)
    m = next(m for m in report.by_model if m.model == "m")
    assert m.avg_iterations == 0.0


# ---------------------------------------------------------------------------
# build_bottleneck — outliers
# ---------------------------------------------------------------------------


def test_outlier_flagged_for_extreme_wall_time() -> None:
    receipts = [_receipt(goal=f"normal-{i}", wall_seconds=10.0) for i in range(9)]
    receipts.append(_receipt(goal="slow-outlier", wall_seconds=1000.0))
    report = build_bottleneck(receipts, top=5)
    outlier_goals = [o.goal for o in report.outliers]
    assert "slow-outlier" in outlier_goals


def test_outlier_flagged_for_extreme_iterations() -> None:
    receipts = [
        _receipt(goal=f"normal-{i}", wall_seconds=10.0, iterations=2) for i in range(9)
    ]
    receipts.append(_receipt(goal="iter-outlier", wall_seconds=10.0, iterations=50))
    report = build_bottleneck(receipts, top=5)
    outlier = next(o for o in report.outliers if o.goal == "iter-outlier")
    assert "iterations" in outlier.reason


def test_no_outliers_when_all_uniform() -> None:
    receipts = [_receipt(goal=f"g-{i}", wall_seconds=10.0, iterations=3) for i in range(5)]
    report = build_bottleneck(receipts)
    assert report.outliers == []


def test_outliers_sorted_by_wall_desc_then_goal() -> None:
    receipts = [_receipt(goal=f"base-{i}", wall_seconds=10.0) for i in range(9)]
    receipts.append(_receipt(goal="z-outlier", wall_seconds=500.0))
    receipts.append(_receipt(goal="a-outlier", wall_seconds=1000.0))
    report = build_bottleneck(receipts, top=5)
    assert [o.goal for o in report.outliers][:2] == ["a-outlier", "z-outlier"]


def test_outliers_respect_top_n() -> None:
    receipts = [_receipt(goal=f"base-{i}", wall_seconds=1.0) for i in range(9)]
    for i in range(5):
        receipts.append(_receipt(goal=f"outlier-{i}", wall_seconds=1000.0 + i))
    report = build_bottleneck(receipts, top=2)
    assert len(report.outliers) == 2


# ---------------------------------------------------------------------------
# build_bottleneck — time sink summary
# ---------------------------------------------------------------------------


def test_time_sink_summary_reports_percentage() -> None:
    receipts = [
        _receipt(goal="dominant", wall_seconds=90.0),
        _receipt(goal="minor", wall_seconds=10.0),
    ]
    report = build_bottleneck(receipts)
    assert any("dominant" in line and "90%" in line for line in report.time_sink_summary)


def test_time_sink_summary_empty_when_no_runs() -> None:
    report = build_bottleneck([])
    assert report.time_sink_summary == []


# ---------------------------------------------------------------------------
# Empty state / honesty
# ---------------------------------------------------------------------------


def test_empty_state_no_division_by_zero() -> None:
    report = build_bottleneck([])
    assert report.total_runs == 0
    assert report.total_wall_seconds == 0.0
    assert report.by_goal == []
    assert report.by_model == []
    assert report.outliers == []
    assert "No run receipts" in render_text(report)


def test_render_text_notes_excluded_receipts() -> None:
    receipts = [_receipt(goal="a"), _receipt(goal="b", wall_seconds=None)]
    report = build_bottleneck(receipts)
    text = render_text(report)
    assert "excluded" in text.lower() or "excluded" in " ".join(report.notes).lower()


def test_render_text_no_outliers_says_none() -> None:
    receipts = [_receipt(goal=f"g-{i}", wall_seconds=10.0) for i in range(5)]
    report = build_bottleneck(receipts)
    text = render_text(report)
    assert "Outlier runs: none." in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_bottleneck_exits_zero_with_no_receipts(tmp_path: Path) -> None:
    _make_onmc_project(tmp_path)
    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["bottleneck"], catch_exceptions=False)
    finally:
        os.chdir(orig)
    assert result.exit_code == 0
    assert "No run receipts" in result.output


def test_cli_bottleneck_json_shape(tmp_path: Path) -> None:
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-a.json", goal="alpha", wall_seconds=100.0)
    _write_receipt(receipts_dir, "run-b.json", goal="beta", wall_seconds=20.0)
    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(
            app, ["bottleneck", "--top", "5", "--json"], catch_exceptions=False
        )
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
    data = json.loads(result.output)
    for key in (
        "total_runs",
        "excluded_count",
        "total_wall_seconds",
        "by_goal",
        "by_model",
        "outliers",
        "time_sink_summary",
        "notes",
    ):
        assert key in data, f"missing key: {key}"
    assert data["total_runs"] == 2
    assert data["total_wall_seconds"] == pytest.approx(120.0)
