"""Tests for onmc standup: build_standup, parse_since, render_text, and the CLI.

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
from oh_no_my_claudecode.standup.standup import (
    DEFAULT_SINCE,
    build_standup,
    parse_since,
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
    iterations: int | None = 3,
    stop_reason: str | None = None,
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
        "stop_reason": stop_reason or ("converged" if verified else "max-iterations"),
        "iterations": iterations,
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
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    OnmcService(tmp_path).init_project()


# ---------------------------------------------------------------------------
# parse_since
# ---------------------------------------------------------------------------


def test_parse_since_relative_hours() -> None:
    from datetime import timedelta

    cutoff = parse_since("24h", _NOW)
    assert cutoff == _NOW - timedelta(hours=24)


def test_parse_since_relative_days() -> None:
    from datetime import timedelta

    cutoff = parse_since("7d", _NOW)
    assert cutoff == _NOW - timedelta(days=7)


def test_parse_since_iso_date() -> None:
    cutoff = parse_since("2026-07-01", _NOW)
    assert cutoff is not None
    assert cutoff.date().isoformat() == "2026-07-01"


def test_parse_since_invalid_returns_none() -> None:
    assert parse_since("not-a-time", _NOW) is None
    assert parse_since("", _NOW) is None


# ---------------------------------------------------------------------------
# build_standup — windowing
# ---------------------------------------------------------------------------


def test_windowing_excludes_runs_before_cutoff() -> None:
    inside = _receipt(goal="inside", ended_at="2026-07-06T11:00:00Z")
    outside = _receipt(goal="outside", ended_at="2026-07-04T00:00:00Z")
    report = build_standup([inside, outside], now=_NOW, since="24h")
    assert report.total_runs == 1
    assert report.top_goals[0].goal == "inside"


def test_windowing_boundary_is_inclusive() -> None:
    from datetime import timedelta

    boundary = (_NOW - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    receipt = _receipt(goal="on-boundary", ended_at=boundary)
    report = build_standup([receipt], now=_NOW, since="24h")
    assert report.total_runs == 1


def test_default_since_is_24h() -> None:
    assert DEFAULT_SINCE == "24h"
    report_default = build_standup([_receipt()], now=_NOW)
    report_explicit = build_standup([_receipt()], now=_NOW, since="24h")
    assert report_default.total_runs == report_explicit.total_runs


def test_undated_receipts_excluded_and_noted() -> None:
    dated = _receipt(goal="dated")
    undated = _receipt(goal="undated", started_at=None, ended_at=None)
    report = build_standup([dated, undated], now=_NOW, since="24h")
    assert report.total_runs == 1
    assert report.excluded_undated_count == 1
    assert any("timestamp" in note for note in report.notes)


def test_invalid_since_falls_back_to_default_with_note() -> None:
    report = build_standup([_receipt()], now=_NOW, since="not-a-time")
    assert report.since_label == DEFAULT_SINCE
    assert any("could not parse" in note for note in report.notes)


# ---------------------------------------------------------------------------
# build_standup — counts, rate, breakdowns
# ---------------------------------------------------------------------------


def test_counts_and_success_rate() -> None:
    receipts = [
        _receipt(goal="a", verified=True),
        _receipt(goal="b", verified=True),
        _receipt(goal="c", verified=False),
    ]
    report = build_standup(receipts, now=_NOW, since="24h")
    assert report.total_runs == 3
    assert report.verified_count == 2
    assert report.failed_count == 1
    assert report.success_rate == 2 / 3


def test_empty_state_success_rate_is_zero_not_divide_by_zero() -> None:
    report = build_standup([], now=_NOW, since="24h")
    assert report.total_runs == 0
    assert report.success_rate == 0.0
    assert "No agent runs" in render_text(report)


def test_cost_totals_and_unknown_count() -> None:
    receipts = [
        _receipt(goal="a", cost_usd=0.10),
        _receipt(goal="b", cost_usd=None),
        _receipt(goal="c", cost_usd=0.20),
    ]
    report = build_standup(receipts, now=_NOW, since="24h")
    assert report.total_cost_usd == pytest.approx(0.30, abs=1e-6)
    assert report.cost_unknown_count == 1


def test_model_breakdown_sorted_by_runs_desc_then_name() -> None:
    receipts = [
        _receipt(goal="a", model="sonnet"),
        _receipt(goal="b", model="opus"),
        _receipt(goal="c", model="opus"),
    ]
    report = build_standup(receipts, now=_NOW, since="24h")
    assert [m.model for m in report.by_model] == ["opus", "sonnet"]
    assert report.by_model[0].runs == 2
    assert report.by_model[1].runs == 1


def test_top_goals_sorted_and_limited() -> None:
    receipts = [_receipt(goal=f"goal-{i}") for i in range(7)]
    # give goal-0 three runs so it ranks first
    receipts += [_receipt(goal="goal-0"), _receipt(goal="goal-0")]
    report = build_standup(receipts, now=_NOW, since="24h")
    assert report.top_goals[0].goal == "goal-0"
    assert report.top_goals[0].runs == 3
    assert len(report.top_goals) <= 5


# ---------------------------------------------------------------------------
# build_standup — notable items
# ---------------------------------------------------------------------------


def test_notable_includes_failed_runs() -> None:
    receipts = [_receipt(goal="broke", verified=False, stop_reason="max-iterations")]
    report = build_standup(receipts, now=_NOW, since="24h")
    assert len(report.notable) == 1
    assert report.notable[0].reason == "failed"
    assert report.notable[0].stop_reason == "max-iterations"


def test_notable_includes_high_iteration_verified_runs() -> None:
    receipts = [_receipt(goal="hard", verified=True, iterations=8)]
    report = build_standup(receipts, now=_NOW, since="24h")
    assert len(report.notable) == 1
    assert report.notable[0].reason == "high-iteration"


def test_notable_excludes_clean_verified_runs() -> None:
    receipts = [_receipt(goal="clean", verified=True, iterations=2)]
    report = build_standup(receipts, now=_NOW, since="24h")
    assert report.notable == []
    assert "nothing stands out" in render_text(report)


def test_notable_list_is_capped() -> None:
    receipts = [_receipt(goal=f"fail-{i}", verified=False) for i in range(15)]
    report = build_standup(receipts, now=_NOW, since="24h")
    assert len(report.notable) == 10


# ---------------------------------------------------------------------------
# render_text
# ---------------------------------------------------------------------------


def test_render_text_includes_headline_numbers() -> None:
    receipts = [_receipt(goal="a", verified=True), _receipt(goal="b", verified=False)]
    report = build_standup(receipts, now=_NOW, since="24h")
    text = render_text(report)
    assert "2 runs" in text
    assert "1 verified" in text
    assert "1 failed" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_standup_exits_zero_with_no_receipts(tmp_path: Path) -> None:
    _make_onmc_project(tmp_path)
    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["standup"], catch_exceptions=False)
    finally:
        os.chdir(orig)
    assert result.exit_code == 0
    assert "No agent runs" in result.output


def test_cli_standup_json_shape(tmp_path: Path) -> None:
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    # Receipts dated relative to the real clock: this test invokes the actual
    # CLI (no frozen _NOW), so fixed dates age out of the window over time.
    from datetime import UTC, datetime, timedelta

    fresh = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_receipt(
        receipts_dir,
        "run-a.json",
        model="opus",
        cost_usd=0.20,
        started_at=fresh,
        ended_at=fresh,
    )
    _write_receipt(
        receipts_dir,
        "run-b.json",
        model="sonnet",
        cost_usd=0.05,
        verified=False,
        started_at=fresh,
        ended_at=fresh,
    )
    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(
            app, ["standup", "--since", "30d", "--json"], catch_exceptions=False
        )
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
    data = json.loads(result.output)
    for key in (
        "since",
        "now",
        "since_label",
        "total_runs",
        "verified_count",
        "failed_count",
        "success_rate",
        "total_cost_usd",
        "cost_unknown_count",
        "total_wall_seconds",
        "by_model",
        "top_goals",
        "notable",
        "excluded_undated_count",
        "notes",
    ):
        assert key in data, f"missing key: {key}"
    assert data["total_runs"] == 2
    assert data["verified_count"] == 1
    assert data["failed_count"] == 1
