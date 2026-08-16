"""Verified cascade: equal verified pass at lower spend; honest when cheap is useless."""

from __future__ import annotations

from oh_no_my_claudecode.experiment.cascade import run_cascade

TASKS = [f"t{i}" for i in range(10)]


def _cheap(task: str) -> bool:
    return int(task[1:]) < 6  # verified-solves 60%


def _expensive(task: str) -> bool:
    return int(task[1:]) < 9  # verified-solves 90%


def test_cascade_matches_direct_pass_rate_at_lower_spend() -> None:
    report = run_cascade(TASKS, _cheap, _expensive, cheap_cost=1.0, expensive_cost=10.0)
    assert report.cascade_pass_rate == report.direct_pass_rate == 0.9
    assert report.escalation_rate == 0.4
    # 6 cheap-only (6.0) + 4 escalated (4 * 11.0 = 44.0) = 50.0 vs direct 100.0
    assert report.spend_cascade == 50.0 and report.spend_direct == 100.0
    assert report.savings_pct == 50.0
    by_tier = {o.task_id: o.resolved_by for o in report.outcomes}
    assert by_tier["t0"] == "cheap" and by_tier["t8"] == "expensive"
    assert by_tier["t9"] == "unresolved"  # neither tier verified — reported, not hidden


def test_useless_cheap_tier_reports_negative_savings() -> None:
    report = run_cascade(TASKS, lambda t: False, _expensive, cheap_cost=1.0, expensive_cost=10.0)
    assert report.cascade_pass_rate == report.direct_pass_rate  # verification preserved
    assert report.escalation_rate == 1.0
    assert report.savings_pct < 0  # cascade made it MORE expensive; the number says so


def test_deterministic() -> None:
    a = run_cascade(TASKS, _cheap, _expensive, cheap_cost=1.0, expensive_cost=10.0)
    b = run_cascade(TASKS, _cheap, _expensive, cheap_cost=1.0, expensive_cost=10.0)
    assert a == b
