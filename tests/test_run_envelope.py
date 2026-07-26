"""Tests for the complete run envelope (:mod:`oh_no_my_claudecode.trace.envelope`).

Covers the Milestone 1 acceptance criteria:

- a concurrent/nested envelope stays structurally valid;
- a saved envelope round-trips and its receipt verifies offline;
- secret fixtures are ABSENT from the exported envelope + receipt (redaction);
- estimated vs measured metrics are labelled;
- tampering the envelope fails receipt verification.

The envelope is a composition layer, so these tests also exercise the reused
pieces: :class:`RunId` / :class:`ArtifactRef` / :class:`MetricLabel` /
:class:`CandidateState` from the experiment contracts, :class:`TraceEvent` from
the trace models, and the sealed :class:`HarnessRunReceipt`.
"""

from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.experiment.contracts import (
    ArtifactRef,
    CandidateState,
    Condition,
    MetricLabel,
    RunId,
)
from oh_no_my_claudecode.harness_run.receipt import HarnessRunReceipt
from oh_no_my_claudecode.harness_run.run_policy import RunPolicyDecision
from oh_no_my_claudecode.harness_run.stages import StageName, StageRecord, StageStatus
from oh_no_my_claudecode.proof_graph import ProofAssessment
from oh_no_my_claudecode.trace.envelope import (
    ContextCandidate,
    EnvelopeEvent,
    EventCategory,
    GitState,
    LearningCandidateRef,
    Metric,
    RunEnvelope,
    TestOutcome,
    verify_envelope,
)
from oh_no_my_claudecode.trace.models import TraceEvent, TraceEventKind

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

SECRET_TOKEN = "sk-supersecret_ABCDEF0123456789abcd"  # noqa: S105 — test fixture
SECRET_PASSWORD = "hunter2-not-in-output"  # noqa: S105 — test fixture


def _run_id() -> RunId:
    return RunId(
        experiment_id="exp-envelope",
        condition=Condition.ONMC_CURRENT,
        task_id="task-42",
        trial=0,
    )


def _verified_harness_receipt() -> HarnessRunReceipt:
    """Build a genuine, verifying harness receipt to embed (reuse, not reinvent)."""
    proof = ProofAssessment(complete=True, false_green=False, reasons=())
    policy = RunPolicyDecision(allowed=True, approvals_required=False, violations=())
    stages = tuple(
        StageRecord(
            name=name,
            status=StageStatus.SUCCEEDED,
            summary=f"{name.value} ok",
        )
        for name in StageName
    )
    return HarnessRunReceipt.build(
        run_id="run-xyz",
        task="do the thing",
        status="completed",
        completed=True,
        stages=stages,
        policy=policy,
        proof=proof,
    )


def _nested_events() -> tuple[EnvelopeEvent, ...]:
    """A tree: a model turn, then two *concurrent* sub-agents each with children."""
    tool_a = EnvelopeEvent(
        category=EventCategory.TOOL,
        event=TraceEvent(kind=TraceEventKind.TOOL_CALL, payload={"tool": "read", "target": "a.py"}),
    )
    retry_a = EnvelopeEvent(
        category=EventCategory.RETRY,
        event=TraceEvent(kind=TraceEventKind.TOOL_FAILURE, payload={"tool": "read"}),
    )
    subagent_1 = EnvelopeEvent(
        category=EventCategory.SUBAGENT,
        event=TraceEvent(kind=TraceEventKind.GENERIC, payload={"title": "sub-1"}),
        children=(tool_a, retry_a),
    )
    subagent_2 = EnvelopeEvent(
        category=EventCategory.SUBAGENT,
        event=TraceEvent(kind=TraceEventKind.GENERIC, payload={"title": "sub-2"}),
        children=(
            EnvelopeEvent(
                category=EventCategory.HANDOFF,
                event=TraceEvent(kind=TraceEventKind.GENERIC, payload={"title": "handoff"}),
            ),
        ),
    )
    model = EnvelopeEvent(
        category=EventCategory.MODEL,
        event=TraceEvent(kind=TraceEventKind.TOKENS, payload={"total": 1200}),
        children=(subagent_1, subagent_2),  # concurrent siblings
    )
    verifier = EnvelopeEvent(
        category=EventCategory.VERIFIER,
        event=TraceEvent(kind=TraceEventKind.GENERIC, payload={"title": "pytest"}),
    )
    return (model, verifier)


def _envelope(*, with_secret: bool = False) -> RunEnvelope:
    patch = ArtifactRef.of(b"--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n", "text/x-diff")
    candidates = (
        ContextCandidate(
            candidate_id="cand-selected",
            selected=True,
            reason="top BM25 + semantic match",
            score_components={"bm25": 0.82, "semantic": 0.71},
            token_cost=340,
            index_revision="idx-2026-07-24",
            fallback=False,
        ),
        ContextCandidate(
            candidate_id="cand-rejected",
            selected=False,
            reason="below score floor; fallback path",
            score_components={"bm25": 0.11},
            token_cost=0,
            index_revision="idx-2026-07-24",
            fallback=True,
        ),
    )
    costs = {
        "cost_usd": Metric(value=0.0123, label=MetricLabel.MEASURED, unit="usd"),
        "latency_ms": Metric(value=8421.0, label=MetricLabel.MEASURED, unit="ms"),
        # deliberately estimated — no live token meter on this path
        "tokens_saved": Metric(value=1800.0, label=MetricLabel.ESTIMATED, unit="tokens"),
    }
    branch = "feat/sota-run-envelope"
    reason_extra = ""
    if with_secret:
        # Plant secrets in free-text/provenance fields to prove redaction.
        branch = f"feat/{SECRET_TOKEN}"
        reason_extra = f" auth={SECRET_TOKEN} password={SECRET_PASSWORD}"

    return RunEnvelope(
        run_id=_run_id(),
        created_at=1_780_000_000.0,
        events=_nested_events(),
        context_candidates=(
            ContextCandidate(
                candidate_id="cand-selected",
                selected=True,
                reason="top BM25 + semantic match" + reason_extra,
                score_components={"bm25": 0.82, "semantic": 0.71},
                token_cost=340,
                index_revision="idx-2026-07-24",
                fallback=False,
            ),
            candidates[1],
        ),
        git=GitState(branch=branch, head_sha="deadbeef", dirty=True, patch=patch),
        tests=(
            TestOutcome(name="test_ok", passed=True, label=MetricLabel.MEASURED, duration_ms=12.0),
            TestOutcome(name="test_flaky", passed=False, label=MetricLabel.ESTIMATED),
        ),
        artifacts=(patch,),
        costs=costs,
        learning_candidates=(
            LearningCandidateRef(
                candidate_id="lc-1",
                state=CandidateState.OBSERVED,
                artifact=ArtifactRef.of(b"note", "text/plain"),
            ),
        ),
        harness_receipt=_verified_harness_receipt().to_dict(),
        secret_values=(SECRET_TOKEN, SECRET_PASSWORD) if with_secret else (),
    )


# ---------------------------------------------------------------------------
# Structural validity (concurrent / nested)
# ---------------------------------------------------------------------------


def test_nested_concurrent_envelope_is_structurally_valid() -> None:
    env = _envelope()
    assert env.structural_errors() == []
    assert env.is_structurally_valid is True

    # The nested tree flattens to every event we placed (model + 2 sub-agents,
    # their children, plus the verifier) — nesting is preserved, not lost.
    flat = [e for top in env.events for e in top.iter_flat()]
    categories = sorted({e.category for e in flat})
    assert EventCategory.SUBAGENT in categories
    assert EventCategory.HANDOFF in categories
    assert EventCategory.RETRY in categories
    assert len(flat) == 7  # model, sub1, tool_a, retry_a, sub2, handoff, verifier


def test_duplicate_context_candidate_ids_are_flagged() -> None:
    env = RunEnvelope(
        run_id=_run_id(),
        created_at=1.0,
        context_candidates=(
            ContextCandidate(candidate_id="dup", selected=True, reason="a"),
            ContextCandidate(candidate_id="dup", selected=False, reason="b"),
        ),
    )
    errors = env.structural_errors()
    assert any("duplicate context candidate id" in e for e in errors)
    assert env.is_structurally_valid is False


# ---------------------------------------------------------------------------
# Round-trip + offline receipt verification
# ---------------------------------------------------------------------------


def test_envelope_roundtrips_and_receipt_verifies_offline(tmp_path: Path) -> None:
    env = _envelope()

    # byte-stable: serialising twice gives identical bytes
    assert env.to_json() == env.to_json()

    # structural round-trip: parsed dict equals to_dict()
    serialized = env.to_json()
    assert json.loads(serialized) == env.to_dict()

    # save to disk, read back, verify offline (no access to the RunEnvelope)
    saved = tmp_path / "envelope.json"
    saved.write_text(serialized, encoding="utf-8")
    reloaded = saved.read_text(encoding="utf-8")

    assert verify_envelope(reloaded) is True
    assert env.verify() is True

    # the receipt is content-addressed (sha256 present, matches ArtifactRef)
    receipt = json.loads(reloaded)["receipt"]
    assert len(receipt["sha256"]) == 64
    assert receipt["media_type"].endswith("run-envelope+json")


def test_embedded_harness_receipt_still_verifies_inside_envelope() -> None:
    env = _envelope()
    body = json.loads(env.to_json())
    # the embedded verified receipt is present and internally consistent
    assert body["harness_receipt"]["verified"] is True
    # and verify_envelope re-checks it as part of overall verification
    assert verify_envelope(env.to_json()) is True


# ---------------------------------------------------------------------------
# Redaction — secrets must be absent from envelope AND receipt
# ---------------------------------------------------------------------------


def test_secrets_absent_from_exported_envelope_and_receipt() -> None:
    env = _envelope(with_secret=True)
    serialized = env.to_json()

    # No secret value leaks into the serialised envelope (body or receipt).
    assert SECRET_TOKEN not in serialized
    assert SECRET_PASSWORD not in serialized

    # secret_values are redaction inputs only — never serialised as a field.
    assert "secret_values" not in json.loads(serialized)

    # The redacted envelope is still internally consistent and verifiable.
    assert verify_envelope(serialized) is True

    # Sanity: SECRET_PASSWORD does not match any built-in token pattern, so it
    # only disappears via secret_values. Without redaction inputs it survives —
    # proving the redaction above (not a pattern match) is what removed it.
    leaky = RunEnvelope(
        run_id=_run_id(),
        created_at=1.0,
        git=GitState(branch=f"feat/{SECRET_PASSWORD}", head_sha="x"),
        secret_values=(),  # no redaction
    )
    assert SECRET_PASSWORD in leaky.to_json()


# ---------------------------------------------------------------------------
# Metric labelling — measured vs estimated
# ---------------------------------------------------------------------------


def test_every_metric_is_labelled_measured_or_estimated() -> None:
    env = _envelope()
    body = json.loads(env.to_json())

    for name, metric in body["costs"].items():
        assert metric["label"] in {MetricLabel.MEASURED.value, MetricLabel.ESTIMATED.value}, name

    labels = {name: metric["label"] for name, metric in body["costs"].items()}
    assert labels["cost_usd"] == MetricLabel.MEASURED.value
    assert labels["tokens_saved"] == MetricLabel.ESTIMATED.value

    # test outcomes are labelled too
    test_labels = {t["name"]: t["label"] for t in body["tests"]}
    assert test_labels["test_ok"] == MetricLabel.MEASURED.value
    assert test_labels["test_flaky"] == MetricLabel.ESTIMATED.value


def test_metric_estimated_property_and_validation() -> None:
    assert Metric(1.0, MetricLabel.ESTIMATED).estimated is True
    assert Metric(1.0, MetricLabel.MEASURED).estimated is False
    for bad in (True, "1.0", None):
        try:
            Metric(bad)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:  # pragma: no cover - failure path
            raise AssertionError(f"Metric accepted invalid value {bad!r}")


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


def test_tampering_any_field_fails_receipt_verification() -> None:
    env = _envelope()
    body = json.loads(env.to_json())

    # 1. flip a verified test outcome
    tampered = json.loads(env.to_json())
    tampered["tests"][1]["passed"] = True
    assert verify_envelope(json.dumps(tampered)) is False

    # 2. inflate a cost metric while keeping the old receipt
    tampered = json.loads(env.to_json())
    tampered["costs"]["cost_usd"]["value"] = 0.0
    assert verify_envelope(json.dumps(tampered)) is False

    # 3. rewrite the git head while keeping the old receipt
    tampered = json.loads(env.to_json())
    tampered["git"]["head_sha"] = "0" * 8
    assert verify_envelope(json.dumps(tampered)) is False

    # 4. tamper the embedded harness receipt's verdict
    tampered = json.loads(env.to_json())
    tampered["harness_receipt"]["verified"] = False
    # body hash also changes, but even the embedded-receipt check would catch it
    assert verify_envelope(json.dumps(tampered)) is False

    # 5. dropping the receipt entirely fails
    no_receipt = {k: v for k, v in body.items() if k != "receipt"}
    assert verify_envelope(json.dumps(no_receipt)) is False

    # 6. malformed input never raises, just returns False
    assert verify_envelope("not json") is False
    assert verify_envelope("[]") is False
