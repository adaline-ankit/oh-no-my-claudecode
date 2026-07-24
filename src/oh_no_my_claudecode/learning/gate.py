"""The eval-gated learning state machine — transitions, promotion gate, rollback.

This is the pure core that decides *whether* and *how* a
:class:`~.models.LearningCandidate` may advance along its lifecycle. It enforces
three independent guarantees:

1. **Legal transitions only.** Every move is validated against
   :func:`~oh_no_my_claudecode.experiment.contracts.is_legal_transition`; an
   illegal move raises :class:`IllegalTransitionError`.
2. **No unsanitized learning.** A candidate carrying sanitizer findings can
   never advance past ``sanitized`` — the first step beyond it raises
   :class:`SanitizationError`.
3. **No unproven promotion.** :class:`PromotionGate` refuses promotion unless
   the candidate is sanitized-clean, has a non-empty scope, has a held-out
   matched evaluation that strictly beats a learning-DISABLED control, and its
   protected-suite non-regression flag holds. It is also globally disable-able
   with a single ``learning_enabled=False`` flag — the control path in which no
   candidate ever activates.

Every promotion records provenance, evidence, and a bumped version, and is
always reversible via :func:`rollback`. :func:`explain` surfaces the injection
and promotion evidence for any candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from oh_no_my_claudecode.experiment.contracts import CandidateState, is_legal_transition

from . import sanitize
from .models import (
    LearningCandidate,
    PromotionRecord,
    Scope,
    ShadowEvaluation,
)


class LearningError(Exception):
    """Base class for all learning-gate errors."""


class IllegalTransitionError(LearningError):
    """Raised when a requested state move is not in the legal transition map."""

    def __init__(self, src: CandidateState, dst: CandidateState) -> None:
        self.src = src
        self.dst = dst
        super().__init__(f"illegal transition {src.value} -> {dst.value}")


class SanitizationError(LearningError):
    """Raised when a candidate with findings tries to advance past ``sanitized``."""

    def __init__(self, candidate_id: str, findings: tuple[sanitize.Finding, ...]) -> None:
        self.candidate_id = candidate_id
        self.findings = findings
        rule_ids = ", ".join(f.rule_id for f in findings) or "none"
        super().__init__(
            f"candidate {candidate_id!r} cannot advance past sanitized "
            f"({len(findings)} finding(s): {rule_ids})"
        )


class PromotionRejectedError(LearningError):
    """Raised when :class:`PromotionGate` refuses a promotion."""

    def __init__(self, candidate_id: str, reasons: tuple[str, ...]) -> None:
        self.candidate_id = candidate_id
        self.reasons = reasons
        super().__init__(f"promotion of {candidate_id!r} rejected: {'; '.join(reasons)}")


@dataclass(frozen=True, slots=True)
class AdvanceEvent:
    """A requested lifecycle move plus the payload that move requires.

    * ``to`` — the target state.
    * ``scope`` — required when advancing to ``SCOPED``.
    * ``evaluation`` — required when advancing to ``SHADOW_EVALUATED``.
    * ``at_ms`` — wall-clock stamp recorded on promotion.
    * ``reason`` — free-text audit note.
    """

    to: CandidateState
    scope: Scope | None = None
    evaluation: ShadowEvaluation | None = None
    at_ms: int = 0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Outcome of evaluating a candidate against the promotion gate."""

    eligible: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"eligible": self.eligible, "reasons": list(self.reasons)}


@dataclass(frozen=True, slots=True)
class PromotionGate:
    """Decides whether a shadow-evaluated candidate may be promoted.

    Conditions (all must hold):

    a. sanitized clean — no sanitizer findings;
    b. scope set — a non-empty :class:`~.models.Scope`;
    c. held-out improvement — a matched evaluation whose learning-enabled arm
       strictly beats the learning-DISABLED control by ``min_improvement``;
    d. protected-suite non-regression flag holds.

    ``learning_enabled=False`` is the single global off switch: the control
    path in which nothing is ever eligible for promotion.
    """

    min_improvement: float = 0.0
    learning_enabled: bool = True

    def evaluate(self, candidate: LearningCandidate) -> PromotionDecision:
        reasons: list[str] = []

        if not self.learning_enabled:
            reasons.append("learning-disabled: promotion suppressed by global flag")

        if candidate.state is not CandidateState.SHADOW_EVALUATED:
            reasons.append(
                f"wrong-state: must be shadow-evaluated, is {candidate.state.value}"
            )

        if not candidate.is_sanitized_clean:
            reasons.append(f"not-sanitized-clean: {len(candidate.findings)} finding(s)")

        if candidate.scope.is_empty:
            reasons.append("no-scope: candidate scope is empty")

        evaluation = candidate.evaluation
        if evaluation is None:
            reasons.append("no-evaluation: held-out shadow evaluation missing")
        else:
            if not evaluation.held_out:
                reasons.append("not-held-out: evaluation was not run on a held-out set")
            if not evaluation.improves_over_control(self.min_improvement):
                reasons.append(
                    "no-improvement: learning arm does not beat the disabled control "
                    f"(delta={evaluation.delta:.4f}, required>{self.min_improvement:.4f})"
                )
            if not evaluation.protected_suite_passed:
                reasons.append("protected-regression: protected-suite non-regression flag is false")

        return PromotionDecision(eligible=not reasons, reasons=tuple(reasons))

    def would_promote(self, candidate: LearningCandidate) -> bool:
        return self.evaluate(candidate).eligible


_DEFAULT_GATE = PromotionGate()


def advance(
    candidate: LearningCandidate,
    event: AdvanceEvent,
    *,
    gate: PromotionGate | None = None,
) -> LearningCandidate:
    """Advance *candidate* by *event*, returning a new candidate.

    Enforces legal transitions, the sanitize barrier, and (for promotion) the
    :class:`PromotionGate`. Never mutates the input.
    """
    gate = gate if gate is not None else _DEFAULT_GATE
    src, dst = candidate.state, event.to

    if not is_legal_transition(src, dst):
        raise IllegalTransitionError(src, dst)

    # The sanitize barrier: anything that leaves the sanitized state forward
    # (i.e. into scoped or beyond) requires a clean bill of health. Rollback is
    # always allowed regardless of findings.
    if (
        src is CandidateState.SANITIZED
        and dst is CandidateState.SCOPED
        and not candidate.is_sanitized_clean
    ):
        raise SanitizationError(candidate.id, candidate.findings)

    updates: dict[str, object] = {"state": dst, "updated_at_ms": event.at_ms}

    if dst is CandidateState.SANITIZED:
        # Scan on entry; findings are recorded and will block the next step.
        updates["findings"] = sanitize.scan(candidate.content)

    elif dst is CandidateState.SCOPED:
        if event.scope is None or event.scope.is_empty:
            raise LearningError(
                f"advancing {candidate.id!r} to scoped requires a non-empty scope"
            )
        updates["scope"] = event.scope

    elif dst is CandidateState.SHADOW_EVALUATED:
        if event.evaluation is None:
            raise LearningError(
                f"advancing {candidate.id!r} to shadow-evaluated requires an evaluation"
            )
        updates["evaluation"] = event.evaluation

    elif dst is CandidateState.PROMOTED:
        decision = gate.evaluate(candidate)
        if not decision.eligible:
            raise PromotionRejectedError(candidate.id, decision.reasons)
        assert candidate.evaluation is not None  # guaranteed by gate  # noqa: S101
        new_version = candidate.version + 1
        updates["version"] = new_version
        updates["promotion"] = PromotionRecord(
            version=new_version,
            evaluation=candidate.evaluation,
            provenance=candidate.provenance,
            scope=candidate.scope,
            promoted_at_ms=event.at_ms,
            reason=event.reason,
        )

    return candidate.evolve(**updates)


def rollback(
    candidate: LearningCandidate,
    *,
    at_ms: int = 0,
    reason: str = "",
) -> LearningCandidate:
    """Instantly reverse a candidate to the safe, inactive ``ROLLED_BACK`` state.

    Legal from any active state (candidate through monitored). The result is
    never active (:meth:`LearningCandidate.is_active` is ``False``).
    """
    return advance(
        candidate,
        AdvanceEvent(to=CandidateState.ROLLED_BACK, at_ms=at_ms, reason=reason),
    )


@dataclass(frozen=True, slots=True)
class Explanation:
    """Human/agent-readable evidence bundle for a candidate."""

    candidate_id: str
    state: CandidateState
    version: int
    sanitized_clean: bool
    findings: tuple[sanitize.Finding, ...]
    scope_set: bool
    promotion_decision: PromotionDecision
    promotion: PromotionRecord | None
    active: bool = field(default=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "state": self.state.value,
            "version": self.version,
            "sanitized_clean": self.sanitized_clean,
            "findings": [f.to_dict() for f in self.findings],
            "scope_set": self.scope_set,
            "promotion_decision": self.promotion_decision.to_dict(),
            "promotion": self.promotion.to_dict() if self.promotion else None,
            "active": self.active,
        }


def explain(
    candidate: LearningCandidate,
    *,
    gate: PromotionGate | None = None,
    now_ms: int = 0,
) -> Explanation:
    """Return the injection + promotion evidence for *candidate*."""
    gate = gate if gate is not None else _DEFAULT_GATE
    return Explanation(
        candidate_id=candidate.id,
        state=candidate.state,
        version=candidate.version,
        sanitized_clean=candidate.is_sanitized_clean,
        findings=candidate.findings,
        scope_set=not candidate.scope.is_empty,
        promotion_decision=gate.evaluate(candidate),
        promotion=candidate.promotion,
        active=candidate.is_active(now_ms),
    )


__all__ = [
    "AdvanceEvent",
    "Explanation",
    "IllegalTransitionError",
    "LearningError",
    "PromotionDecision",
    "PromotionGate",
    "PromotionRejectedError",
    "SanitizationError",
    "advance",
    "explain",
    "rollback",
]
