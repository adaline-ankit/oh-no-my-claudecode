"""Data models for the No-Mistakes PR gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AutonomyLevel = Literal["L0", "L1", "L2", "L3", "L4"]
GateStatus = Literal["pass", "fail", "skip"]


@dataclass
class GateCheck:
    """One deterministic gate inside a No-Mistakes run."""

    name: str
    status: GateStatus
    detail: str
    blocking: bool = False


@dataclass
class NoMistakesResult:
    """Aggregated No-Mistakes result."""

    goal: str
    autonomy: AutonomyLevel
    approved: bool
    dry_run: bool
    agent: str
    verify_command: str
    gates: list[GateCheck] = field(default_factory=list)
    autopilot_result: object | None = None
    receipt_path: str | None = None

    @property
    def blocking_gates(self) -> list[GateCheck]:
        """Return gates that block approval."""
        return [gate for gate in self.gates if gate.blocking]
