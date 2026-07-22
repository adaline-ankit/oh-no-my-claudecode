"""Pure proof-graph evaluation and false-green detection."""

from __future__ import annotations

from oh_no_my_claudecode.proof_graph.models import (
    Evidence,
    EvidenceSource,
    Outcome,
    ProofAssessment,
    ProofGraph,
    TaskKind,
    VerifierKind,
    VerifierResult,
)


def _unique_by_id(items: tuple[object, ...], attribute: str, label: str) -> None:
    identifiers = [str(getattr(item, attribute)) for item in items]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"duplicate {label} id")


def evaluate_proof(
    graph: ProofGraph,
    results: tuple[VerifierResult, ...],
    evidence: tuple[Evidence, ...],
) -> ProofAssessment:
    """Evaluate externally collected results against a proof graph.

    This function performs no I/O. A node is satisfied only when its observed
    outcome matches the plan and it carries content-addressed evidence from a
    verifier. Every claim must be named by evidence from every planned node.
    """
    _unique_by_id(results, "verifier_id", "verifier result")
    _unique_by_id(evidence, "evidence_id", "evidence")

    nodes = {node.verifier_id: node for node in graph.verifiers}
    result_by_id = {result.verifier_id: result for result in results}
    evidence_by_id = {item.evidence_id: item for item in evidence}
    reasons: list[str] = []

    for result in results:
        if result.verifier_id not in nodes:
            reasons.append(f"orphan result for unknown verifier {result.verifier_id}")
    for item in evidence:
        if item.verifier_id not in nodes:
            reasons.append(f"orphan evidence {item.evidence_id}")
        if item.source is EvidenceSource.AGENT:
            reasons.append("agent assertions are not verifier evidence")

    satisfied: dict[str, bool] = {}
    valid_evidence: dict[str, tuple[Evidence, ...]] = {}
    for node in graph.verifiers:
        observed = result_by_id.get(node.verifier_id)
        if observed is None:
            reasons.append(f"missing result for {node.verifier_id}")
            satisfied[node.verifier_id] = False
            valid_evidence[node.verifier_id] = ()
            continue

        outcome_matches = observed.outcome is node.expected_outcome
        if not outcome_matches:
            reasons.append(
                f"{node.verifier_id} expected {node.expected_outcome.value}, "
                f"observed {observed.outcome.value}"
            )

        linked: list[Evidence] = []
        for evidence_id in observed.evidence_ids:
            linked_item = evidence_by_id.get(evidence_id)
            if linked_item is None:
                reasons.append(f"{node.verifier_id} references missing evidence {evidence_id}")
                continue
            if linked_item.verifier_id != node.verifier_id:
                reasons.append(f"evidence {evidence_id} is linked to the wrong verifier")
                continue
            if linked_item.outcome is not observed.outcome:
                reasons.append(f"evidence {evidence_id} contradicts its verifier result")
                continue
            if linked_item.source is not EvidenceSource.VERIFIER:
                continue
            if not linked_item.artifact_digest.strip():
                reasons.append(f"evidence {evidence_id} has no artifact digest")
                continue
            linked.append(linked_item)

        if not linked:
            reasons.append(f"{node.verifier_id} has no valid verifier evidence")
        valid_evidence[node.verifier_id] = tuple(linked)
        dependencies_satisfied = all(satisfied.get(item, False) for item in node.dependencies)
        if outcome_matches and not dependencies_satisfied:
            reasons.append(f"{node.verifier_id} passed without satisfied dependencies")
        satisfied[node.verifier_id] = outcome_matches and bool(linked) and dependencies_satisfied

    for claim in graph.claims:
        for node in graph.verifiers:
            node_evidence = valid_evidence[node.verifier_id]
            if not any(claim.claim_id in item.claim_ids for item in node_evidence):
                reasons.append(f"claim {claim.claim_id} has no evidence from {node.kind.value}")

    if graph.task.kind is TaskKind.BUGFIX:
        reproduce = next(
            (node for node in graph.verifiers if node.kind is VerifierKind.REPRODUCE), None
        )
        targeted = next(
            (node for node in graph.verifiers if node.kind is VerifierKind.TARGETED_TESTS), None
        )
        reproduce_result = result_by_id.get(reproduce.verifier_id) if reproduce else None
        targeted_result = result_by_id.get(targeted.verifier_id) if targeted else None
        if reproduce_result is None or reproduce_result.outcome is not Outcome.FAILED:
            reasons.append("bugfix lacks a demonstrated pre-fix failure")
        if targeted_result is None or targeted_result.outcome is not Outcome.PASSED:
            reasons.append("bugfix lacks a demonstrated post-fix pass")

        if reproduce is not None and targeted is not None:
            pre_digests = {
                item.artifact_digest for item in valid_evidence.get(reproduce.verifier_id, ())
            }
            post_digests = {
                item.artifact_digest for item in valid_evidence.get(targeted.verifier_id, ())
            }
            if pre_digests & post_digests:
                reasons.append("pre-fix and post-fix evidence are identical")

    canonical_reasons = tuple(dict.fromkeys(reasons))
    complete = not canonical_reasons and all(satisfied.values()) and len(satisfied) == len(nodes)
    return ProofAssessment(
        complete=complete,
        false_green=not complete,
        reasons=canonical_reasons,
    )
