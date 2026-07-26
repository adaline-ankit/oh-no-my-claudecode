from __future__ import annotations

from oh_no_my_claudecode.experiment.claim import (
    ClaimLanguageDecision,
    ClaimReadinessDecision,
    build_claim_readiness,
    gate_claim_language,
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


def test_claim_language_refuses_better_sota_when_gates_are_missing() -> None:
    readiness = build_claim_readiness(
        benchmark_plan={"claim_ready": False, "reasons": ["only 18 cells"]},
        coverage_gate={"claim_ready": False, "reasons": ["only 3 repo(s)"]},
        calibration_gate={
            "quality_claim_ready": False,
            "cost_claim_ready": False,
            "reasons": ["saturated benchmark"],
        },
    )

    gate = gate_claim_language(
        "ONMC is SOTA and makes Claude Code better and cheaper.",
        readiness,
        report_coverage={"claim_ready": False},
    )

    assert gate.decision is ClaimLanguageDecision.REFUSE
    assert gate.detected_claims == ("quality", "cost", "sota")
    assert any("quality improvement" in reason for reason in gate.reasons)
    assert any("cost claim" in reason for reason in gate.reasons)
    assert any("SOTA claim" in reason for reason in gate.reasons)
    assert any("coverage is incomplete" in reason for reason in gate.reasons)
    assert "external improvement claims are blocked" in gate.suggested_safe_claim


def test_claim_language_allows_strong_claim_only_after_readiness_and_coverage() -> None:
    readiness = build_claim_readiness(
        benchmark_plan={"claim_ready": True, "reasons": []},
        coverage_gate={"claim_ready": True, "reasons": []},
        calibration_gate={
            "quality_claim_ready": True,
            "cost_claim_ready": True,
            "reasons": [],
        },
    )

    gate = gate_claim_language(
        "ONMC improves pass rate and lowers cost under the attached benchmark.",
        readiness,
        report_coverage={"claim_ready": True},
    )

    assert gate.decision is ClaimLanguageDecision.ALLOW
    assert gate.detected_claims == ("quality", "cost")
    assert gate.reasons == ()


def test_claim_language_allows_plain_evidence_description_without_ready_benchmark() -> None:
    readiness = build_claim_readiness(
        benchmark_plan={"claim_ready": False, "reasons": ["too few tasks"]},
        coverage_gate={"claim_ready": False, "reasons": ["too few repos"]},
        calibration_gate={
            "quality_claim_ready": False,
            "cost_claim_ready": False,
            "reasons": [],
        },
    )

    gate = gate_claim_language("ONMC records a tamper-evident local receipt.", readiness)

    assert gate.decision is ClaimLanguageDecision.ALLOW
    assert gate.detected_claims == ()
    assert gate.reasons == ()
