"""Observed partial-trajectory signals for advisory model routing."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum


class TaskKind(StrEnum):
    """Coarse task shape observed by the runtime, not inferred from keywords."""

    LOCAL_EDIT = "local-edit"
    CROSS_MODULE = "cross-module"
    UNKNOWN = "unknown"


class VerifierState(StrEnum):
    """Observed state of the independent verifier."""

    NOT_RUN = "not-run"
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


def _require_non_negative_int(value: int | None, name: str) -> None:
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or None")


def _require_non_negative_number(value: float | None, name: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be a finite non-negative number or None")


@dataclass(frozen=True, slots=True)
class TrajectoryObservation:
    """Signals available after a bounded exploratory model episode.

    Every field is supplied by runtime observation or an explicit task
    contract. The type deliberately contains no prompt text, keyword score, or
    opaque model confidence.
    """

    task_kind: TaskKind
    repository_files: int | None
    files_explored: tuple[str, ...]
    dependency_breadth: int
    test_failures: int
    no_progress_events: int
    uncertainty: float | None
    tool_errors: int
    verifier_state: VerifierState
    tokens_used: int | None = None
    token_budget: int | None = None
    cost_usd: float | None = None
    cost_budget_usd: float | None = None
    cost_is_reliable: bool = False
    prior_escalations: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.task_kind, TaskKind):
            raise ValueError("task_kind must be a TaskKind")
        if not isinstance(self.verifier_state, VerifierState):
            raise ValueError("verifier_state must be a VerifierState")
        if not isinstance(self.cost_is_reliable, bool):
            raise ValueError("cost_is_reliable must be a bool")
        for path in self.files_explored:
            if not isinstance(path, str) or not path.strip():
                raise ValueError("files_explored entries must be non-empty strings")
        if len(set(self.files_explored)) != len(self.files_explored):
            raise ValueError("files_explored must not contain duplicates")
        for name in (
            "repository_files",
            "dependency_breadth",
            "test_failures",
            "no_progress_events",
            "tool_errors",
            "tokens_used",
            "token_budget",
            "prior_escalations",
        ):
            _require_non_negative_int(getattr(self, name), name)
        _require_non_negative_number(self.cost_usd, "cost_usd")
        _require_non_negative_number(self.cost_budget_usd, "cost_budget_usd")
        if self.uncertainty is not None and (
                isinstance(self.uncertainty, bool)
                or not isinstance(self.uncertainty, (int, float))
                or not math.isfinite(self.uncertainty)
                or not 0.0 <= self.uncertainty <= 1.0
        ):
            raise ValueError("uncertainty must be a finite number in [0, 1] or None")

    @property
    def file_breadth(self) -> int:
        """Number of distinct files observed during the episode."""
        return len(self.files_explored)

    @property
    def token_telemetry_available(self) -> bool:
        return self.tokens_used is not None

    @property
    def cost_learning_eligible(self) -> bool:
        """Whether this observation may train or evaluate a cost policy."""
        return self.cost_usd is not None and self.cost_is_reliable

    @property
    def token_budget_exhausted(self) -> bool:
        return (
            self.token_budget is not None
            and self.tokens_used is not None
            and self.tokens_used >= self.token_budget
        )

    @property
    def cost_budget_exhausted(self) -> bool:
        return (
            self.cost_budget_usd is not None
            and self.cost_usd is not None
            and self.cost_usd >= self.cost_budget_usd
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "task_kind": self.task_kind.value,
            "repository_files": self.repository_files,
            "files_explored": list(self.files_explored),
            "file_breadth": self.file_breadth,
            "dependency_breadth": self.dependency_breadth,
            "test_failures": self.test_failures,
            "no_progress_events": self.no_progress_events,
            "uncertainty": self.uncertainty,
            "tool_errors": self.tool_errors,
            "verifier_state": self.verifier_state.value,
            "tokens_used": self.tokens_used,
            "token_budget": self.token_budget,
            "cost_usd": self.cost_usd,
            "cost_budget_usd": self.cost_budget_usd,
            "cost_is_reliable": self.cost_is_reliable,
            "cost_learning_eligible": self.cost_learning_eligible,
            "prior_escalations": self.prior_escalations,
        }


__all__ = ["TaskKind", "TrajectoryObservation", "VerifierState"]
