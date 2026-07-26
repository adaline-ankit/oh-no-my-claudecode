"""Pre-registered predictions for governed harness and memory changes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class LearningComponent(StrEnum):
    """Component boundaries kept separate during learning experiments."""

    CONTEXT_POLICY = "context-policy"
    VERIFIER_POLICY = "verifier-policy"
    ROUTING_POLICY = "routing-policy"
    TOOL_MIDDLEWARE = "tool-middleware"
    MEMORY = "memory"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class PromotionPrediction:
    """Falsifiable effect prediction registered before held-out evaluation."""

    component: LearningComponent
    metric: str
    minimum_effect: float
    task_slice: str
    risk: str

    def __post_init__(self) -> None:
        if not isinstance(self.component, LearningComponent):
            raise ValueError("component must be a LearningComponent")
        for name in ("metric", "task_slice", "risk"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if (
            isinstance(self.minimum_effect, bool)
            or not isinstance(self.minimum_effect, (int, float))
            or not math.isfinite(self.minimum_effect)
            or self.minimum_effect < 0
        ):
            raise ValueError("minimum_effect must be a finite non-negative number")

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component.value,
            "metric": self.metric,
            "minimum_effect": self.minimum_effect,
            "task_slice": self.task_slice,
            "risk": self.risk,
        }


__all__ = ["LearningComponent", "PromotionPrediction"]
