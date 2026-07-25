"""Eval-gated repository-learning state machine.

The pure, deterministic core that turns an *observed* signal into a *promoted*
learned artifact only after it survives sanitization, scoping, and a held-out
matched evaluation against a learning-DISABLED control.

No code path in this package activates learned behavior without a recorded
:class:`~.models.PromotionRecord`, and the whole machine is disable-able with a
single ``PromotionGate(learning_enabled=False)`` flag. Wiring existing memory
features through this gate is intentionally left to a later change; this package
is the gate infrastructure only.
"""

from __future__ import annotations

from .gate import (
    AdvanceEvent,
    Explanation,
    IllegalTransitionError,
    LearningError,
    PromotionDecision,
    PromotionGate,
    PromotionRejectedError,
    SanitizationError,
    advance,
    explain,
    rollback,
)
from .models import (
    CandidateKind,
    LearningCandidate,
    PromotionRecord,
    Provenance,
    RefreshPolicy,
    Scope,
    ShadowEvaluation,
)
from .sanitize import Finding, scan

__all__ = [
    "AdvanceEvent",
    "CandidateKind",
    "Explanation",
    "Finding",
    "IllegalTransitionError",
    "LearningCandidate",
    "LearningError",
    "PromotionDecision",
    "PromotionGate",
    "PromotionRecord",
    "PromotionRejectedError",
    "Provenance",
    "RefreshPolicy",
    "SanitizationError",
    "Scope",
    "ShadowEvaluation",
    "advance",
    "explain",
    "rollback",
    "scan",
]
