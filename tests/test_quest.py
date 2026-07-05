"""Tests for ``onmc quest``: XP curve, levels, achievements, bosses, loot.

All engine tests inject receipts + tasks directly — no filesystem I/O, no
real loop/agent/clock.  Numbers are deterministic via injected ``now``.

CLI tests use ``typer.testing.CliRunner`` to exercise the subcommands end-to-end
(without real receipts on disk) and verify ``--json`` output shape.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.quest.engine import (
    BASE_XP_PER_VERIFIED,
    MAX_WALL_SECONDS,
    SECONDS_PER_BONUS_XP,
    XP_LEVEL_FACTOR,
    _is_boss,
    _level_from_xp,
    _loot_name,
    _streak_days,
    _total_xp_for_level,
    _xp_for_receipt,
    _xp_to_next_level,
    compute_quests,
)

_NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
_RUNNER = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receipt(
    *,
    verified: bool = True,
    wall_seconds: float = 60.0,
    goal: str = "refactor the parser",
    cost_usd: float | None = 0.05,
    ended_at: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "2",
        "goal": goal,
        "agent": "claude",
        "model": "claude-opus-4-8",
        "verified": verified,
        "cost_usd": cost_usd,
        "wall_seconds": wall_seconds,
        "ended_at": ended_at,
        "started_at": started_at,
    }


def _task(
    text: str = "fix the login bug",
    source: str = "manual",
    score: float = 50.0,
) -> dict[str, Any]:
    return {"text": text, "source": source, "score": score}


# ---------------------------------------------------------------------------
# 1. XP per receipt
# ---------------------------------------------------------------------------


def test_xp_unverified_is_zero() -> None:
    r = _receipt(verified=False, wall_seconds=300.0)
    assert _xp_for_receipt(r) == 0


def test_xp_verified_base_only() -> None:
    r = _receipt(verified=True, wall_seconds=0.0)
    assert _xp_for_receipt(r) == BASE_XP_PER_VERIFIED


def test_xp_verified_with_wall() -> None:
    wall = 120.0
    r = _receipt(verified=True, wall_seconds=wall)
    expected = BASE_XP_PER_VERIFIED + int(wall / SECONDS_PER_BONUS_XP)
    assert _xp_for_receipt(r) == expected


def test_xp_wall_capped_at_max() -> None:
    r = _receipt(verified=True, wall_seconds=999_999.0)
    expected = BASE_XP_PER_VERIFIED + int(MAX_WALL_SECONDS / SECONDS_PER_BONUS_XP)
    assert _xp_for_receipt(r) == expected


# ---------------------------------------------------------------------------
# 2. Level curve — known vectors
# ---------------------------------------------------------------------------


def test_level_1_at_zero_xp() -> None:
    assert _level_from_xp(0) == 1


def test_level_1_at_small_xp() -> None:
    # Level 2 requires XP_LEVEL_FACTOR (100) total XP; below that stays at 1.
    assert _level_from_xp(XP_LEVEL_FACTOR - 1) == 1


def test_level_2_at_threshold() -> None:
    xp_for_2 = _total_xp_for_level(2)
    assert _level_from_xp(xp_for_2) == 2


def test_level_5_at_threshold() -> None:
    xp_for_5 = _total_xp_for_level(5)
    assert _level_from_xp(xp_for_5) == 5


def test_level_monotone_with_xp() -> None:
    levels = [_level_from_xp(xp) for xp in range(0, 10_000, 50)]
    assert levels == sorted(levels), "levels must be non-decreasing"


def test_xp_to_next_zero_at_exact_threshold() -> None:
    # At the exact XP for next level the remainder is 0.
    xp_for_3 = _total_xp_for_level(3)
    assert _xp_to_next_level(2, xp_for_3) == 0


# ---------------------------------------------------------------------------
# 3. Achievements unlock at thresholds
# ---------------------------------------------------------------------------


def test_first_blood_achievement_on_one_verified() -> None:
    log = compute_quests([_receipt(verified=True)], [], now=_NOW)
    keys = {a.key for a in log.achievements}
    assert "first_blood" in keys


def test_no_achievements_on_empty_receipts() -> None:
    log = compute_quests([], [], now=_NOW)
    assert log.achievements == []


def test_ten_runs_achievement() -> None:
    receipts = [_receipt() for _ in range(10)]
    log = compute_quests(receipts, [], now=_NOW)
    keys = {a.key for a in log.achievements}
    assert "ten_runs" in keys


def test_streak_achievement_3_days() -> None:
    today = _NOW.date()
    receipts = [
        _receipt(ended_at=f"{today.isoformat()}T10:00:00+00:00"),
        _receipt(
            ended_at=f"{(today - timedelta(days=1)).isoformat()}T10:00:00+00:00"
        ),
        _receipt(
            ended_at=f"{(today - timedelta(days=2)).isoformat()}T10:00:00+00:00"
        ),
    ]
    log = compute_quests(receipts, [], now=_NOW)
    keys = {a.key for a in log.achievements}
    assert "streak_3" in keys


def test_level_achievement_unlocked() -> None:
    # Build enough XP to pass level 5.
    xp_for_5 = _total_xp_for_level(5)
    # Create verified receipts to accumulate that XP.
    receipts_needed = xp_for_5 // BASE_XP_PER_VERIFIED + 1
    receipts = [_receipt(wall_seconds=0.0) for _ in range(receipts_needed)]
    log = compute_quests(receipts, [], now=_NOW)
    assert log.level >= 5
    keys = {a.key for a in log.achievements}
    assert "level_5" in keys


# ---------------------------------------------------------------------------
# 4. Boss fights flagged from high-risk tasks
# ---------------------------------------------------------------------------


def test_boss_keyword_detection() -> None:
    assert _is_boss("refactor the authentication system") is True
    assert _is_boss("fix a small typo") is False
    assert _is_boss("critical security migration") is True
    assert _is_boss("update the README") is False


def test_boss_task_appears_in_boss_fights() -> None:
    tasks = [
        _task(text="refactor entire auth module", score=80.0),
        _task(text="update changelog", score=50.0),
    ]
    log = compute_quests([], tasks, now=_NOW)
    assert len(log.boss_fights) == 1
    assert "refactor" in log.boss_fights[0].text


def test_boss_tasks_sorted_first_in_active_quests() -> None:
    tasks = [
        _task(text="update changelog", score=90.0),
        _task(text="critical security fix", score=30.0),
    ]
    log = compute_quests([], tasks, now=_NOW)
    # Boss should appear first even though it has a lower score.
    assert log.active_quests[0].is_boss is True


# ---------------------------------------------------------------------------
# 5. Loot from recent verified completions
# ---------------------------------------------------------------------------


def test_loot_from_verified_receipts() -> None:
    receipts = [
        _receipt(goal="deploy the feature", ended_at="2024-06-15T10:00:00+00:00"),
        _receipt(goal="fix login bug", ended_at="2024-06-14T10:00:00+00:00"),
        _receipt(verified=False, goal="attempted refactor"),
    ]
    log = compute_quests(receipts, [], now=_NOW)
    # Only verified receipts become loot.
    assert len(log.recent_loot) == 2
    assert all(lo.verified for lo in log.recent_loot)
    # Newest first.
    assert log.recent_loot[0].ended_at > log.recent_loot[1].ended_at


def test_loot_name_derived_from_goal() -> None:
    name = _loot_name("deploy the feature to production")
    # Should be title-cased words, at most 5.
    parts = name.split()
    assert 1 <= len(parts) <= 5
    assert all(p[0].isupper() for p in parts)


def test_loot_name_empty_goal() -> None:
    name = _loot_name("")
    assert name == "Mysterious Artefact"


# ---------------------------------------------------------------------------
# 6. Streak calculation
# ---------------------------------------------------------------------------


def test_streak_zero_with_no_verified_today() -> None:
    yesterday = _NOW - timedelta(days=1)
    receipts = [_receipt(ended_at=yesterday.isoformat())]
    streak = _streak_days(receipts, _NOW)
    assert streak == 0


def test_streak_one_with_verified_today_only() -> None:
    receipts = [_receipt(ended_at=_NOW.isoformat())]
    streak = _streak_days(receipts, _NOW)
    assert streak == 1


def test_streak_consecutive_days() -> None:
    today = _NOW.date()
    receipts = [
        _receipt(ended_at=f"{today.isoformat()}T08:00:00+00:00"),
        _receipt(ended_at=f"{(today - timedelta(days=1)).isoformat()}T08:00:00+00:00"),
        _receipt(ended_at=f"{(today - timedelta(days=2)).isoformat()}T08:00:00+00:00"),
    ]
    streak = _streak_days(receipts, _NOW)
    assert streak == 3


def test_streak_broken_by_gap() -> None:
    today = _NOW.date()
    # Gap on day-1; streak should only count today.
    receipts = [
        _receipt(ended_at=f"{today.isoformat()}T08:00:00+00:00"),
        _receipt(
            ended_at=f"{(today - timedelta(days=2)).isoformat()}T08:00:00+00:00"
        ),
    ]
    streak = _streak_days(receipts, _NOW)
    assert streak == 1


# ---------------------------------------------------------------------------
# 7. Determinism: injected now, stable output
# ---------------------------------------------------------------------------


def test_deterministic_with_injected_now() -> None:
    receipts = [_receipt(), _receipt(verified=False)]
    tasks = [_task()]
    log1 = compute_quests(receipts, tasks, now=_NOW)
    log2 = compute_quests(receipts, tasks, now=_NOW)
    assert log1.to_dict() == log2.to_dict()


# ---------------------------------------------------------------------------
# 8. Empty state — graceful level 1, 0 XP
# ---------------------------------------------------------------------------


def test_empty_state_level_1_zero_xp() -> None:
    log = compute_quests([], [], now=_NOW)
    assert log.level == 1
    assert log.total_xp == 0
    assert log.streak_days == 0
    assert log.active_quests == []
    assert log.boss_fights == []
    assert log.recent_loot == []
    assert log.achievements == []


# ---------------------------------------------------------------------------
# 9. CLI — --json output shape
# ---------------------------------------------------------------------------


def _make_cli() -> Any:
    """Build a minimal CLI app with the quest group registered."""
    import typer

    from oh_no_my_claudecode.quest.commands import register

    app = typer.Typer()
    register(app)
    return app


def test_cli_stats_json_shape(tmp_path: Any) -> None:
    app = _make_cli()
    result = _RUNNER.invoke(app, ["quest", "stats", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    for key in ("level", "total_xp", "xp_to_next", "streak_days", "total_runs", "verified_total"):
        assert key in data, f"missing key: {key}"


def test_cli_log_json_shape(tmp_path: Any) -> None:
    app = _make_cli()
    result = _RUNNER.invoke(app, ["quest", "log", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    for key in ("level", "total_xp", "active_quests", "boss_fights", "recent_loot", "achievements"):
        assert key in data, f"missing key: {key}"


def test_cli_achievements_json_shape(tmp_path: Any) -> None:
    app = _make_cli()
    result = _RUNNER.invoke(app, ["quest", "achievements", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "achievements" in data
    assert "count" in data


def test_cli_log_human_readable(tmp_path: Any) -> None:
    app = _make_cli()
    result = _RUNNER.invoke(app, ["quest", "log"])
    assert result.exit_code == 0, result.output
    assert "Level" in result.output


def test_cli_stats_human_readable(tmp_path: Any) -> None:
    app = _make_cli()
    result = _RUNNER.invoke(app, ["quest", "stats"])
    assert result.exit_code == 0, result.output
    assert "Level" in result.output


def test_cli_achievements_no_achievements(tmp_path: Any) -> None:
    app = _make_cli()
    result = _RUNNER.invoke(app, ["quest", "achievements"])
    assert result.exit_code == 0, result.output
    # Should say something helpful when there are no achievements.
    assert "No achievements" in result.output or "Unlocked" in result.output


# ---------------------------------------------------------------------------
# 10. QuestLog.to_dict round-trip
# ---------------------------------------------------------------------------


def test_to_dict_json_serialisable() -> None:
    receipts = [
        _receipt(ended_at="2024-06-15T10:00:00+00:00"),
        _receipt(verified=False),
    ]
    tasks = [_task(text="refactor security layer")]
    log = compute_quests(receipts, tasks, now=_NOW)
    raw = json.dumps(log.to_dict())
    restored = json.loads(raw)
    assert restored["level"] == log.level
    assert restored["total_xp"] == log.total_xp
    assert len(restored["recent_loot"]) == len(log.recent_loot)
    assert len(restored["boss_fights"]) == len(log.boss_fights)
