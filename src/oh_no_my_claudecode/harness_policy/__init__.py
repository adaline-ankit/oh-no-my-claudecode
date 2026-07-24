"""File-backed harness execution policy: paths, limits, verifiers, secrets.

Public surface:

- :class:`HarnessPolicy` — the repo-scoped guardrail (``.onmc/policy.json``).
- :class:`ChangeSet` — the observed effect of a run.
- :func:`evaluate_policy` — pure verdict (:class:`PolicyEvaluation`).
- :func:`load_policy` / :func:`save_policy` — file persistence.
- :func:`scan_secrets` — deterministic credential detection.
"""

from __future__ import annotations

from .engine import evaluate_policy
from .loader import POLICY_FILE, load_policy, policy_dir, save_policy
from .models import (
    ChangeSet,
    HarnessPolicy,
    PolicyEvaluation,
    PolicyOutcome,
    PolicyViolation,
    ViolationSeverity,
)
from .secrets import SecretFinding, scan_secrets

__all__ = [
    "POLICY_FILE",
    "ChangeSet",
    "HarnessPolicy",
    "PolicyEvaluation",
    "PolicyOutcome",
    "PolicyViolation",
    "SecretFinding",
    "ViolationSeverity",
    "evaluate_policy",
    "load_policy",
    "policy_dir",
    "save_policy",
    "scan_secrets",
]
