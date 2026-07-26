"""Observed-trajectory routing for the ONMC loop runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from oh_no_my_claudecode.loop.models import IterationContract

RouteAction = Literal["start", "continue", "escalate"]


@dataclass(frozen=True, slots=True)
class TrajectorySignals:
    """Signals observed before dispatching the next loop episode."""

    iteration: int
    current_escalation_level: int
    consecutive_losses: int
    escalation_threshold: int
    consecutive_noops: int
    consecutive_same_error: int
    total_tokens: int
    total_cost_usd: float
    last_loss: IterationContract | None = None


@dataclass(frozen=True, slots=True)
class TrajectoryRouteDecision:
    """Routing decision for the next bounded agent episode."""

    iteration: int
    action: RouteAction
    escalation_level: int
    reset_consecutive_losses: bool
    confidence: float
    rationale: str
    signals: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "iteration": self.iteration,
            "action": self.action,
            "escalation_level": self.escalation_level,
            "reset_consecutive_losses": self.reset_consecutive_losses,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "signals": list(self.signals),
        }


def route_next_iteration(signals: TrajectorySignals) -> TrajectoryRouteDecision:
    """Route the next loop episode from observed trajectory state.

    This is deliberately conservative: it does not guess from prompt keywords.
    It escalates only after the runtime has observed repeated losses or a
    strong live failure signal from the previous episode.
    """
    if signals.last_loss is None:
        return TrajectoryRouteDecision(
            iteration=signals.iteration,
            action="start",
            escalation_level=signals.current_escalation_level,
            reset_consecutive_losses=False,
            confidence=0.0,
            rationale="no prior episode; start at the requested model tier",
        )

    observed = _observed_signals(signals)
    threshold = max(signals.escalation_threshold, 1)
    threshold_hit = signals.consecutive_losses >= threshold
    strong_live_signal = bool(
        signals.consecutive_noops > 0
        or signals.consecutive_same_error >= 2
        or (
            signals.last_loss.tokens is not None
            and signals.last_loss.tokens >= 8_000
            and signals.last_loss.outcome == "loss"
        )
        or len(signals.last_loss.files_touched) >= 6
    )

    if threshold_hit or strong_live_signal:
        reasons = tuple(observed) or ("loss threshold reached",)
        return TrajectoryRouteDecision(
            iteration=signals.iteration,
            action="escalate",
            escalation_level=signals.current_escalation_level + 1,
            reset_consecutive_losses=True,
            confidence=0.72 if threshold_hit else 0.58,
            rationale="; ".join(reasons),
            signals=reasons,
        )

    loss_count = signals.consecutive_losses
    return TrajectoryRouteDecision(
        iteration=signals.iteration,
        action="continue",
        escalation_level=signals.current_escalation_level,
        reset_consecutive_losses=False,
        confidence=0.45,
        rationale=(
            f"observed {loss_count}/{threshold} loss(es); continue current "
            "episode before escalating"
        ),
        signals=tuple(observed),
    )


def render_route_prompt(decision: TrajectoryRouteDecision) -> str:
    """Render a compact, untrusted-safe routing note for the agent prompt."""
    if decision.action == "start":
        return ""
    return (
        "## ONMC routing decision\n\n"
        f"Action: {decision.action}; escalation_level={decision.escalation_level}; "
        f"confidence={decision.confidence:.2f}.\n"
        f"Basis: {decision.rationale}\n"
    )


def _observed_signals(signals: TrajectorySignals) -> list[str]:
    out: list[str] = []
    threshold = max(signals.escalation_threshold, 1)
    if signals.consecutive_losses >= threshold:
        out.append(f"{signals.consecutive_losses} consecutive losses reached threshold")
    elif signals.consecutive_losses > 0:
        out.append(f"{signals.consecutive_losses}/{threshold} consecutive losses")
    if signals.consecutive_noops > 0:
        out.append("previous verifier pass was vacuous because no net change was observed")
    if signals.consecutive_same_error >= 2:
        out.append(f"{signals.consecutive_same_error} repeated verifier-error heads")
    if signals.last_loss is not None:
        touched = len(signals.last_loss.files_touched)
        if touched >= 6:
            out.append(f"last failed episode touched {touched} files")
        if signals.last_loss.tokens is not None and signals.last_loss.tokens >= 8_000:
            out.append(f"last failed episode spent {signals.last_loss.tokens} tokens")
    if signals.total_cost_usd > 0:
        out.append(f"observed cost ${signals.total_cost_usd:.4f}")
    elif signals.total_tokens > 0:
        out.append(f"observed {signals.total_tokens} tokens")
    return out


__all__ = [
    "RouteAction",
    "TrajectoryRouteDecision",
    "TrajectorySignals",
    "render_route_prompt",
    "route_next_iteration",
]
