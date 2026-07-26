from __future__ import annotations

from oh_no_my_claudecode.experiment.claim import (
    ClaimReadinessDecision,
    build_claim_readiness,
)


def test_claim_readiness_combines_failed_benchmark_gates() -> None:
    report = build_claim_readiness(
        benchmark_plan={
            "claim_ready": False,
            "sample_size_ready": False,
            "budget_ready": True,
            "task_count": 28,
            "min_tasks_required": 50,
            "reasons": ["only 28 task(s); requires 50"],
        },
        coverage_gate={
            "claim_ready": False,
            "reasons": ["task kind 'refactor' has 1 task(s); requires 3"],
        },
        calibration_gate={
            "quality_claim_ready": False,
            "cost_claim_ready": False,
            "reasons": ["24 task(s) saturated across conditions"],
        },
    )

    assert report.decision is ClaimReadinessDecision.NOT_READY
    assert report.quality_claim_ready is False
    assert report.cost_claim_ready is False
    assert report.blocked_gates == (
        "benchmark_plan",
        "portfolio_coverage",
        "calibration",
    )
    assert "only 28 task(s); requires 50" in report.reasons
    assert "task kind 'refactor' has 1 task(s); requires 3" in report.reasons
    assert "24 task(s) saturated across conditions" in report.reasons
    assert any("Add at least 22" in action for action in report.next_actions)
    assert any("Rebalance the portfolio" in action for action in report.next_actions)


def test_claim_readiness_passes_only_when_all_gates_pass() -> None:
    report = build_claim_readiness(
        benchmark_plan={"claim_ready": True, "reasons": []},
        coverage_gate={"claim_ready": True, "reasons": []},
        calibration_gate={
            "quality_claim_ready": True,
            "cost_claim_ready": True,
            "reasons": [],
        },
    )

    assert report.decision is ClaimReadinessDecision.READY
    assert report.quality_claim_ready is True
    assert report.cost_claim_ready is True
    assert report.blocked_gates == ()
    assert report.reasons == ()
    assert report.next_actions == ()


def test_report_without_manifest_cannot_support_external_claim() -> None:
    report = build_claim_readiness(
        benchmark_plan={"claim_ready": True, "reasons": []},
        calibration_gate={
            "quality_claim_ready": True,
            "cost_claim_ready": True,
            "reasons": [],
        },
    )

    assert report.decision is ClaimReadinessDecision.NOT_READY
    assert report.quality_claim_ready is False
    assert report.blocked_gates == ("portfolio_coverage",)
    assert any("manifest missing" in reason for reason in report.reasons)
