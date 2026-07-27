"""Contract tests for the advisory trajectory-aware model router."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oh_no_my_claudecode.autoroute.policy import (
    RoutingAction,
    ShadowRoutingPolicy,
)
from oh_no_my_claudecode.autoroute.trajectory import (
    TaskKind,
    TrajectoryObservation,
    VerifierState,
)
from oh_no_my_claudecode.experiment.routing import (
    RoutingArm,
    RoutingTrial,
    evaluate_routing,
)
from oh_no_my_claudecode.loop.engine import run_loop
from oh_no_my_claudecode.loop.models import (
    AgentRunResult,
    LoopConfig,
    LoopSpec,
    VerifyOutcome,
)
from oh_no_my_claudecode.storage import SQLiteStorage


def _observation(**overrides: object) -> TrajectoryObservation:
    values: dict[str, object] = {
        "task_kind": TaskKind.LOCAL_EDIT,
        "repository_files": 120,
        "files_explored": ("src/widget.py",),
        "dependency_breadth": 0,
        "test_failures": 0,
        "no_progress_events": 0,
        "uncertainty": 0.1,
        "tool_errors": 0,
        "verifier_state": VerifierState.PASSED,
        "tokens_used": 800,
        "token_budget": 10_000,
        "cost_usd": 0.02,
        "cost_budget_usd": 1.0,
        "cost_is_reliable": True,
        "prior_escalations": 0,
    }
    values.update(overrides)
    return TrajectoryObservation(**values)  # type: ignore[arg-type]


def test_local_verified_typo_stays_on_cheap_model_in_shadow() -> None:
    decision = ShadowRoutingPolicy(
        cheap_model="claude-haiku",
        strong_model="claude-sonnet",
    ).advise(_observation())

    assert decision.action is RoutingAction.CONTINUE_CHEAP
    assert decision.recommended_model == "claude-haiku"
    assert decision.advisory_only is True
    assert decision.enforced is False
    assert decision.preserve_worktree is True
    assert decision.preserve_context is True


def test_cross_module_repeated_failures_recommend_one_escalation() -> None:
    policy = ShadowRoutingPolicy(
        cheap_model="claude-haiku",
        strong_model="claude-sonnet",
    )
    observation = _observation(
        task_kind=TaskKind.CROSS_MODULE,
        files_explored=("src/api.py", "src/models.py", "src/db.py", "tests/test_api.py"),
        dependency_breadth=4,
        test_failures=3,
        no_progress_events=2,
        uncertainty=0.8,
        verifier_state=VerifierState.FAILED,
    )

    decision = policy.advise(observation)
    assert decision.action is RoutingAction.RECOMMEND_ESCALATION
    assert decision.recommended_model == "claude-sonnet"
    assert decision.enforced is False
    assert "repeated test failures" in decision.reasons

    already_escalated = policy.advise(
        _observation(
            task_kind=TaskKind.CROSS_MODULE,
            dependency_breadth=5,
            test_failures=4,
            no_progress_events=3,
            verifier_state=VerifierState.FAILED,
            prior_escalations=1,
        )
    )
    assert already_escalated.action is RoutingAction.HOLD_TIER
    assert already_escalated.recommended_model == "claude-sonnet"
    assert "escalation cap reached" in already_escalated.reasons


def test_verified_episode_after_advisory_escalation_holds_strong_tier() -> None:
    decision = ShadowRoutingPolicy("cheap", "strong").advise(
        _observation(prior_escalations=1, verifier_state=VerifierState.PASSED)
    )

    assert decision.action is RoutingAction.HOLD_TIER
    assert decision.current_model == "strong"
    assert decision.recommended_model == "strong"


@pytest.mark.parametrize(
    ("cost_usd", "cost_is_reliable"),
    [(None, False), (0.25, False)],
)
def test_missing_or_unreliable_cost_disables_cost_learning(
    cost_usd: float | None,
    cost_is_reliable: bool,
) -> None:
    observation = _observation(cost_usd=cost_usd, cost_is_reliable=cost_is_reliable)
    decision = ShadowRoutingPolicy("cheap", "strong").advise(observation)

    assert observation.cost_learning_eligible is False
    assert decision.cost_learning_eligible is False
    assert any("cost learning disabled" in reason for reason in decision.telemetry_status)


def test_missing_token_telemetry_is_visible_in_advice() -> None:
    decision = ShadowRoutingPolicy("cheap", "strong").advise(
        _observation(tokens_used=None)
    )

    assert "token telemetry unavailable" in decision.telemetry_status


def test_two_tier_policy_rejects_more_than_one_escalation() -> None:
    with pytest.raises(ValueError, match="exactly one escalation"):
        ShadowRoutingPolicy("cheap", "strong", max_escalations=2)


def test_exhausted_budget_holds_current_tier() -> None:
    decision = ShadowRoutingPolicy("cheap", "strong").advise(
        _observation(
            task_kind=TaskKind.CROSS_MODULE,
            test_failures=4,
            no_progress_events=3,
            verifier_state=VerifierState.FAILED,
            tokens_used=10_000,
            token_budget=10_000,
        )
    )

    assert decision.action is RoutingAction.HOLD_TIER
    assert "token budget exhausted" in decision.reasons


def test_report_computes_regret_and_non_inferiority_against_baselines() -> None:
    trials = [
        RoutingTrial("task-a", RoutingArm.ALWAYS_CHEAP, False, 0.10),
        RoutingTrial("task-a", RoutingArm.STATIC_PROMPT, True, 0.40),
        RoutingTrial("task-a", RoutingArm.ALWAYS_STRONG, True, 0.50),
        RoutingTrial("task-a", RoutingArm.TRAJECTORY, True, 0.30),
        RoutingTrial("task-b", RoutingArm.ALWAYS_CHEAP, True, 0.10),
        RoutingTrial("task-b", RoutingArm.STATIC_PROMPT, True, 0.25),
        RoutingTrial("task-b", RoutingArm.ALWAYS_STRONG, True, 0.50),
        RoutingTrial("task-b", RoutingArm.TRAJECTORY, True, 0.20),
    ]

    report = evaluate_routing(trials, non_inferiority_margin=0.02)

    assert report.trajectory_quality == 1.0
    assert report.always_strong_quality == 1.0
    assert report.quality_delta == 0.0
    assert report.quality_non_inferior is True
    assert report.cost_reduction_vs_always_strong == pytest.approx(0.5)
    assert report.router_quality_regret == 0.0
    assert report.router_cost_regret_usd == pytest.approx(0.05)
    assert report.observed_gate_met is True
    assert report.enforcement_enabled is False
    assert report.claim_ready is False


def test_incomplete_cost_coverage_blocks_cost_gate_and_regret() -> None:
    trials = [
        RoutingTrial("task-a", RoutingArm.ALWAYS_CHEAP, True, 0.10),
        RoutingTrial("task-a", RoutingArm.STATIC_PROMPT, True, 0.20),
        RoutingTrial("task-a", RoutingArm.ALWAYS_STRONG, True, 0.50),
        RoutingTrial("task-a", RoutingArm.TRAJECTORY, True, None),
    ]

    report = evaluate_routing(trials)

    assert report.cost_coverage == 0.0
    assert report.cost_reduction_vs_always_strong is None
    assert report.router_cost_regret_usd is None
    assert report.cost_gate_met is False
    assert report.observed_gate_met is False
    assert "complete reliable paired cost coverage required" in report.gate_reasons


def test_quality_regret_records_router_miss_against_oracle() -> None:
    trials = [
        RoutingTrial("task-a", RoutingArm.ALWAYS_CHEAP, False, 0.10),
        RoutingTrial("task-a", RoutingArm.STATIC_PROMPT, False, 0.20),
        RoutingTrial("task-a", RoutingArm.ALWAYS_STRONG, True, 0.50),
        RoutingTrial("task-a", RoutingArm.TRAJECTORY, False, 0.25),
    ]

    report = evaluate_routing(trials)

    assert report.oracle_quality == 1.0
    assert report.router_quality_regret == 1.0
    assert report.quality_non_inferior is False
    assert report.observed_gate_met is False


def test_frozen_routing_fixture_matches_shadow_policy() -> None:
    dataset = json.loads(
        (Path(__file__).parents[1] / "datasets" / "routing_v1.json").read_text(
            encoding="utf-8"
        )
    )
    policy = ShadowRoutingPolicy("cheap", "strong")

    assert dataset["advisory_only"] is True
    assert dataset["claim_eligible"] is False
    for task in dataset["tasks"]:
        raw = task["signals"]
        observation = TrajectoryObservation(
            task_kind=TaskKind(raw["task_kind"]),
            repository_files=raw["repository_files"],
            files_explored=tuple(raw["files_explored"]),
            dependency_breadth=raw["dependency_breadth"],
            test_failures=raw["test_failures"],
            no_progress_events=raw["no_progress_events"],
            uncertainty=raw["uncertainty"],
            tool_errors=raw["tool_errors"],
            verifier_state=VerifierState(raw["verifier_state"]),
            tokens_used=raw["tokens_used"],
            token_budget=raw["token_budget"],
            cost_usd=raw["cost_usd"],
            cost_budget_usd=raw["cost_budget_usd"],
            cost_is_reliable=raw["cost_is_reliable"],
            prior_escalations=raw["prior_escalations"],
        )
        decision = policy.advise(observation)
        assert decision.action.value == task["expected_advice"]
        assert decision.enforced is False


def test_loop_records_shadow_advice_without_changing_model_tier(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "onmc.db")
    storage.initialize()
    observed_escalation_levels: list[int] = []

    def agent_runner(prompt: str, *, escalation_level: int) -> AgentRunResult:
        del prompt
        observed_escalation_levels.append(escalation_level)
        return AgentRunResult(
            output="attempted a cross-module repair",
            prediction="repair dependency chain",
            files_touched=[
                "src/api.py",
                "pkg/models.py",
                "db/schema.py",
                "tests/test_api.py",
            ],
            tokens=None,
            cost_usd=None,
        )

    result = run_loop(
        storage,
        tmp_path,
        LoopSpec(goal="repair the dependency chain"),
        LoopConfig(
            max_iterations=2,
            escalation_threshold=99,
            no_progress_window=10,
        ),
        agent_runner=agent_runner,
        verify_runner=lambda command: VerifyOutcome(passed=False, output=f"{command}: failed"),
        change_probe=lambda: "",
        now=datetime(2024, 1, 1, tzinfo=UTC),
    )

    assert observed_escalation_levels == [0, 0]
    assert len(result.iterations) == 2
    route_receipt = result.iterations[1].route_decision
    assert route_receipt is not None
    shadow = route_receipt["shadow_model_advice"]
    assert isinstance(shadow, dict)
    assert shadow["action"] == RoutingAction.RECOMMEND_ESCALATION.value
    assert shadow["enforced"] is False
    assert shadow["preserve_worktree"] is True
    assert shadow["preserve_context"] is True
    assert "token telemetry unavailable" in shadow["telemetry_status"]
    observation = shadow["observed_trajectory"]
    assert isinstance(observation, dict)
    assert observation["task_kind"] == "cross-module"
    assert observation["file_breadth"] == 4
    assert observation["dependency_breadth"] == 3
