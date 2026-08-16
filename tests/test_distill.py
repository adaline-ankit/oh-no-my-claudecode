"""R2 distillation: verified-only mining, normalization, maximality, gate-ready."""

from __future__ import annotations

from oh_no_my_claudecode.learning.distill import distill_workflows, normalize_step
from oh_no_my_claudecode.learning.models import CandidateKind, CandidateState


def _receipt(rid: str, actions: list[str], *, verified: bool = True) -> dict[str, object]:
    return {
        "receipt_hash": rid,
        "verified": verified,
        "iterations": [{"action_summary": a} for a in actions],
    }


WORKFLOW_A = [
    "reproduce the bug with a failing test in tests/test_auth.py",
    "trace the root cause in src/auth.py",
    "apply the fix and rerun pytest 3 times",
]
WORKFLOW_A_VARIANT = [
    "reproduce the bug with a failing test in tests/test_billing.py",
    "trace the root cause in lib/billing.py",
    "apply the fix and rerun pytest 12 times",
]


def test_normalization_collapses_specifics_to_procedure() -> None:
    assert normalize_step(WORKFLOW_A[0]) == normalize_step(WORKFLOW_A_VARIANT[0])
    assert "<file>" in normalize_step(WORKFLOW_A[1])
    assert "<n>" in normalize_step(WORKFLOW_A[2])


def test_mines_recurring_workflow_from_verified_runs_only() -> None:
    receipts = [
        _receipt("r1", WORKFLOW_A),
        _receipt("r2", WORKFLOW_A_VARIANT),
        _receipt("r3", WORKFLOW_A, verified=False),  # unverified never teaches
        _receipt("r4", ["update the readme wording", "publish release notes"]),
    ]
    candidates = distill_workflows(receipts, min_support=2)
    assert len(candidates) == 1
    top = candidates[0]
    assert top.support == ("r1", "r2")  # r3 excluded despite matching steps
    assert len(top.steps) == 3  # maximal: the 2-step fragments are suppressed
    assert "reproduce the bug" in top.steps[0]

    # Deterministic
    assert distill_workflows(receipts, min_support=2) == candidates


def test_candidate_is_gate_ready_skill_with_provenance() -> None:
    receipts = [_receipt("r1", WORKFLOW_A), _receipt("r2", WORKFLOW_A_VARIANT)]
    candidate = distill_workflows(receipts, min_support=2)[0].to_learning_candidate(repo="acme/api")
    assert candidate.kind is CandidateKind.SKILL
    assert candidate.state is CandidateState.OBSERVED  # enters at the gate's front door
    assert candidate.provenance.trace_ids == ("r1", "r2")
    assert candidate.scope.repos == ("acme/api",)
    assert "Learned workflow" in candidate.content and "1." in candidate.content
