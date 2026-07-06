"""Tests for ``onmc achievements``: XP, streaks, levels, and badge unlocks.

Engine tests inject receipt dicts directly — no filesystem I/O, no real
loop/agent/clock. Numbers are deterministic.

CLI tests write fake receipts to a ``tmp_path``'s ``.agent-memory/receipts/``
and invoke the Typer command end-to-end via ``CliRunner``, mirroring the
pattern in ``tests/test_quest.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.achievements.achievements import (
    LEVEL_XP_FACTOR,
    MARATHONER_VERIFIED_THRESHOLD,
    PERFECT_STREAK_THRESHOLD,
    XP_ONE_SHOT_BONUS,
    XP_PER_VERIFIED,
    _level_from_xp,
    _total_xp_for_level,
    build_report,
    render_text,
)
from oh_no_my_claudecode.cli import app

_RUNNER = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receipt(
    *,
    verified: bool = True,
    iterations: int = 1,
    ended_at: str | None = None,
    started_at: str | None = None,
    goal: str = "refactor the parser",
) -> dict[str, Any]:
    return {
        "schema_version": "2",
        "goal": goal,
        "agent": "claude",
        "model": "claude-opus-4-8",
        "verified": verified,
        "cost_usd": 0.05,
        "wall_seconds": 42.0,
        "iterations": iterations,
        "ended_at": ended_at,
        "started_at": started_at,
    }


def _ts(day: int, hour: int = 0) -> str:
    return f"2026-07-{day:02d}T{hour:02d}:00:00+00:00"


# ---------------------------------------------------------------------------
# 1. Zero-state
# ---------------------------------------------------------------------------


def test_zero_state_no_receipts() -> None:
    report = build_report([])
    assert report.total_runs == 0
    assert report.verified_total == 0
    assert report.total_xp == 0
    assert report.level == 1
    assert report.current_streak == 0
    assert report.longest_streak == 0
    assert not report.unlocked_badges


def test_zero_state_render_text_is_honest() -> None:
    report = build_report([])
    text = render_text(report)
    assert "no verified runs yet" in text.lower()


def test_all_unverified_earns_no_xp() -> None:
    receipts = [_receipt(verified=False, ended_at=_ts(d)) for d in range(1, 4)]
    report = build_report(receipts)
    assert report.total_runs == 3
    assert report.verified_total == 0
    assert report.total_xp == 0
    assert report.current_streak == 0
    assert report.longest_streak == 0


# ---------------------------------------------------------------------------
# 2. XP accounting
# ---------------------------------------------------------------------------


def test_xp_verified_base_only() -> None:
    receipts = [_receipt(verified=True, iterations=3, ended_at=_ts(1))]
    report = build_report(receipts)
    assert report.total_xp == XP_PER_VERIFIED


def test_xp_one_shot_bonus() -> None:
    receipts = [_receipt(verified=True, iterations=1, ended_at=_ts(1))]
    report = build_report(receipts)
    assert report.total_xp == XP_PER_VERIFIED + XP_ONE_SHOT_BONUS


def test_xp_mixed_verified_and_unverified() -> None:
    receipts = [
        _receipt(verified=True, iterations=1, ended_at=_ts(1)),
        _receipt(verified=False, ended_at=_ts(2)),
        _receipt(verified=True, iterations=2, ended_at=_ts(3)),
    ]
    report = build_report(receipts)
    assert report.total_xp == (XP_PER_VERIFIED + XP_ONE_SHOT_BONUS) + XP_PER_VERIFIED
    assert report.verified_total == 2
    assert report.total_runs == 3


# ---------------------------------------------------------------------------
# 3. Level curve
# ---------------------------------------------------------------------------


def test_level_1_at_zero_xp() -> None:
    assert _level_from_xp(0) == 1


def test_level_1_below_threshold() -> None:
    assert _level_from_xp(LEVEL_XP_FACTOR - 1) == 1


def test_level_matches_threshold_roundtrip() -> None:
    for level in (2, 3, 5, 10, 20):
        xp = _total_xp_for_level(level)
        assert _level_from_xp(xp) == level
        assert _level_from_xp(xp - 1) == level - 1


# ---------------------------------------------------------------------------
# 4. Streak logic
# ---------------------------------------------------------------------------


def test_current_streak_all_verified() -> None:
    receipts = [_receipt(verified=True, ended_at=_ts(d)) for d in range(1, 5)]
    report = build_report(receipts)
    assert report.current_streak == 4
    assert report.longest_streak == 4


def test_current_streak_broken_by_trailing_failure() -> None:
    receipts = [
        _receipt(verified=True, ended_at=_ts(1)),
        _receipt(verified=True, ended_at=_ts(2)),
        _receipt(verified=False, ended_at=_ts(3)),
    ]
    report = build_report(receipts)
    assert report.current_streak == 0
    assert report.longest_streak == 2


def test_longest_streak_survives_after_current_breaks() -> None:
    receipts = [
        _receipt(verified=True, ended_at=_ts(1)),
        _receipt(verified=True, ended_at=_ts(2)),
        _receipt(verified=True, ended_at=_ts(3)),
        _receipt(verified=False, ended_at=_ts(4)),
        _receipt(verified=True, ended_at=_ts(5)),
    ]
    report = build_report(receipts)
    assert report.longest_streak == 3
    assert report.current_streak == 1


def test_streak_orders_by_ended_at_not_insertion_order() -> None:
    # Deliberately inserted out of chronological order.
    receipts = [
        _receipt(verified=True, ended_at=_ts(3)),
        _receipt(verified=False, ended_at=_ts(1)),
        _receipt(verified=True, ended_at=_ts(2)),
    ]
    report = build_report(receipts)
    # Chronological order: [F(1), T(2), T(3)] -> current streak = 2.
    assert report.current_streak == 2
    assert report.longest_streak == 2


# ---------------------------------------------------------------------------
# 5. Badge unlocks
# ---------------------------------------------------------------------------


def test_first_blood_unlocks_on_first_verified() -> None:
    receipts = [_receipt(verified=True, ended_at=_ts(1))]
    report = build_report(receipts)
    keys = {b.key for b in report.unlocked_badges}
    assert "first_blood" in keys


def test_one_shot_badge_requires_single_iteration() -> None:
    receipts = [_receipt(verified=True, iterations=3, ended_at=_ts(1))]
    report = build_report(receipts)
    keys = {b.key for b in report.unlocked_badges}
    assert "one_shot" not in keys

    receipts_one_shot = [_receipt(verified=True, iterations=1, ended_at=_ts(1))]
    report_one_shot = build_report(receipts_one_shot)
    keys_one_shot = {b.key for b in report_one_shot.unlocked_badges}
    assert "one_shot" in keys_one_shot


def test_perfect_streak_badge_at_threshold() -> None:
    receipts = [
        _receipt(verified=True, ended_at=_ts(d)) for d in range(1, PERFECT_STREAK_THRESHOLD + 1)
    ]
    report = build_report(receipts)
    keys = {b.key for b in report.unlocked_badges}
    assert "perfect_streak" in keys


def test_perfect_streak_badge_not_unlocked_below_threshold() -> None:
    receipts = [
        _receipt(verified=True, ended_at=_ts(d))
        for d in range(1, PERFECT_STREAK_THRESHOLD)  # one short
    ]
    report = build_report(receipts)
    keys = {b.key for b in report.unlocked_badges}
    assert "perfect_streak" not in keys


def test_marathoner_badge_at_threshold() -> None:
    receipts = [
        _receipt(verified=True, ended_at=_ts((d % 28) + 1))
        for d in range(MARATHONER_VERIFIED_THRESHOLD)
    ]
    report = build_report(receipts)
    keys = {b.key for b in report.unlocked_badges}
    assert "marathoner" in keys


def test_badge_unlocked_at_records_timestamp() -> None:
    receipts = [_receipt(verified=True, ended_at=_ts(5))]
    report = build_report(receipts)
    first_blood = next(b for b in report.badges if b.key == "first_blood")
    assert first_blood.unlocked
    assert first_blood.unlocked_at is not None
    assert "2026-07-05" in first_blood.unlocked_at


def test_all_badges_present_even_when_locked() -> None:
    report = build_report([])
    assert len(report.badges) >= 4
    assert all(not b.unlocked for b in report.badges)


# ---------------------------------------------------------------------------
# 6. CLI end-to-end
# ---------------------------------------------------------------------------


def _write_receipt(receipts_dir: Path, name: str, receipt: dict[str, Any]) -> None:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    (receipts_dir / f"run-{name}.json").write_text(json.dumps(receipt), encoding="utf-8")


def test_cli_json_shape_with_receipts(tmp_path: Path, monkeypatch: Any) -> None:
    (tmp_path / ".git").mkdir()
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "1", _receipt(verified=True, ended_at=_ts(1)))
    _write_receipt(receipts_dir, "2", _receipt(verified=True, iterations=1, ended_at=_ts(2)))
    monkeypatch.chdir(tmp_path)

    result = _RUNNER.invoke(app, ["achievements", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    for key in ("total_runs", "verified_total", "total_xp", "level", "current_streak", "badges"):
        assert key in data, f"missing key: {key}"
    assert data["verified_total"] == 2


def test_cli_human_readable_zero_state(tmp_path: Path, monkeypatch: Any) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    result = _RUNNER.invoke(app, ["achievements"])
    assert result.exit_code == 0, result.output
    assert "no verified runs yet" in result.output.lower()


def test_cli_human_readable_with_badges(tmp_path: Path, monkeypatch: Any) -> None:
    (tmp_path / ".git").mkdir()
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "1", _receipt(verified=True, ended_at=_ts(1)))
    monkeypatch.chdir(tmp_path)

    result = _RUNNER.invoke(app, ["achievements"])
    assert result.exit_code == 0, result.output
    assert "Level" in result.output
    assert "first_blood" in result.output
