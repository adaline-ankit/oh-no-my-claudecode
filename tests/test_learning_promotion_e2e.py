"""End-to-end contract tests for quarantined, prediction-backed learning."""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.experiment.contracts import (
    ArtifactRef,
    CandidateState,
    MetricLabel,
)
from oh_no_my_claudecode.learning import (
    ActivationRefusedError,
    AdvanceEvent,
    CandidateKind,
    LearningCandidate,
    Provenance,
    Scope,
    ShadowEvaluation,
    advance,
    require_promoted,
)
from oh_no_my_claudecode.learning.candidate_registry import (
    CandidateConflictError,
    CandidateDisposition,
    CandidateRegistry,
)
from oh_no_my_claudecode.learning.prediction import (
    LearningComponent,
    PromotionPrediction,
)
from oh_no_my_claudecode.learning.promotion import (
    GovernedPromotionService,
    PromotionManifest,
)


def _candidate(candidate_id: str = "cand-router-memory") -> LearningCandidate:
    candidate = LearningCandidate(
        id=candidate_id,
        kind=CandidateKind.STRATEGY,
        content="Escalate only after a repeated cross-module verifier failure.",
        provenance=Provenance(
            trace_ids=("trace-held-out-001",),
            artifacts=(ArtifactRef.of(b"trajectory", "application/json"),),
        ),
        scope=Scope(repos=("org/repo",), tasks=("fix-*",)),
    )
    candidate = advance(candidate, AdvanceEvent(to=CandidateState.CANDIDATE, at_ms=1))
    candidate = advance(candidate, AdvanceEvent(to=CandidateState.SANITIZED, at_ms=2))
    candidate = advance(
        candidate,
        AdvanceEvent(to=CandidateState.SCOPED, scope=candidate.scope, at_ms=3),
    )
    return candidate


def _evaluation(
    *,
    candidate_score: float = 0.82,
    control_score: float = 0.70,
    protected_suite_passed: bool = True,
    held_out: bool = True,
) -> ShadowEvaluation:
    return ShadowEvaluation(
        candidate_score=candidate_score,
        control_score=control_score,
        sample_size=50,
        protected_suite_passed=protected_suite_passed,
        metric_label=MetricLabel.MEASURED,
        held_out=held_out,
    )


def _shadow_candidate(
    *,
    candidate_id: str = "cand-router-memory",
    evaluation: ShadowEvaluation | None = None,
) -> LearningCandidate:
    candidate = _candidate(candidate_id)
    return advance(
        candidate,
        AdvanceEvent(
            to=CandidateState.SHADOW_EVALUATED,
            evaluation=evaluation or _evaluation(),
            at_ms=4,
        ),
    )


def _manifest(
    evaluation: ShadowEvaluation,
    *,
    component: LearningComponent = LearningComponent.MEMORY,
    dataset_revision: str = "heldout-v7@sha256:abc123",
    protected_non_regression: bool = True,
    rollback_pointer: str = "refs/onmc-learning/router-memory@v0",
) -> PromotionManifest:
    return PromotionManifest(
        prediction=PromotionPrediction(
            component=component,
            metric="verified_pass_rate",
            minimum_effect=0.05,
            task_slice="cross-module-fixes",
            risk="May over-escalate simple tasks.",
        ),
        dataset_revision=dataset_revision,
        held_out_result=evaluation,
        protected_non_regression=protected_non_regression,
        rollback_pointer=rollback_pointer,
    )


def test_candidate_is_quarantined_by_default_and_cannot_activate() -> None:
    candidate = _shadow_candidate()
    registry = CandidateRegistry()

    record = registry.register(candidate, _manifest(candidate.evaluation))  # type: ignore[arg-type]

    assert record.disposition is CandidateDisposition.QUARANTINED
    assert record.candidate.is_active(now_ms=10) is False
    with pytest.raises(ActivationRefusedError):
        require_promoted(record.candidate, now_ms=10)


def test_missing_governance_evidence_remains_quarantined() -> None:
    candidate = _shadow_candidate()
    registry = CandidateRegistry()
    service = GovernedPromotionService(registry)
    manifest = PromotionManifest()

    record = service.promote(candidate, manifest, at_ms=10)

    assert record.disposition is CandidateDisposition.QUARANTINED
    assert record.decision is not None
    assert set(record.decision.reasons) >= {
        "prediction-missing",
        "dataset-revision-missing",
        "held-out-result-missing",
        "protected-non-regression-missing",
        "rollback-pointer-missing",
    }


def test_training_gain_with_held_out_regression_stays_quarantined() -> None:
    regression = _evaluation(candidate_score=0.64, control_score=0.70)
    candidate = _shadow_candidate(evaluation=regression)
    service = GovernedPromotionService(CandidateRegistry())

    record = service.promote(candidate, _manifest(regression), at_ms=10)

    assert record.disposition is CandidateDisposition.QUARANTINED
    assert record.decision is not None
    assert "held-out-improvement-below-prediction" in record.decision.reasons


def test_protected_suite_regression_stays_quarantined() -> None:
    regression = _evaluation(protected_suite_passed=False)
    candidate = _shadow_candidate(evaluation=regression)
    service = GovernedPromotionService(CandidateRegistry())

    record = service.promote(
        candidate,
        _manifest(regression, protected_non_regression=False),
        at_ms=10,
    )

    assert record.disposition is CandidateDisposition.QUARANTINED
    assert record.decision is not None
    assert "protected-non-regression-missing" in record.decision.reasons
    assert "protected-suite-regression" in record.decision.reasons


def test_eligible_candidate_promotes_with_complete_governance_receipt() -> None:
    candidate = _shadow_candidate()
    assert candidate.evaluation is not None
    registry = CandidateRegistry()
    service = GovernedPromotionService(registry)
    manifest = _manifest(candidate.evaluation)

    record = service.promote(candidate, manifest, at_ms=10, reason="pre-registered gate passed")

    assert record.disposition is CandidateDisposition.PROMOTED
    assert record.decision is not None and record.decision.eligible
    assert record.candidate.state is CandidateState.PROMOTED
    assert record.candidate.is_active(now_ms=11)
    assert record.manifest.dataset_revision == "heldout-v7@sha256:abc123"
    assert record.manifest.rollback_pointer == "refs/onmc-learning/router-memory@v0"
    assert record.manifest.prediction is not None
    assert record.manifest.prediction.component is LearningComponent.MEMORY
    assert require_promoted(record.candidate, now_ms=11).reason == "pre-registered gate passed"


def test_rollback_deactivates_but_preserves_prediction_and_evidence() -> None:
    candidate = _shadow_candidate()
    assert candidate.evaluation is not None
    registry = CandidateRegistry()
    service = GovernedPromotionService(registry)
    promoted = service.promote(candidate, _manifest(candidate.evaluation), at_ms=10)

    rolled_back = service.rollback(promoted.candidate.id, at_ms=20, reason="held-out drift")

    assert rolled_back.disposition is CandidateDisposition.ROLLED_BACK
    assert rolled_back.candidate.state is CandidateState.ROLLED_BACK
    assert rolled_back.candidate.is_active(now_ms=21) is False
    assert rolled_back.manifest.dataset_revision == promoted.manifest.dataset_revision
    assert rolled_back.manifest.rollback_pointer == promoted.manifest.rollback_pointer
    assert rolled_back.decision == promoted.decision


def test_same_candidate_and_manifest_are_idempotent_but_conflicts_fail() -> None:
    candidate = _shadow_candidate()
    assert candidate.evaluation is not None
    registry = CandidateRegistry()
    service = GovernedPromotionService(registry)
    manifest = _manifest(candidate.evaluation)

    first = service.promote(candidate, manifest, at_ms=10)
    repeated = service.promote(candidate, manifest, at_ms=99)

    assert repeated is first
    assert repeated.candidate.version == 1

    conflicting = _manifest(candidate.evaluation, dataset_revision="heldout-v8@sha256:def456")
    with pytest.raises(CandidateConflictError):
        service.promote(candidate, conflicting, at_ms=100)


def test_component_identity_keeps_prompt_and_memory_experiments_separate() -> None:
    memory_candidate = _shadow_candidate(candidate_id="cand-memory-policy")
    prompt_candidate = _shadow_candidate(candidate_id="cand-prompt-policy")
    assert memory_candidate.evaluation is not None
    assert prompt_candidate.evaluation is not None
    registry = CandidateRegistry()

    memory = registry.register(
        memory_candidate,
        _manifest(memory_candidate.evaluation, component=LearningComponent.MEMORY),
    )
    prompt = registry.register(
        prompt_candidate,
        _manifest(prompt_candidate.evaluation, component=LearningComponent.PROMPT),
    )

    assert memory.manifest.prediction is not None
    assert prompt.manifest.prediction is not None
    assert memory.manifest.prediction.component is LearningComponent.MEMORY
    assert prompt.manifest.prediction.component is LearningComponent.PROMPT
    assert memory.manifest_digest != prompt.manifest_digest
