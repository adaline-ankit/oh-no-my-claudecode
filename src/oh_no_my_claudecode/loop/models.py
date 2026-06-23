"""Data models for the onmc loop engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass
class LoopSpec:
    """Goal and success criteria for one loop run."""

    goal: str
    success_criteria: str = ""


@dataclass
class IterationContract:
    """The falsifiable prediction-outcome contract for one iteration."""

    iteration: int
    prediction: str
    action_summary: str
    files_touched: list[str]
    verify_passed: bool
    verify_output: str
    outcome: Literal["win", "loss"]
    tokens: int | None = None


@dataclass
class LoopResult:
    """Aggregated result from a completed loop run."""

    iterations: list[IterationContract] = field(default_factory=list)
    converged: bool = False
    stop_reason: str = ""
    recorded_memory_ids: list[str] = field(default_factory=list)
    total_tokens: int = 0


@dataclass
class LoopConfig:
    """Runtime parameters for run_loop."""

    max_iterations: int = 10
    budget_tokens: int | None = None
    verify_command: str = "pytest"
    escalation_threshold: int = 3
    no_progress_window: int = 3


@dataclass
class AgentRunResult:
    """Output from one agent invocation."""

    output: str
    prediction: str
    files_touched: list[str]
    tokens: int | None = None


@dataclass
class VerifyOutcome:
    """Result from one verify command invocation."""

    passed: bool
    output: str


class AgentRunner(Protocol):
    """Injectable agent runner protocol."""

    def __call__(self, prompt: str, *, escalation_level: int) -> AgentRunResult:
        """Run agent and return result."""
        ...


class VerifyRunner(Protocol):
    """Injectable verify runner protocol."""

    def __call__(self, command: str) -> VerifyOutcome:
        """Run verify command and return outcome."""
        ...
