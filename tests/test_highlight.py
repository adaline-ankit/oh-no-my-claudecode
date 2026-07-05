"""Tests for the ``onmc highlight`` reel engine.

Covers the pure :mod:`oh_no_my_claudecode.highlight.reel` module only —
no filesystem, no ledger, no CLI invocation. Each test injects receipts
and ``now`` directly into ``build_reel``.

Test matrix (>= 7 tests, as required)
--------------------------------------
1. biggest_win selected from seeded receipts by value score.
2. boss_kill is the longest-wall-time verified run.
3. longest_streak moment emitted when streak >= 2.
4. ranking is deterministic with injected ``now``.
5. ``--limit`` (limit param) caps the moment count.
6. ``--markdown`` renders a shareable Markdown block.
7. ``--json`` produces the expected JSON envelope shape.
8. empty receipts → graceful "no highlights yet" reel.
9. unverified receipts are excluded from all moments.
10. most_efficient moment picks the lowest-cost run.
11. fastest_merge picks the shortest-wall-time run.
12. since filter excludes older receipts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from oh_no_my_claudecode.highlight.reel import (
    Reel,
    build_reel,
    render_markdown,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)


def _receipt(
    goal: str,
    *,
    verified: bool = True,
    wall_seconds: float = 120.0,
    cost_usd: float | None = None,
    ended_at: str | None = None,
) -> dict[str, Any]:
    """Build a minimal receipt dict."""
    ts = ended_at or _NOW.isoformat()
    r: dict[str, Any] = {
        "goal": goal,
        "verified": verified,
        "wall_seconds": wall_seconds,
        "ended_at": ts,
    }
    if cost_usd is not None:
        r["cost_usd"] = cost_usd
    return r


def _day(offset: int) -> str:
    """ISO timestamp for _NOW + offset days."""
    return (_NOW + timedelta(days=offset)).isoformat()


# ---------------------------------------------------------------------------
# 1. biggest_win selected by value score
# ---------------------------------------------------------------------------


def test_biggest_win_selected_by_value_score() -> None:
    """The biggest_win moment should point at the run with the highest value score.

    Value score = wall_seconds + cost_usd * COST_WEIGHT * 3600.
    Here the expensive short run beats the long cheap one because cost bonus
    is significant, but the longest wall run should win if cost bonus is absent.
    """
    receipts = [
        _receipt("quick fix", wall_seconds=30.0, cost_usd=0.0001),
        _receipt("big refactor", wall_seconds=900.0),  # no cost — high wall
        _receipt("medium task", wall_seconds=200.0, cost_usd=0.01),
    ]
    reel = build_reel(receipts, now=_NOW)
    assert reel.total_verified == 3
    wins = [m for m in reel.moments if m.kind == "biggest_win"]
    assert len(wins) == 1
    # "big refactor" has the highest wall (900 s) and no cost bonus, so it wins
    # when cost_usd is None for it. Medium task: 200 + 0.01*0.3*3600 = 200 + 10.8 = 210.8
    # big refactor: 900 + 0 = 900  → big refactor wins
    goal_lower = wins[0].receipt_goal.lower()
    assert "Big" in wins[0].headline or "Refactor" in wins[0].headline or "big" in goal_lower


def test_biggest_win_with_cost_bonus() -> None:
    """When cost bonus is large, it can make a shorter run win biggest_win."""
    receipts = [
        _receipt("cheap long task", wall_seconds=500.0, cost_usd=0.0),
        # cost=1.0 → bonus = 1.0 * 0.3 * 3600 = 1080; total = 1080 + 100 = 1180 > 500
        _receipt("expensive short task", wall_seconds=100.0, cost_usd=1.0),
    ]
    reel = build_reel(receipts, now=_NOW)
    wins = [m for m in reel.moments if m.kind == "biggest_win"]
    assert len(wins) == 1
    assert "expensive" in wins[0].receipt_goal.lower() or "Expensive" in wins[0].headline


# ---------------------------------------------------------------------------
# 2. boss_kill from highest wall-time verified run
# ---------------------------------------------------------------------------


def test_boss_kill_is_longest_wall_time() -> None:
    """boss_kill should point at the verified run with the most wall time."""
    receipts = [
        _receipt("sprint task", wall_seconds=60.0),
        _receipt("marathon session", wall_seconds=3600.0),
        _receipt("medium work", wall_seconds=300.0),
    ]
    reel = build_reel(receipts, now=_NOW)
    boss = [m for m in reel.moments if m.kind == "boss_kill"]
    assert len(boss) == 1
    assert "marathon" in boss[0].receipt_goal.lower() or "3600" in boss[0].detail


# ---------------------------------------------------------------------------
# 3. longest_streak moment emitted for streak >= 2
# ---------------------------------------------------------------------------


def test_streak_moment_emitted_when_streak_gte_2() -> None:
    """A streak moment should appear when consecutive days >= 2."""
    receipts = [
        _receipt("day 0 task", ended_at=_day(0)),
        _receipt("day -1 task", ended_at=_day(-1)),
        _receipt("day -2 task", ended_at=_day(-2)),
    ]
    reel = build_reel(receipts, now=_NOW)
    streaks = [m for m in reel.moments if m.kind == "longest_streak"]
    assert len(streaks) == 1
    assert reel.streak_days >= 3
    assert str(reel.streak_days) in streaks[0].detail


def test_no_streak_moment_for_single_day() -> None:
    """A single-day run should produce no streak moment (streak < 2)."""
    receipts = [_receipt("only today", ended_at=_day(0))]
    reel = build_reel(receipts, now=_NOW)
    streaks = [m for m in reel.moments if m.kind == "longest_streak"]
    assert len(streaks) == 0


# ---------------------------------------------------------------------------
# 4. ranking is deterministic with injected now
# ---------------------------------------------------------------------------


def test_ranking_is_deterministic() -> None:
    """build_reel with the same inputs and now must return identical moments."""
    receipts = [
        _receipt("task a", wall_seconds=100.0),
        _receipt("task b", wall_seconds=500.0),
        _receipt("task c", wall_seconds=10.0, cost_usd=0.5),
    ]
    reel1 = build_reel(receipts, now=_NOW)
    reel2 = build_reel(receipts, now=_NOW)
    assert [m.kind for m in reel1.moments] == [m.kind for m in reel2.moments]
    assert [m.headline for m in reel1.moments] == [m.headline for m in reel2.moments]


# ---------------------------------------------------------------------------
# 5. limit caps the number of moments
# ---------------------------------------------------------------------------


def test_limit_caps_moments() -> None:
    """The limit parameter should cap the moment count."""
    receipts = [
        _receipt("task a", wall_seconds=100.0),
        _receipt("task b", wall_seconds=500.0, cost_usd=0.5),
        _receipt("task c", wall_seconds=10.0),
        # Spread across 3 days to generate a streak moment too.
        _receipt("task d", wall_seconds=200.0, ended_at=_day(-1)),
        _receipt("task e", wall_seconds=300.0, ended_at=_day(-2)),
    ]
    reel = build_reel(receipts, now=_NOW, limit=2)
    assert len(reel.moments) <= 2


def test_limit_default_is_5() -> None:
    """Default limit should be 5 even with many receipts."""
    receipts = [_receipt(f"task {i}", wall_seconds=float(i * 10)) for i in range(1, 20)]
    reel = build_reel(receipts, now=_NOW)
    assert len(reel.moments) <= 5


# ---------------------------------------------------------------------------
# 6. --markdown renders shareable Markdown block
# ---------------------------------------------------------------------------


def test_markdown_contains_key_sections() -> None:
    """render_markdown should include a heading, the moment headlines, and a footer."""
    receipts = [_receipt("important feature", wall_seconds=120.0)]
    reel = build_reel(receipts, now=_NOW)
    md = render_markdown(reel)
    assert "## onmc highlight reel" in md
    assert "verified" in md
    assert "onmc" in md


def test_markdown_empty_reel_is_graceful() -> None:
    """render_markdown on an empty reel should return a friendly message."""
    reel = Reel()
    md = render_markdown(reel)
    assert "no highlights yet" in md.lower() or "no highlights" in md.lower()
    assert "onmc" in md


# ---------------------------------------------------------------------------
# 7. --json produces expected envelope shape
# ---------------------------------------------------------------------------


def test_to_dict_json_envelope_shape() -> None:
    """reel.to_dict() should produce the expected JSON-safe structure."""
    receipts = [_receipt("my task", wall_seconds=60.0, cost_usd=0.05)]
    reel = build_reel(receipts, now=_NOW)
    d = reel.to_dict()
    assert "moments" in d
    assert "total_verified" in d
    assert "total_receipts" in d
    assert "streak_days" in d
    assert isinstance(d["moments"], list)
    if d["moments"]:
        m = d["moments"][0]
        assert "kind" in m
        assert "headline" in m
        assert "detail" in m
        assert "receipt_goal" in m


# ---------------------------------------------------------------------------
# 8. empty receipts → graceful empty reel
# ---------------------------------------------------------------------------


def test_empty_receipts_returns_empty_reel() -> None:
    """build_reel with no receipts should return an empty reel, never raise."""
    reel = build_reel([], now=_NOW)
    assert reel.moments == []
    assert reel.total_receipts == 0
    assert reel.total_verified == 0
    assert reel.streak_days == 0


# ---------------------------------------------------------------------------
# 9. unverified receipts are excluded
# ---------------------------------------------------------------------------


def test_unverified_receipts_excluded() -> None:
    """Unverified receipts must never contribute to any moment."""
    receipts = [
        _receipt("unverified run", verified=False, wall_seconds=9999.0),
        _receipt("verified run", verified=True, wall_seconds=10.0),
    ]
    reel = build_reel(receipts, now=_NOW)
    assert reel.total_verified == 1
    for m in reel.moments:
        assert "unverified" not in m.receipt_goal.lower()
        assert "9999" not in m.detail


# ---------------------------------------------------------------------------
# 10. most_efficient picks the lowest-cost run
# ---------------------------------------------------------------------------


def test_most_efficient_picks_lowest_cost() -> None:
    """most_efficient should pick the run with the lowest non-zero cost."""
    receipts = [
        _receipt("expensive run", wall_seconds=50.0, cost_usd=1.0),
        _receipt("cheap run", wall_seconds=50.0, cost_usd=0.001),
        _receipt("no cost run", wall_seconds=50.0),
    ]
    reel = build_reel(receipts, now=_NOW)
    efficient = [m for m in reel.moments if m.kind == "most_efficient"]
    assert len(efficient) == 1
    assert "cheap" in efficient[0].receipt_goal.lower() or "0.0010" in efficient[0].detail


# ---------------------------------------------------------------------------
# 11. fastest_merge picks shortest wall-time run
# ---------------------------------------------------------------------------


def test_fastest_merge_picks_shortest_wall_time() -> None:
    """fastest_merge should pick the verified run with the shortest wall time."""
    receipts = [
        _receipt("slow task", wall_seconds=600.0),
        _receipt("fast task", wall_seconds=5.0),
        _receipt("medium task", wall_seconds=100.0),
    ]
    reel = build_reel(receipts, now=_NOW)
    fastest = [m for m in reel.moments if m.kind == "fastest_merge"]
    assert len(fastest) == 1
    assert "fast" in fastest[0].receipt_goal.lower() or "5" in fastest[0].detail


# ---------------------------------------------------------------------------
# 12. since filter excludes older receipts
# ---------------------------------------------------------------------------


def test_since_filter_excludes_older_receipts() -> None:
    """Receipts older than the since cutoff should be excluded from the reel."""
    old_ts = (_NOW - timedelta(days=10)).isoformat()
    recent_ts = (_NOW - timedelta(hours=1)).isoformat()
    receipts = [
        _receipt("old run", wall_seconds=999.0, ended_at=old_ts),
        _receipt("recent run", wall_seconds=10.0, ended_at=recent_ts),
    ]
    cutoff = _NOW - timedelta(days=1)
    reel = build_reel(receipts, now=_NOW, since=cutoff)
    assert reel.total_verified == 1
    for m in reel.moments:
        assert "old" not in m.receipt_goal.lower()
