"""Tests for the ``nightshift`` feature: bounded planning + morning digest."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from oh_no_my_claudecode.nightshift import (
    DEFAULT_BUDGET,
    NightshiftPlan,
    NightshiftSummary,
    plan_nightshift,
    render_morning_digest,
    summarize_receipts,
)


def _console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, force_terminal=False, width=100), buf


# --------------------------------------------------------------------------- #
# plan_nightshift
# --------------------------------------------------------------------------- #


def test_plan_respects_budget_cap_and_orders_deterministically() -> None:
    goals = ["a", "b", "c", "d", "e"]
    plan = plan_nightshift(goals, budget=2)
    assert plan.scheduled_count == 2
    assert [u.goal for u in plan.units] == ["a", "b"]
    assert [u.index for u in plan.units] == [0, 1]
    assert plan.total_goals == 5
    assert plan.deferred_count == 3
    # Deterministic: same inputs → identical serialisation.
    assert plan_nightshift(goals, budget=2).to_dict() == plan.to_dict()


def test_plan_empty_backlog_is_safe() -> None:
    plan = plan_nightshift([], budget=5)
    assert isinstance(plan, NightshiftPlan)
    assert plan.is_empty
    assert plan.scheduled_count == 0
    assert plan.deferred_count == 0
    assert plan.total_goals == 0


def test_plan_dedupes_and_drops_blanks_preserving_order() -> None:
    plan = plan_nightshift(["fix bug", "  ", "fix bug", "add cache", ""], budget=10)
    assert [u.goal for u in plan.units] == ["fix bug", "add cache"]
    assert plan.total_goals == 2
    assert plan.deferred_count == 0


def test_plan_budget_zero_schedules_nothing_but_reports_backlog() -> None:
    plan = plan_nightshift(["a", "b"], budget=0)
    assert plan.scheduled_count == 0
    assert plan.total_goals == 2
    assert plan.deferred_count == 2


def test_plan_fewer_goals_than_budget_schedules_all() -> None:
    plan = plan_nightshift(["a", "b"], budget=DEFAULT_BUDGET)
    assert plan.scheduled_count == 2
    assert plan.deferred_count == 0


# --------------------------------------------------------------------------- #
# summarize_receipts
# --------------------------------------------------------------------------- #


def test_summarize_counts_verified_and_failed() -> None:
    receipts = [
        {"goal": "a", "verified": True, "pr_url": "https://x/1"},
        {"goal": "b", "verified": False},
        {"goal": "c", "verified": True, "pr": "https://x/3"},
    ]
    summary = summarize_receipts(receipts)
    assert summary.total == 3
    assert summary.verified == 2
    assert summary.failed == 1
    assert not summary.all_verified
    # pr / pr_url both normalise into pr_url; missing → None.
    assert summary.results[0]["pr_url"] == "https://x/1"
    assert summary.results[1]["pr_url"] is None
    assert summary.results[2]["pr_url"] == "https://x/3"


def test_summarize_empty_and_all_verified() -> None:
    assert summarize_receipts([]).all_verified is False
    good = summarize_receipts([{"goal": "a", "verified": True}])
    assert good.all_verified is True
    assert good.failed == 0


def test_summarize_missing_goal_renders_unknown() -> None:
    summary = summarize_receipts([{"verified": True}])
    assert summary.results[0]["goal"] == "(unknown)"


# --------------------------------------------------------------------------- #
# render_morning_digest
# --------------------------------------------------------------------------- #


def test_render_plan_digest_contains_expected_strings() -> None:
    plan = plan_nightshift(["fix flaky test", "add caching", "refactor"], budget=2)
    console, buf = _console()
    render_morning_digest(plan, console)
    out = buf.getvalue()
    assert "nightshift" in out
    assert "morning report" in out
    assert "fix flaky test" in out
    assert "add caching" in out
    # Deferred goal is beyond the budget cap, not listed as a unit.
    assert "refactor" not in out
    assert "deferred: 1" in out
    assert "No agents spawned" in out


def test_render_summary_digest_shows_verified_and_pr_links() -> None:
    summary = summarize_receipts(
        [
            {"goal": "ship auth", "verified": True, "pr_url": "https://pr/1"},
            {"goal": "flaky test", "verified": False},
        ]
    )
    console, buf = _console()
    render_morning_digest(summary, console)
    out = buf.getvalue()
    assert "verified: 1" in out
    assert "failed: 1" in out
    assert "ship auth" in out
    assert "https://pr/1" in out
    assert "did not verify" in out


def test_render_all_verified_summary() -> None:
    summary = summarize_receipts([{"goal": "a", "verified": True}])
    console, buf = _console()
    render_morning_digest(summary, console)
    assert "All units verified" in buf.getvalue()


def test_render_empty_summary_is_safe() -> None:
    console, buf = _console()
    render_morning_digest(NightshiftSummary(), console)
    assert "Nothing ran overnight" in buf.getvalue()
