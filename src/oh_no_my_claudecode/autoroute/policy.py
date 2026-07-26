"""Deterministic shadow policy for trajectory-aware model routing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .trajectory import TaskKind, TrajectoryObservation, VerifierState


class RoutingAction(StrEnum):
    """Advisory action for the next bounded episode."""

    CONTINUE_CHEAP = "continue-cheap"
    RECOMMEND_ESCALATION = "recommend-escalation"
    HOLD_TIER = "hold-tier"


@dataclass(frozen=True, slots=True)
class ShadowRoutingDecision:
    """A recommendation that cannot mutate runtime model selection."""

    action: RoutingAction
    current_model: str
    recommended_model: str
    reasons: tuple[str, ...]
    observed_risk_score: int
    cost_learning_eligible: bool
    telemetry_status: tuple[str, ...]
    observation: TrajectoryObservation
    advisory_only: bool = True
    enforced: bool = False
    preserve_worktree: bool = True
    preserve_context: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "current_model": self.current_model,
            "recommended_model": self.recommended_model,
            "reasons": list(self.reasons),
            "observed_risk_score": self.observed_risk_score,
            "cost_learning_eligible": self.cost_learning_eligible,
            "telemetry_status": list(self.telemetry_status),
            "observed_trajectory": self.observation.to_dict(),
            "advisory_only": self.advisory_only,
            "enforced": self.enforced,
            "preserve_worktree": self.preserve_worktree,
            "preserve_context": self.preserve_context,
        }


@dataclass(frozen=True, slots=True)
class ShadowRoutingPolicy:
    """Recommend at most one escalation from observed progress signals.

    The policy intentionally exposes no enforcement switch. A caller can record
    the result in a trajectory or experiment, but cannot use this type to
    silently change the runtime model.
    """

    cheap_model: str
    strong_model: str
    max_escalations: int = 1
    large_repository_threshold: int = 1_000
    broad_file_threshold: int = 4
    broad_dependency_threshold: int = 3
    repeated_failure_threshold: int = 2
    no_progress_threshold: int = 2
    uncertainty_threshold: float = 0.7

    def __post_init__(self) -> None:
        if not self.cheap_model.strip() or not self.strong_model.strip():
            raise ValueError("model names must be non-empty")
        if self.max_escalations != 1:
            raise ValueError("two-tier shadow routing supports exactly one escalation")
        for name in (
            "large_repository_threshold",
            "broad_file_threshold",
            "broad_dependency_threshold",
            "repeated_failure_threshold",
            "no_progress_threshold",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not 0.0 <= self.uncertainty_threshold <= 1.0:
            raise ValueError("uncertainty_threshold must be in [0, 1]")

    def advise(self, observation: TrajectoryObservation) -> ShadowRoutingDecision:
        current_model = (
            self.strong_model if observation.prior_escalations else self.cheap_model
        )
        risk_score, risk_reasons = self._risk(observation)

        if observation.token_budget_exhausted:
            return self._decision(
                RoutingAction.HOLD_TIER,
                current_model,
                current_model,
                ("token budget exhausted",),
                risk_score,
                observation,
            )
        if observation.cost_budget_exhausted:
            return self._decision(
                RoutingAction.HOLD_TIER,
                current_model,
                current_model,
                ("cost budget exhausted",),
                risk_score,
                observation,
            )
        if observation.prior_escalations >= self.max_escalations:
            return self._decision(
                RoutingAction.HOLD_TIER,
                current_model,
                current_model,
                ("escalation cap reached",),
                risk_score,
                observation,
            )
        if observation.verifier_state is VerifierState.PASSED:
            action = (
                RoutingAction.HOLD_TIER
                if observation.prior_escalations
                else RoutingAction.CONTINUE_CHEAP
            )
            return self._decision(
                action,
                current_model,
                current_model,
                ("targeted verifier passed",),
                risk_score,
                observation,
            )

        failure_signal = (
            observation.test_failures >= self.repeated_failure_threshold
            or observation.no_progress_events >= self.no_progress_threshold
            or observation.verifier_state is VerifierState.FAILED
        )
        if failure_signal and risk_score >= 3:
            return self._decision(
                RoutingAction.RECOMMEND_ESCALATION,
                current_model,
                self.strong_model,
                risk_reasons,
                risk_score,
                observation,
            )

        reasons = risk_reasons or ("insufficient observed evidence to escalate",)
        return self._decision(
            RoutingAction.CONTINUE_CHEAP,
            current_model,
            current_model,
            reasons,
            risk_score,
            observation,
        )

    def _risk(self, observation: TrajectoryObservation) -> tuple[int, tuple[str, ...]]:
        reasons: list[str] = []
        if observation.task_kind is TaskKind.CROSS_MODULE:
            reasons.append("cross-module task")
        if (
            observation.repository_files is not None
            and observation.repository_files >= self.large_repository_threshold
        ):
            reasons.append("large repository")
        if observation.file_breadth >= self.broad_file_threshold:
            reasons.append("broad file exploration")
        if observation.dependency_breadth >= self.broad_dependency_threshold:
            reasons.append("broad dependency exploration")
        if observation.test_failures >= self.repeated_failure_threshold:
            reasons.append("repeated test failures")
        if observation.no_progress_events >= self.no_progress_threshold:
            reasons.append("repeated no-progress observations")
        if observation.verifier_state is VerifierState.FAILED:
            reasons.append("independent verifier failed")
        if (
            observation.uncertainty is not None
            and observation.uncertainty >= self.uncertainty_threshold
        ):
            reasons.append("high observed uncertainty")
        if observation.tool_errors >= self.repeated_failure_threshold:
            reasons.append("repeated tool errors")
        return len(reasons), tuple(reasons)

    @staticmethod
    def _decision(
        action: RoutingAction,
        current_model: str,
        recommended_model: str,
        reasons: tuple[str, ...],
        risk_score: int,
        observation: TrajectoryObservation,
    ) -> ShadowRoutingDecision:
        return ShadowRoutingDecision(
            action=action,
            current_model=current_model,
            recommended_model=recommended_model,
            reasons=reasons,
            observed_risk_score=risk_score,
            cost_learning_eligible=observation.cost_learning_eligible,
            telemetry_status=ShadowRoutingPolicy._telemetry_status(observation),
            observation=observation,
        )

    @staticmethod
    def _telemetry_status(observation: TrajectoryObservation) -> tuple[str, ...]:
        status: list[str] = []
        if not observation.token_telemetry_available:
            status.append("token telemetry unavailable")
        if observation.cost_usd is None:
            status.append("cost telemetry unavailable; cost learning disabled")
        elif not observation.cost_is_reliable:
            status.append("cost telemetry unreliable; cost learning disabled")
        return tuple(status)


__all__ = [
    "RoutingAction",
    "ShadowRoutingDecision",
    "ShadowRoutingPolicy",
]
