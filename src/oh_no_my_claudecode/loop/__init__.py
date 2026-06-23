"""Memory-grounded autonomous loop runner — onmc loop.

Each iteration recalls recorded dead-ends (via compile_guard) and relevant
memories, injects them into the agent prompt so the agent cannot repeat known
failures, then records the outcome back into storage so future iterations improve.
"""

from __future__ import annotations

from oh_no_my_claudecode.loop.engine import run_loop
from oh_no_my_claudecode.loop.models import (
    AgentRunner,
    AgentRunResult,
    IterationContract,
    LoopConfig,
    LoopResult,
    LoopSpec,
    VerifyOutcome,
    VerifyRunner,
)

__all__ = [
    "AgentRunResult",
    "AgentRunner",
    "IterationContract",
    "LoopConfig",
    "LoopResult",
    "LoopSpec",
    "VerifyOutcome",
    "VerifyRunner",
    "run_loop",
]
