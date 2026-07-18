"""Autonomous-continuity eval — orchestration-safety SIM.

This sub-package measures where ONMC's orchestration policy beats naive
orchestration over a long unattended multi-task run.

The eval is a DETERMINISTIC POLICY SIMULATION (no LLM, no subprocess, fully
reproducible in CI) because the differentiator here is POLICY, not model
quality.  The A/B harness already covers per-task precision; this covers what
happens across a whole unattended session.

Key policy differences measured:
- False-green rejection: ONMC refuses no-diff "completions".
- Cascade/poisoning prevention: ONMC isolates broken tasks so one failure does
  not block the rest of the session.
- Scope enforcement: ONMC rejects tasks that edited protected paths.
- Transient-error survival: ONMC retries once then skips safely with no
  tree poisoning.
"""

from oh_no_my_claudecode.evals.continuity.harness import run_continuity
from oh_no_my_claudecode.evals.continuity.models import (
    ContinuityComparison,
    ContinuityTask,
    OrchestratorReport,
    TaskRun,
)
from oh_no_my_claudecode.evals.continuity.suite import BUILTIN_TASKS

__all__ = [
    "ContinuityTask",
    "TaskRun",
    "OrchestratorReport",
    "ContinuityComparison",
    "run_continuity",
    "BUILTIN_TASKS",
]
