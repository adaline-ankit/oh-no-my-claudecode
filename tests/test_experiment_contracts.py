"""Tests for the frozen SOTA experiment contracts."""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.experiment import (
    AdapterCapabilities,
    ArtifactRef,
    BenchmarkAuditStatus,
    CandidateState,
    Condition,
    Environment,
    ExperimentId,
    ExperimentManifest,
    MetricLabel,
    RunId,
    TrialResult,
    is_legal_transition,
)
from oh_no_my_claudecode.experiment.contracts import _CANDIDATE_TRANSITIONS


def _env() -> Environment:
    return Environment(code_sha="abc123", config_hash="cfg", model="m", provider="p")


def _manifest(trials: int = 3) -> ExperimentManifest:
    return ExperimentManifest(
        experiment_id=ExperimentId("exp-billing-flaky"),
        task_set_revision="rev-1",
        conditions=(Condition.BARE_AGENT, Condition.ONMC_CURRENT, Condition.ONMC_CANDIDATE),
        trials=trials,
        seed=7,
        environment=_env(),
    )


def test_experiment_id_rejects_bad_slugs() -> None:
    with pytest.raises(ValueError, match="experiment id"):
        ExperimentId("Bad Id!")


def test_run_id_slug_is_deterministic_and_safe() -> None:
    rid = RunId("exp-1", Condition.ONMC_CANDIDATE, "fix flaky billing", 2)
    assert rid.slug == "exp-1.onmc-candidate.fix-flaky-billing.t2"


def test_manifest_requires_two_distinct_conditions() -> None:
    with pytest.raises(ValueError, match="two distinct conditions"):
        ExperimentManifest(
            experiment_id=ExperimentId("exp-1"),
            task_set_revision="r",
            conditions=(Condition.BARE_AGENT,),
            trials=1,
            seed=0,
            environment=_env(),
        )


def test_manifest_requires_frozen_task_set() -> None:
    with pytest.raises(ValueError, match="task_set_revision"):
        ExperimentManifest(
            experiment_id=ExperimentId("exp-1"),
            task_set_revision="  ",
            conditions=(Condition.BARE_AGENT, Condition.ONMC_CURRENT),
            trials=1,
            seed=0,
            environment=_env(),
        )


def test_manifest_uncertainty_flag_and_default_audit_status() -> None:
    assert _manifest(trials=3).requires_uncertainty is True
    assert _manifest(trials=1).requires_uncertainty is False
    # A benchmark is suspect until explicitly audited valid.
    assert _manifest().audit_status is BenchmarkAuditStatus.SUSPECT


def test_manifest_json_is_byte_stable() -> None:
    assert _manifest().to_json() == _manifest().to_json()


def test_artifact_ref_is_content_addressed() -> None:
    ref = ArtifactRef.of(b"diff --git a b", "text/x-patch")
    assert ref.size_bytes == len(b"diff --git a b")
    assert ArtifactRef.of(b"diff --git a b", "text/x-patch") == ref
    with pytest.raises(ValueError, match="64 lowercase hex"):
        ArtifactRef("nothex", "text/plain", 1)


def test_trial_result_rejects_negative_metrics() -> None:
    rid = RunId("exp-1", Condition.BARE_AGENT, "t", 0)
    with pytest.raises(ValueError, match="cost_usd"):
        TrialResult(rid, passed=True, cost_usd=-1.0)


def test_trial_result_defaults_to_measured() -> None:
    rid = RunId("exp-1", Condition.BARE_AGENT, "t", 0)
    assert TrialResult(rid, passed=True).metric_label is MetricLabel.MEASURED


def test_adapter_without_enforcement_is_advisory() -> None:
    adapter = AdapterCapabilities(name="claude", supports_real_run=True)
    assert adapter.advisory_only is True
    enforced = AdapterCapabilities(name="claude", supports_real_run=True, enforced_effects=True)
    assert enforced.advisory_only is False


def test_candidate_cannot_skip_to_promoted() -> None:
    # A candidate must be shadow-evaluated before promotion — no shortcuts.
    assert not is_legal_transition(CandidateState.CANDIDATE, CandidateState.PROMOTED)
    assert not is_legal_transition(CandidateState.OBSERVED, CandidateState.PROMOTED)
    assert is_legal_transition(CandidateState.SHADOW_EVALUATED, CandidateState.PROMOTED)


def test_any_active_state_can_roll_back() -> None:
    terminal = {CandidateState.SUPERSEDED, CandidateState.ROLLED_BACK}
    # OBSERVED is pre-candidate — nothing is applied yet, so it only advances.
    non_rollbackable = terminal | {CandidateState.OBSERVED}
    for state, targets in _CANDIDATE_TRANSITIONS.items():
        if state in terminal:
            assert targets == frozenset()
        elif state not in non_rollbackable:
            assert CandidateState.ROLLED_BACK in targets


def test_promoted_is_reachable_only_through_full_pipeline() -> None:
    order = [
        CandidateState.OBSERVED,
        CandidateState.CANDIDATE,
        CandidateState.SANITIZED,
        CandidateState.SCOPED,
        CandidateState.SHADOW_EVALUATED,
        CandidateState.PROMOTED,
        CandidateState.MONITORED,
    ]
    for src, dst in zip(order[:-1], order[1:], strict=True):
        assert is_legal_transition(src, dst)
