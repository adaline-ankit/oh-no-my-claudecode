"""Eval-gated repository-learning state machine.

The pure, deterministic core that turns an *observed* signal into a *promoted*
learned artifact only after it survives sanitization, scoping, and a held-out
matched evaluation against a learning-DISABLED control.

No code path in this package activates learned behavior without a recorded
:class:`~.models.PromotionRecord`, and the whole machine is disable-able with a
single kill switch — ``ONMC_LEARNING=0`` (see :mod:`.activation`), which is also
what ``PromotionGate(learning_enabled=False)`` expresses in code.

Two enforcement halves:

* :mod:`.gate` decides whether a candidate may be **promoted**;
* :mod:`.activation` decides whether a promoted candidate may be **activated**,
  and exposes :func:`~.activation.require_promoted` so a caller can *prove*
  authorization before acting on learned content. A call site that activates
  learned behavior without it is, by construction, an ungated bypass.

Wiring existing memory features through these seams is still incremental:
:mod:`.ingest` is the opt-in write seam, and code that writes to a store
directly remains ungated until it adopts :func:`~.activation.require_promoted`.
"""

from __future__ import annotations

from .activation import (
    LEARNING_ENABLED_ENV,
    ActivationDecision,
    ActivationRefusedError,
    ActivationTarget,
    active_candidates,
    can_roll_back,
    check_activation,
    env_gate,
    is_learning_enabled,
    require_promoted,
)
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
    "LEARNING_ENABLED_ENV",
    "ActivationDecision",
    "ActivationRefusedError",
    "ActivationTarget",
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
    "active_candidates",
    "advance",
    "can_roll_back",
    "check_activation",
    "env_gate",
    "explain",
    "is_learning_enabled",
    "require_promoted",
    "rollback",
    "scan",
]
