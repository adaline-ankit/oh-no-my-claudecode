"""Tests for onmc heatmap: build_heatmap, render_text, and the CLI command.

The grid core is exercised by injecting receipt dicts directly — no files, no
real clock (a fixed ``today`` is always passed in). The CLI test seeds
synthetic ``run-*.json`` receipts in a temp onmc project and asserts exit
codes and ``--json`` shape; it never asserts Rich/Typer ``--help`` text.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.heatmap.heatmap import (
    DEFAULT_WEEKS,
    build_heatmap,
    render_text,
)

_RUNNER = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receipt(
    *,
    verified: bool = True,
    ended_at: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    """Build a minimal receipt dict with just the fields heatmap reads."""
    return {
        "schema_version": "2",
        "agent": "claude",
        "model": "claude-opus-4-8",
        "verified": verified,
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
# build_heatmap: day bucketing
# ---------------------------------------------------------------------------


def test_buckets_runs_by_calendar_day() -> None:
    today = date(2026, 7, 5)  # Sunday
    receipts = [
        _receipt(ended_at="2026-07-05T09:00:00+00:00"),
        _receipt(ended_at="2026-07-05T18:00:00+00:00"),
        _receipt(ended_at="2026-07-04T09:00:00+00:00"),
    ]
    hm = build_heatmap(receipts, today=today, weeks=2)

    by_day = {cell.day: cell.count for cell in hm.days}
    assert by_day[date(2026, 7, 5)] == 2
    assert by_day[date(2026, 7, 4)] == 1
    assert hm.total_runs == 3


def test_verified_count_tracked_separately_from_total() -> None:
    today = date(2026, 7, 5)
    receipts = [
        _receipt(ended_at="2026-07-05T09:00:00+00:00", verified=True),
        _receipt(ended_at="2026-07-05T10:00:00+00:00", verified=False),
    ]
    hm = build_heatmap(receipts, today=today, weeks=1)
    cell = next(c for c in hm.days if c.day == date(2026, 7, 5))
    assert cell.count == 2
    assert cell.verified_count == 1


def test_unparseable_timestamp_excluded_and_noted() -> None:
    today = date(2026, 7, 5)
    receipts = [
        _receipt(ended_at=None),
        _receipt(ended_at="not-a-date"),
        _receipt(ended_at="2026-07-05T09:00:00+00:00"),
    ]
    hm = build_heatmap(receipts, today=today, weeks=1)
    assert hm.total_runs == 1
    assert any("excluded" in note for note in hm.notes)


def test_receipts_outside_window_are_dropped() -> None:
    today = date(2026, 7, 5)
    receipts = [
        _receipt(ended_at="2020-01-01T09:00:00+00:00"),  # far in the past
        _receipt(ended_at="2026-07-05T09:00:00+00:00"),
    ]
    hm = build_heatmap(receipts, today=today, weeks=1)
    assert hm.total_runs == 1


# ---------------------------------------------------------------------------
# grid dimensions
# ---------------------------------------------------------------------------


def test_grid_covers_exactly_weeks_times_seven_days() -> None:
    today = date(2026, 7, 5)
    hm = build_heatmap([], today=today, weeks=4)
    assert len(hm.days) == 4 * 7
    assert hm.days[-1].day == today
    assert hm.days[0].day <= today


def test_default_weeks_constant_used_when_unspecified() -> None:
    today = date(2026, 7, 5)
    hm = build_heatmap([], today=today)
    assert hm.weeks == DEFAULT_WEEKS
    assert len(hm.days) == DEFAULT_WEEKS * 7


def test_weeks_below_one_is_clamped() -> None:
    today = date(2026, 7, 5)
    hm = build_heatmap([], today=today, weeks=0)
    assert hm.weeks == 1
    assert len(hm.days) == 7


def test_days_ordered_oldest_to_newest() -> None:
    today = date(2026, 7, 5)
    hm = build_heatmap([], today=today, weeks=2)
    days = [c.day for c in hm.days]
    assert days == sorted(days)


# ---------------------------------------------------------------------------
# intensity levels / totals
# ---------------------------------------------------------------------------


def test_busiest_day_is_the_max_count_day() -> None:
    today = date(2026, 7, 5)
    receipts = (
        [_receipt(ended_at="2026-07-05T09:00:00+00:00") for _ in range(5)]
        + [_receipt(ended_at="2026-07-04T09:00:00+00:00") for _ in range(2)]
    )
    hm = build_heatmap(receipts, today=today, weeks=1)
    assert hm.busiest_day is not None
    assert hm.busiest_day.day == date(2026, 7, 5)
    assert hm.busiest_day.count == 5


def test_active_days_counts_only_nonzero_days() -> None:
    today = date(2026, 7, 5)
    receipts = [_receipt(ended_at="2026-07-05T09:00:00+00:00")]
    hm = build_heatmap(receipts, today=today, weeks=2)
    assert hm.active_days == 1


def test_current_streak_counts_consecutive_days_ending_today() -> None:
    today = date(2026, 7, 5)
    receipts = [
        _receipt(ended_at="2026-07-05T09:00:00+00:00"),
        _receipt(ended_at="2026-07-04T09:00:00+00:00"),
        _receipt(ended_at="2026-07-03T09:00:00+00:00"),
        # gap on 07-02
        _receipt(ended_at="2026-07-01T09:00:00+00:00"),
    ]
    hm = build_heatmap(receipts, today=today, weeks=2)
    assert hm.current_streak == 3


def test_current_streak_is_zero_when_today_is_idle() -> None:
    today = date(2026, 7, 5)
    receipts = [_receipt(ended_at="2026-07-03T09:00:00+00:00")]
    hm = build_heatmap(receipts, today=today, weeks=2)
    assert hm.current_streak == 0


# ---------------------------------------------------------------------------
# empty-state
# ---------------------------------------------------------------------------


def test_empty_receipts_gives_honest_zero_totals() -> None:
    today = date(2026, 7, 5)
    hm = build_heatmap([], today=today, weeks=4)
    assert hm.total_runs == 0
    assert hm.active_days == 0
    assert hm.busiest_day is None
    assert hm.current_streak == 0


def test_render_text_empty_state_message() -> None:
    today = date(2026, 7, 5)
    hm = build_heatmap([], today=today, weeks=4)
    text = render_text(hm)
    assert "No runs recorded yet" in text


def test_render_text_nonempty_includes_totals_and_legend() -> None:
    today = date(2026, 7, 5)
    receipts = [_receipt(ended_at="2026-07-05T09:00:00+00:00")]
    hm = build_heatmap(receipts, today=today, weeks=2)
    text = render_text(hm)
    assert "total runs: 1" in text
    assert "legend:" in text
    assert "busiest day:" in text
    assert "current streak:" in text


def test_render_text_is_deterministic() -> None:
    today = date(2026, 7, 5)
    receipts = [
        _receipt(ended_at="2026-07-05T09:00:00+00:00"),
        _receipt(ended_at="2026-07-01T09:00:00+00:00"),
    ]
    hm_a = build_heatmap(receipts, today=today, weeks=3)
    hm_b = build_heatmap(receipts, today=today, weeks=3)
    assert render_text(hm_a) == render_text(hm_b)


# ---------------------------------------------------------------------------
# CLI: onmc heatmap
# ---------------------------------------------------------------------------


def test_cli_json_shape_and_exit_code(tmp_path: Path) -> None:
    import os

    from oh_no_my_claudecode.cli import app

    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-a.json", ended_at="2026-07-05T09:00:00+00:00")
    _write_receipt(
        receipts_dir, "run-b.json", ended_at="2026-07-04T09:00:00+00:00", verified=False
    )
    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["heatmap", "--json"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert "days" in payload
    assert "totals" in payload
    assert payload["totals"]["total_runs"] == 2
    assert isinstance(payload["days"], list)


def test_cli_empty_state_exits_zero(tmp_path: Path) -> None:
    import os

    from oh_no_my_claudecode.cli import app

    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["heatmap"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 0, result.output
    assert "No runs recorded yet" in result.output


def test_cli_rejects_weeks_below_one(tmp_path: Path) -> None:
    import os

    from oh_no_my_claudecode.cli import app

    _make_onmc_project(tmp_path)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["heatmap", "--weeks", "0"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 1
