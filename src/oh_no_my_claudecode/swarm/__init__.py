"""onmc swarm — parallel accountable agent loops across isolated worktrees.

Honest concurrency model
------------------------
"100s of agents" means a QUEUE of 100s of tasks drained by a BOUNDED worker
pool (default concurrency = min(cpu_count-1, 8)).  It does NOT mean 100s of
simultaneous processes.  Real limits include CPU, RAM, file descriptors, and
API rate limits.  The pool size is configurable; the honesty about it is not.
"""

from __future__ import annotations

from oh_no_my_claudecode.swarm.models import (
    SwarmConfig,
    SwarmResult,
    SwarmUnit,
    SwarmUnitResult,
)
from oh_no_my_claudecode.swarm.orchestrator import request_abort, run_swarm, swarm_state

__all__ = [
    "SwarmConfig",
    "SwarmResult",
    "SwarmUnit",
    "SwarmUnitResult",
    "request_abort",
    "run_swarm",
    "swarm_state",
]
