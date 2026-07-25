"""Activation enforcement — the kill switch and the promote-before-activate guard.

:mod:`.gate` decides whether a candidate *may* be promoted. This module governs
the other half of the contract: whether an already-promoted artifact may
*currently influence an agent*, and it gives callers a way to **prove** that
before they act on learned content. Together they make the gate authoritative
rather than advisory:

* :func:`is_learning_enabled` / :data:`LEARNING_ENABLED_ENV` — the single kill
  switch. ``ONMC_LEARNING=0`` renders every learned artifact inert: no candidate
  is eligible for promotion (via :func:`env_gate`) and no candidate is
  activatable (via :func:`check_activation` / :func:`require_promoted`).
  This mirrors the established ``ONMC_FIREWALL`` kill-switch idiom in
  :mod:`oh_no_my_claudecode.hooks.firewall` — default ON, and ``0`` / ``false``
  / ``no`` / ``off`` turn it OFF.

* :func:`check_activation` — a non-raising audit of one candidate against the
  full activation contract, returning an :class:`ActivationDecision` with
  machine-readable reason codes.

* :func:`require_promoted` — the assertion form. It returns the
  :class:`~.models.PromotionRecord` that authorizes activation and raises
  :class:`ActivationRefusedError` otherwise, so a bypass becomes a loud failure
  instead of a silent one. Callers that activate learned behavior without
  calling it are, by construction, ungated — which is exactly what makes the
  bypass auditable.

The activation contract (every clause must hold):

a. the kill switch is ON;
b. state is ``PROMOTED`` or ``MONITORED`` — see
   :meth:`~.models.LearningCandidate.is_active`;
c. a :class:`~.models.PromotionRecord` exists and its version is ``>= 1``;
d. the refresh policy has not expired (no stale learning);
e. the candidate is sanitize-clean (no injection/secret findings);
f. the promotion record carries a non-empty :class:`~.models.Scope` and, when a
   target context is supplied, that scope covers it;
g. the promotion record carries honest, non-empty
   :class:`~.models.Provenance`;
h. a rollback path still exists — the artifact can be reversed.

Nothing here mutates a candidate or touches any store; it is a pure predicate
layer over the existing contracts.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from oh_no_my_claudecode.experiment.contracts import CandidateState, is_legal_transition

from .gate import LearningError, PromotionGate
from .models import LearningCandidate, PromotionRecord

#: The single kill switch for all active learned behavior. Default ON; set to
#: any value in :data:`_DISABLED_VALUES` to make every learned artifact inert.
LEARNING_ENABLED_ENV = "ONMC_LEARNING"

_DISABLED_VALUES = frozenset({"0", "false", "no", "off"})


def is_learning_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether learned behavior is allowed at all (default ``True``).

    Reads :data:`LEARNING_ENABLED_ENV` (``ONMC_LEARNING``) from *env* (defaulting
    to :data:`os.environ`):

    * ``"0"`` / ``"false"`` / ``"no"`` / ``"off"`` (any case) → learning OFF;
    * anything else, including unset → learning ON.

    This is the one flag that disables *both* promotion (through
    :func:`env_gate`) and activation (through :func:`check_activation`).
    """
    source = os.environ if env is None else env
    return source.get(LEARNING_ENABLED_ENV, "").strip().lower() not in _DISABLED_VALUES


def env_gate(
    *,
    min_improvement: float = 0.0,
    env: Mapping[str, str] | None = None,
) -> PromotionGate:
    """Build a :class:`~.gate.PromotionGate` wired to the kill switch.

    Prefer this over ``PromotionGate()`` at call sites that construct a gate from
    ambient configuration, so ``ONMC_LEARNING=0`` suppresses promotion without
    every caller re-reading the environment.
    """
    return PromotionGate(
        min_improvement=min_improvement,
        learning_enabled=is_learning_enabled(env),
    )


class ActivationRefusedError(LearningError):
    """Raised by :func:`require_promoted` when activation is not authorized.

    Carries the machine-readable ``reasons`` from the failed
    :class:`ActivationDecision` so a caller can log precisely which clause of the
    activation contract was violated.
    """

    def __init__(self, candidate_id: str, reasons: tuple[str, ...]) -> None:
        self.candidate_id = candidate_id
        self.reasons = reasons
        super().__init__(
            f"activation of {candidate_id!r} refused: {'; '.join(reasons) or 'unknown'}"
        )


@dataclass(frozen=True, slots=True)
class ActivationTarget:
    """The context a learned artifact is about to be applied to.

    Passed to :func:`check_activation` to enforce clause (f): a promoted
    artifact only activates inside the scope it was promoted for. All fields
    optional — an omitted dimension is only satisfied if the promoted scope
    leaves that dimension unconstrained (see :meth:`~.models.Scope.matches`).
    """

    repo: str | None = None
    branch: str | None = None
    path: str | None = None
    language: str | None = None
    task: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "repo": self.repo,
            "branch": self.branch,
            "path": self.path,
            "language": self.language,
            "task": self.task,
        }


@dataclass(frozen=True, slots=True)
class ActivationDecision:
    """Outcome of auditing one candidate against the activation contract.

    ``active`` is the single bit a caller acts on; ``reasons`` explains every
    violated clause (never just the first), and ``promotion`` is the record that
    authorizes activation when ``active`` is ``True``.
    """

    active: bool
    candidate_id: str
    reasons: tuple[str, ...] = ()
    promotion: PromotionRecord | None = None
    learning_enabled: bool = True
    target: ActivationTarget | None = field(default=None)

    @property
    def refused(self) -> bool:
        return not self.active

    def to_dict(self) -> dict[str, object]:
        return {
            "active": self.active,
            "candidate_id": self.candidate_id,
            "reasons": list(self.reasons),
            "promotion": self.promotion.to_dict() if self.promotion else None,
            "learning_enabled": self.learning_enabled,
            "target": self.target.to_dict() if self.target else None,
        }


def can_roll_back(candidate: LearningCandidate) -> bool:
    """Whether *candidate* still has a rollback path out of its current state.

    An artifact with no way back is not safely activatable — clause (h).
    """
    return is_legal_transition(candidate.state, CandidateState.ROLLED_BACK)


def check_activation(
    candidate: LearningCandidate,
    *,
    now_ms: int,
    target: ActivationTarget | None = None,
    env: Mapping[str, str] | None = None,
) -> ActivationDecision:
    """Audit *candidate* against the full activation contract, without raising.

    Collects **every** violated clause so an auditor sees the whole picture, and
    returns the authorizing :class:`~.models.PromotionRecord` when the candidate
    is genuinely activatable. Pure: never mutates *candidate*.
    """
    enabled = is_learning_enabled(env)
    reasons: list[str] = []

    if not enabled:
        reasons.append(
            f"kill-switch: {LEARNING_ENABLED_ENV} is disabled — all learned behaviour is inert"
        )

    if candidate.state not in (CandidateState.PROMOTED, CandidateState.MONITORED):
        reasons.append(f"not-promoted: state is {candidate.state.value}")

    record = candidate.promotion
    if record is None:
        reasons.append("no-promotion-record: nothing authorized this activation")
    else:
        if record.version < 1:
            reasons.append(f"unversioned-promotion: version is {record.version}")
        if record.scope.is_empty:
            reasons.append("no-scope: promotion record carries an empty scope")
        elif target is not None and not record.scope.matches(
            repo=target.repo,
            branch=target.branch,
            path=target.path,
            language=target.language,
            task=target.task,
        ):
            reasons.append("out-of-scope: target context is outside the promoted scope")
        if record.provenance.is_empty:
            reasons.append("no-provenance: promotion record has no trace ids or artifacts")

    if candidate.is_stale(now_ms):
        reasons.append(f"stale: refresh policy expired before now_ms={now_ms}")

    if not candidate.is_sanitized_clean:
        reasons.append(f"not-sanitized-clean: {len(candidate.findings)} finding(s)")

    if not can_roll_back(candidate):
        reasons.append(f"no-rollback-path: state {candidate.state.value} cannot be rolled back")

    return ActivationDecision(
        active=not reasons,
        candidate_id=candidate.id,
        reasons=tuple(reasons),
        promotion=record if not reasons else None,
        learning_enabled=enabled,
        target=target,
    )


def require_promoted(
    candidate: LearningCandidate,
    *,
    now_ms: int,
    target: ActivationTarget | None = None,
    env: Mapping[str, str] | None = None,
) -> PromotionRecord:
    """Prove *candidate* may be activated; return the record that authorizes it.

    Call this immediately before letting learned content influence an agent.
    Raises :class:`ActivationRefusedError` if any clause of the activation contract
    fails — including the ``ONMC_LEARNING`` kill switch being off — so an
    unproven activation can never proceed silently.
    """
    decision = check_activation(candidate, now_ms=now_ms, target=target, env=env)
    if not decision.active or decision.promotion is None:
        raise ActivationRefusedError(candidate.id, decision.reasons)
    return decision.promotion


def active_candidates(
    candidates: tuple[LearningCandidate, ...],
    *,
    now_ms: int,
    target: ActivationTarget | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[LearningCandidate, ...]:
    """Filter *candidates* down to those that pass :func:`check_activation`.

    The batch form for context-assembly call sites: hand it everything a store
    returned and only genuinely-promoted, in-scope, fresh artifacts come back.
    With the kill switch off this always returns ``()``.
    """
    return tuple(
        c
        for c in candidates
        if check_activation(c, now_ms=now_ms, target=target, env=env).active
    )


__all__ = [
    "LEARNING_ENABLED_ENV",
    "ActivationDecision",
    "ActivationRefusedError",
    "ActivationTarget",
    "active_candidates",
    "can_roll_back",
    "check_activation",
    "env_gate",
    "is_learning_enabled",
    "require_promoted",
]
