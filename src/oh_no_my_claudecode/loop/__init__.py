"""Memory-grounded autonomous loop runner — onmc loop.

Each iteration recalls recorded dead-ends (via compile_guard) and relevant
memories, injects them into the agent prompt so the agent cannot repeat known
failures, then records the outcome back into storage so future iterations improve.
"""

from __future__ import annotations

from oh_no_my_claudecode.loop.checkpoint import (
    CheckpointState,
    CheckpointStore,
    FileCheckpointStore,
    InMemoryCheckpointStore,
)
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
from oh_no_my_claudecode.loop.templates import LoopTemplate, get_template, list_templates

__all__ = [
    "AgentRunResult",
    "AgentRunner",
    "CheckpointState",
    "CheckpointStore",
    "FileCheckpointStore",
    "InMemoryCheckpointStore",
    "IterationContract",
    "LoopConfig",
    "LoopResult",
    "LoopSpec",
    "LoopTemplate",
    "VerifyOutcome",
    "VerifyRunner",
    "get_template",
    "list_templates",
    "run_loop",
]
