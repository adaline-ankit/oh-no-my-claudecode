"""Exhaustive tests for the pure proof-graph planning and evaluation core."""

from __future__ import annotations

import json

import pytest

from oh_no_my_claudecode.proof_graph import (
    Claim,
    ClaimKind,
    DiffMetadata,
    Evidence,
    EvidenceSource,
    Outcome,
    ProofReceipt,
    RiskMetadata,
    TaskKind,
    TaskMetadata,
    VerifierKind,
    VerifierResult,
    evaluate_proof,
    synthesize_proof_graph,
    verify_receipt,
)


def _bugfix_graph(*, changed_files: tuple[str, ...] = ("src/cache.py", "tests/test_cache.py")):
    return synthesize_proof_graph(
        TaskMetadata(
            task_id="cache-fix",
            summary="Cache invalidation returns stale values",
            kind=TaskKind.BUGFIX,
            claims=(
                Claim(
                    claim_id="bug-fixed",
                    statement="The stale-cache failure is fixed",
                    kind=ClaimKind.BUGFIX,
                ),
            ),
        ),
        RiskMetadata(),
        DiffMetadata(changed_files=changed_files, languages=("python",)),
    )


def _passing_results(graph):
    evidence = []
    results = []
    for node in graph.verifiers:
        item = Evidence(
            evidence_id=f"e-{node.verifier_id}",
            verifier_id=node.verifier_id,
            outcome=node.expected_outcome,
            artifact_digest=f"sha256:{node.verifier_id}",
            claim_ids=tuple(claim.claim_id for claim in graph.claims),
        )
        evidence.append(item)
        results.append(
            VerifierResult(
                verifier_id=node.verifier_id,
                outcome=node.expected_outcome,
                evidence_ids=(item.evidence_id,),
            )
        )
    return tuple(results), tuple(evidence)


def test_bugfix_plan_is_deterministic_and_dependency_ordered() -> None:
    first = _bugfix_graph()
    second = synthesize_proof_graph(first.task, first.risk, first.diff)

    assert first == second
    assert [node.kind for node in first.verifiers] == [
        VerifierKind.REPRODUCE,
        VerifierKind.TARGETED_TESTS,
        VerifierKind.REGRESSION,
        VerifierKind.STATIC_ANALYSIS,
        VerifierKind.TYPE_CHECK,
        VerifierKind.LINT,
    ]
    assert first.verifiers[0].expected_outcome is Outcome.FAILED
    assert first.verifiers[1].dependencies == (first.verifiers[0].verifier_id,)
    assert first.verifiers[2].dependencies == (first.verifiers[1].verifier_id,)
    assert all(isinstance(arg, str) for node in first.verifiers for arg in node.argv)


def test_feature_plan_does_not_require_a_pre_fix_failure() -> None:
    graph = synthesize_proof_graph(
        TaskMetadata(
            task_id="feature",
            summary="Add export",
            kind=TaskKind.FEATURE,
            claims=(Claim("export-works", "Export works", ClaimKind.BEHAVIOR),),
        ),
        RiskMetadata(),
        DiffMetadata(("src/export.py", "tests/test_export.py"), ("python",)),
    )

    assert VerifierKind.REPRODUCE not in {node.kind for node in graph.verifiers}
    assert graph.verifiers[0].kind is VerifierKind.TARGETED_TESTS
    assert graph.verifiers[0].dependencies == ()


def test_duplicate_result_error_names_conflicting_identifier() -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    duplicate = results + (results[0],)

    with pytest.raises(
        ValueError,
        match=f"duplicate verifier result id: {results[0].verifier_id}",
    ):
        evaluate_proof(graph, duplicate, evidence)


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        (RiskMetadata(security=True), VerifierKind.SECURITY),
        (RiskMetadata(browser=True), VerifierKind.BROWSER),
        (RiskMetadata(performance=True), VerifierKind.PERFORMANCE),
    ],
)
def test_risk_metadata_adds_applicable_verifier(risk, expected) -> None:
    graph = synthesize_proof_graph(
        TaskMetadata(
            "risky",
            "Risky change",
            TaskKind.FEATURE,
            (Claim("claim", "It works", ClaimKind.BEHAVIOR),),
        ),
        risk,
        DiffMetadata(("src/change.py",), ("python",)),
    )

    assert expected in {node.kind for node in graph.verifiers}


def test_diff_paths_infer_security_browser_and_performance_checks() -> None:
    graph = synthesize_proof_graph(
        TaskMetadata(
            "inferred",
            "Update sensitive web benchmark",
            TaskKind.FEATURE,
            (Claim("claim", "It works", ClaimKind.BEHAVIOR),),
        ),
        RiskMetadata(),
        DiffMetadata(
            ("src/auth/session.py", "web/login.tsx", "benchmarks/login.py"),
            ("python", "typescript"),
        ),
    )

    kinds = {node.kind for node in graph.verifiers}
    assert {VerifierKind.SECURITY, VerifierKind.BROWSER, VerifierKind.PERFORMANCE} <= kinds


def test_targeted_test_argv_is_derived_from_sorted_test_paths() -> None:
    graph = _bugfix_graph(changed_files=("tests/test_z.py", "src/z.py", "tests/test_a.py"))
    targeted = next(node for node in graph.verifiers if node.kind is VerifierKind.TARGETED_TESTS)

    assert targeted.argv == ("python", "-m", "pytest", "-q", "tests/test_a.py", "tests/test_z.py")


def test_synthesizer_rejects_missing_claims_and_empty_diffs() -> None:
    with pytest.raises(ValueError, match="claim"):
        synthesize_proof_graph(
            TaskMetadata("empty", "No claim", TaskKind.FEATURE),
            RiskMetadata(),
            DiffMetadata(("src/a.py",), ("python",)),
        )
    with pytest.raises(ValueError, match="changed file"):
        synthesize_proof_graph(
            TaskMetadata(
                "empty",
                "No diff",
                TaskKind.FEATURE,
                (Claim("c", "Claim", ClaimKind.BEHAVIOR),),
            ),
            RiskMetadata(),
            DiffMetadata(),
        )


@pytest.mark.parametrize(
    "task",
    [
        TaskMetadata(
            "",
            "Summary",
            TaskKind.FEATURE,
            (Claim("c", "Claim", ClaimKind.BEHAVIOR),),
        ),
        TaskMetadata(
            "task",
            "",
            TaskKind.FEATURE,
            (Claim("c", "Claim", ClaimKind.BEHAVIOR),),
        ),
        TaskMetadata(
            "task",
            "Summary",
            TaskKind.FEATURE,
            (Claim("c", "", ClaimKind.BEHAVIOR),),
        ),
    ],
)
def test_synthesizer_rejects_empty_task_and_claim_text(task: TaskMetadata) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        synthesize_proof_graph(
            task,
            RiskMetadata(),
            DiffMetadata(("src/a.py",), ("python",)),
        )


def test_complete_proof_requires_verifier_evidence_not_agent_assertion() -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    assessment = evaluate_proof(graph, results, evidence)
    assert assessment.complete is True
    assert assessment.false_green is False
    assert assessment.reasons == ()

    agent_evidence = tuple(
        Evidence(
            item.evidence_id,
            item.verifier_id,
            item.outcome,
            item.artifact_digest,
            item.claim_ids,
            source=EvidenceSource.AGENT,
        )
        for item in evidence
    )
    rejected = evaluate_proof(graph, results, agent_evidence)
    assert rejected.complete is False
    assert "agent assertions are not verifier evidence" in rejected.reasons


def test_bugfix_requires_pre_fix_failure_and_post_fix_pass() -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    reproduce_id = graph.verifiers[0].verifier_id
    wrong = tuple(
        VerifierResult(item.verifier_id, Outcome.PASSED, item.evidence_ids)
        if item.verifier_id == reproduce_id
        else item
        for item in results
    )

    assessment = evaluate_proof(graph, wrong, evidence)
    assert assessment.complete is False
    assert assessment.false_green is True
    assert "bugfix lacks a demonstrated pre-fix failure" in assessment.reasons


def test_bugfix_rejects_same_artifact_for_pre_and_post_fix() -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    reproduce_id = graph.verifiers[0].verifier_id
    targeted_id = graph.verifiers[1].verifier_id
    shared = "sha256:identical"
    evidence = tuple(
        Evidence(
            item.evidence_id,
            item.verifier_id,
            item.outcome,
            shared if item.verifier_id in {reproduce_id, targeted_id} else item.artifact_digest,
            item.claim_ids,
        )
        for item in evidence
    )

    assessment = evaluate_proof(graph, results, evidence)
    assert assessment.complete is False
    assert assessment.false_green is True
    assert "pre-fix and post-fix evidence are identical" in assessment.reasons


def test_every_claim_must_map_to_evidence_from_every_required_verifier() -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    first = evidence[0]
    evidence = (
        Evidence(
            first.evidence_id,
            first.verifier_id,
            first.outcome,
            first.artifact_digest,
            (),
        ),
        *evidence[1:],
    )

    assessment = evaluate_proof(graph, results, evidence)
    assert assessment.complete is False
    assert "claim bug-fixed has no evidence from reproduce" in assessment.reasons


@pytest.mark.parametrize("mutation", ["missing", "failed", "digestless", "orphan"])
def test_false_green_detection_for_incomplete_or_inconsistent_results(mutation: str) -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    target = graph.verifiers[-1]
    if mutation == "missing":
        results = results[:-1]
    elif mutation == "failed":
        results = (*results[:-1], VerifierResult(target.verifier_id, Outcome.FAILED, ()))
    elif mutation == "digestless":
        last = evidence[-1]
        evidence = (
            *evidence[:-1],
            Evidence(last.evidence_id, last.verifier_id, last.outcome, "", last.claim_ids),
        )
    else:
        results = (*results, VerifierResult("unknown-verifier", Outcome.PASSED, ()))

    assessment = evaluate_proof(graph, results, evidence)
    assert assessment.complete is False
    assert assessment.false_green is True
    assert assessment.reasons


def test_dependency_failure_prevents_downstream_success() -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    targeted = graph.verifiers[1]
    reproduce = graph.verifiers[0]
    results = tuple(
        VerifierResult(item.verifier_id, Outcome.PASSED, item.evidence_ids)
        if item.verifier_id == reproduce.verifier_id
        else item
        for item in results
    )

    assessment = evaluate_proof(graph, results, evidence)
    assert assessment.complete is False
    assert f"{targeted.verifier_id} passed without satisfied dependencies" in assessment.reasons


def test_duplicate_result_or_evidence_ids_are_rejected() -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    with pytest.raises(ValueError, match="duplicate verifier result"):
        evaluate_proof(graph, (*results, results[0]), evidence)
    with pytest.raises(ValueError, match="duplicate evidence"):
        evaluate_proof(graph, results, (*evidence, evidence[0]))


def test_receipt_serialization_is_stable_and_tamper_evident() -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    assessment = evaluate_proof(graph, tuple(reversed(results)), tuple(reversed(evidence)))
    receipt = ProofReceipt.build(
        graph,
        assessment,
        tuple(reversed(results)),
        tuple(reversed(evidence)),
    )

    serialized = receipt.to_json()
    rebuilt = ProofReceipt.build(graph, assessment, results, evidence)
    assert serialized == rebuilt.to_json()
    assert serialized == receipt.to_json()
    assert verify_receipt(serialized) is True
    assert ProofReceipt.from_json(serialized) == receipt

    payload = json.loads(serialized)
    payload["assessment"]["complete"] = False
    tampered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert verify_receipt(tampered) is False
    with pytest.raises(ValueError, match="integrity"):
        ProofReceipt.from_json(tampered)


def test_receipt_hash_changes_when_evidence_changes() -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    assessment = evaluate_proof(graph, results, evidence)
    original = ProofReceipt.build(graph, assessment, results, evidence)
    changed = list(evidence)
    item = changed[-1]
    changed[-1] = Evidence(
        item.evidence_id,
        item.verifier_id,
        item.outcome,
        "sha256:different-output",
        item.claim_ids,
    )
    changed_assessment = evaluate_proof(graph, results, tuple(changed))
    altered = ProofReceipt.build(graph, changed_assessment, results, tuple(changed))

    assert original.receipt_hash != altered.receipt_hash


def test_failed_assessment_is_stable_across_input_order() -> None:
    graph = _bugfix_graph()
    results, evidence = _passing_results(graph)
    agent_evidence = tuple(
        Evidence(
            item.evidence_id,
            item.verifier_id,
            item.outcome,
            item.artifact_digest,
            item.claim_ids,
            EvidenceSource.AGENT,
        )
        for item in evidence
    )

    forward = evaluate_proof(graph, results, agent_evidence)
    reverse = evaluate_proof(graph, tuple(reversed(results)), tuple(reversed(agent_evidence)))
    assert forward == reverse


def test_receipt_rejects_correctly_hashed_but_invalid_envelope() -> None:
    import hashlib

    invalid = {"schema_version": "1"}
    canonical = json.dumps(invalid, sort_keys=True, separators=(",", ":"))
    invalid["receipt_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    serialized = json.dumps(invalid, sort_keys=True, separators=(",", ":"))

    assert verify_receipt(serialized) is False
    with pytest.raises(ValueError, match="integrity"):
        ProofReceipt.from_json(serialized)


def test_core_is_planning_and_evaluation_only() -> None:
    """The package must expose plans, never an execution entrypoint."""
    import oh_no_my_claudecode.proof_graph as proof_graph

    assert not hasattr(proof_graph, "run")
    assert not hasattr(proof_graph, "execute")
