"""The false-green challenge set, as data the ablation can run over.

``tests/test_verifier_false_green.py`` is the repo's ground truth: a battery of
changes that *look* green but are not genuinely verified, plus a control that a
correct verifier must pass. Those cases were expressed as hand-written test
functions, which made them unusable for measuring *which component* catches
what. This module encodes the same battery as :class:`VerifierCase` data so
:mod:`oh_no_my_claudecode.verifier.ablation` can replay it under any component
subset.

Two tiers, kept explicitly separate so every number stays attributable:

- :attr:`CaseProvenance.REPO_BATTERY` — a 1:1 encoding of one existing
  challenge in ``tests/test_verifier_false_green.py``. Component inputs are
  exactly the ones that test supplies; every other component is deliberately
  left unsupplied and therefore reports *skipped*, never "found nothing".
- :attr:`CaseProvenance.COMPOSED` — cases added here because the repo battery is
  one-detector-per-case and therefore cannot measure *overlap* or false
  positives. Each composed case supplies inputs for several components at once
  and carries a ``rationale`` justifying every one of them.

Everything here is inert data plus pure in-process mutant runners: no clock, no
network, no subprocess, no unseeded randomness. Importing this module runs
nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from oh_no_my_claudecode.proof_graph.models import (
    Claim,
    ClaimKind,
    DiffMetadata,
    Evidence,
    EvidenceSource,
    Outcome,
    ProofGraph,
    RiskMetadata,
    TaskKind,
    TaskMetadata,
    VerifierKind,
    VerifierNode,
    VerifierResult,
)
from oh_no_my_claudecode.verifier.adapters import build_changed_regions, coverage_to_executions
from oh_no_my_claudecode.verifier.composition import (
    ContractInput,
    MutationInput,
    ProofGraphInput,
    ReachabilityInput,
    VerifierCase,
)
from oh_no_my_claudecode.verifier.contract_review import (
    BehaviorRequirement,
    ForbiddenRegression,
    Invariant,
    TaskContract,
)
from oh_no_my_claudecode.verifier.mutation import (
    FunctionUnderTest,
    Mutant,
    MutationOperator,
)
from oh_no_my_claudecode.verifier.reachability import ChangedRegion, TestExecution


class CaseProvenance(StrEnum):
    """Where a challenge case came from — repo ground truth, or added here."""

    REPO_BATTERY = "repo-battery"
    COMPOSED = "composed"


@dataclass(frozen=True, slots=True)
class ChallengeCase:
    """One labelled case plus its provenance, so findings stay attributable."""

    case: VerifierCase
    provenance: CaseProvenance
    rationale: str
    source_test: str | None = None

    def __post_init__(self) -> None:
        if self.provenance is CaseProvenance.REPO_BATTERY and not self.source_test:
            raise ValueError(f"{self.case.case_id}: repo-battery cases must name a source test")
        if not self.rationale.strip():
            raise ValueError(f"{self.case.case_id}: every challenge case needs a rationale")


# --------------------------------------------------------------------------- #
# Shared fixtures — identical to the ones the repo battery uses
# --------------------------------------------------------------------------- #

#: The function under test used throughout ``tests/test_verifier_false_green.py``.
FUNCTION_UNDER_TEST = FunctionUnderTest(
    qualname="is_eligible",
    source=(
        "def is_eligible(age, active):\n"
        "    if age >= 18 and active:\n"
        "        return True\n"
        "    return False"
    ),
)

_SOURCE_FILE = "src/eligibility.py"


def _blind_runner(_mutant: Mutant) -> Outcome:
    """A trivially green suite: it notices no injected fault at all."""
    return Outcome.PASSED


def _comparison_only_runner(mutant: Mutant) -> Outcome:
    """A weakened suite: still catches comparison flips, blind to everything else."""
    if mutant.operator is MutationOperator.FLIP_COMPARISON:
        return Outcome.FAILED
    return Outcome.PASSED


def _killing_runner(_mutant: Mutant) -> Outcome:
    """A strong suite: every injected fault makes the suite fail."""
    return Outcome.FAILED


def _killing_runner_with_ungraded(mutant: Mutant) -> Outcome:
    """A strong suite where dropped-statement mutants fail to build (ungraded).

    Exercises the "errored mutants are excluded from the score" path: an
    ungraded mutant must not be reported as a survivor.
    """
    if mutant.operator is MutationOperator.DROP_STATEMENT:
        return Outcome.ERROR
    return Outcome.FAILED


def _clean_proof_graph(
    *,
    task_id: str,
    claim_id: str,
    statement: str,
    digest: str,
    changed_file: str = _SOURCE_FILE,
) -> ProofGraphInput:
    """A well-formed, complete proof: planned node passed with verifier evidence.

    Used by composed cases whose scenario really does have a clean proof-graph
    view, so the pre-existing boundary genuinely clears and any flag comes from
    another component.
    """
    node = VerifierNode(
        verifier_id="v_targeted",
        kind=VerifierKind.TARGETED_TESTS,
        argv=(),
        expected_outcome=Outcome.PASSED,
    )
    graph = ProofGraph(
        task=TaskMetadata(
            task_id=task_id,
            summary=statement,
            kind=TaskKind.FEATURE,
            claims=(Claim(claim_id=claim_id, statement=statement, kind=ClaimKind.BEHAVIOR),),
        ),
        risk=RiskMetadata(),
        diff=DiffMetadata(changed_files=(changed_file,)),
        verifiers=(node,),
    )
    evidence = Evidence(
        evidence_id="e_targeted",
        verifier_id="v_targeted",
        outcome=Outcome.PASSED,
        artifact_digest=digest,
        claim_ids=(claim_id,),
        source=EvidenceSource.VERIFIER,
    )
    return ProofGraphInput(
        graph=graph,
        results=(
            VerifierResult(
                verifier_id="v_targeted",
                outcome=Outcome.PASSED,
                evidence_ids=("e_targeted",),
            ),
        ),
        evidence=(evidence,),
    )


def _reachability_from_coverage(
    *,
    executed: Sequence[int],
    changed: Sequence[int],
    file: str = _SOURCE_FILE,
) -> ReachabilityInput:
    """Build reachability inputs through the real coverage adapter.

    Uses :func:`~...adapters.build_changed_regions` and
    :func:`~...adapters.coverage_to_executions` over an inline ``coverage json``
    document, so the adapter edge is exercised by the ablation without any I/O.
    """
    report = {
        "files": {
            file: {
                "executed_lines": list(executed),
                "missing_lines": [line for line in changed if line not in set(executed)],
                "excluded_lines": [],
            }
        }
    }
    return ReachabilityInput(
        regions=tuple(build_changed_regions(report, {file: list(changed)})),
        executions=tuple(coverage_to_executions(report)),
    )


def _satisfied_contract(*, contract_id: str, claim_id: str, digest: str) -> ContractInput:
    """A contract fully backed by passing verifier evidence."""
    return ContractInput(
        contract=TaskContract(
            contract_id=contract_id,
            required_behaviors=(
                BehaviorRequirement(
                    requirement_id="behavior",
                    description="the declared behaviour holds",
                    claim_ids=(claim_id,),
                ),
            ),
        ),
        evidence=(
            Evidence(
                evidence_id="e_behavior",
                verifier_id="v_targeted",
                outcome=Outcome.PASSED,
                artifact_digest=digest,
                claim_ids=(claim_id,),
                source=EvidenceSource.VERIFIER,
            ),
        ),
    )


# --------------------------------------------------------------------------- #
# Tier 1 — 1:1 encodings of tests/test_verifier_false_green.py
# --------------------------------------------------------------------------- #

_REPO_BATTERY: tuple[ChallengeCase, ...] = (
    ChallengeCase(
        provenance=CaseProvenance.REPO_BATTERY,
        source_test="test_challenge_changed_code_unreached",
        rationale=(
            "The green suite only touches unrelated lines; only the reachability "
            "inputs from the source test are supplied."
        ),
        case=VerifierCase(
            case_id="repo-unreached-change",
            description="changed code is never reached by a passing test",
            expected_false_green=True,
            reachability=ReachabilityInput(
                regions=(ChangedRegion(file=_SOURCE_FILE, lines=frozenset({2, 3})),),
                executions=(
                    TestExecution(
                        test_id="t_unrelated",
                        outcome=Outcome.PASSED,
                        covered={_SOURCE_FILE: frozenset({40, 41})},
                    ),
                ),
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.REPO_BATTERY,
        source_test="test_challenge_reached_only_by_failing_test",
        rationale="Coverage exists but comes from a failing test, per the source test.",
        case=VerifierCase(
            case_id="repo-reached-only-by-failing-test",
            description="the change is covered, but only by a FAILING test",
            expected_false_green=True,
            reachability=ReachabilityInput(
                regions=(ChangedRegion(file=_SOURCE_FILE, lines=frozenset({2})),),
                executions=(
                    TestExecution(
                        test_id="t_red",
                        outcome=Outcome.FAILED,
                        covered={_SOURCE_FILE: frozenset({2})},
                    ),
                ),
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.REPO_BATTERY,
        source_test="test_challenge_trivially_true_suite_lets_all_mutants_survive",
        rationale="An `assert True` suite; the source test supplies only the mutation seam.",
        case=VerifierCase(
            case_id="repo-blind-suite",
            description="a trivially green suite lets every mutant survive",
            expected_false_green=True,
            mutation=MutationInput(function=FUNCTION_UNDER_TEST, runner=_blind_runner),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.REPO_BATTERY,
        source_test="test_challenge_weakened_suite_leaves_survivors",
        rationale="A partially weakened suite; the source test supplies only the mutation seam.",
        case=VerifierCase(
            case_id="repo-weakened-suite",
            description="the suite catches comparison flips but nothing else",
            expected_false_green=True,
            mutation=MutationInput(function=FUNCTION_UNDER_TEST, runner=_comparison_only_runner),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.REPO_BATTERY,
        source_test="test_challenge_agent_only_evidence_does_not_satisfy_contract",
        rationale="Agent self-report as the only evidence; the source test supplies the contract.",
        case=VerifierCase(
            case_id="repo-agent-only-contract-evidence",
            description="the contract is 'satisfied' only by the agent's own say-so",
            expected_false_green=True,
            contract=ContractInput(
                contract=TaskContract(
                    contract_id="add-eligibility-rule",
                    required_behaviors=(
                        BehaviorRequirement(
                            requirement_id="rule-added",
                            description="18+ active users are eligible",
                            claim_ids=("c_rule",),
                        ),
                    ),
                ),
                evidence=(
                    Evidence(
                        evidence_id="e_agent",
                        verifier_id="v_self_report",
                        outcome=Outcome.PASSED,
                        artifact_digest="",
                        claim_ids=("c_rule",),
                        source=EvidenceSource.AGENT,
                    ),
                ),
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.REPO_BATTERY,
        source_test="test_challenge_demonstrated_regression_is_violation",
        rationale="A failing verifier on a guard claim; the source test supplies the contract.",
        case=VerifierCase(
            case_id="repo-demonstrated-regression",
            description="a forbidden regression was actually demonstrated",
            expected_false_green=True,
            contract=ContractInput(
                contract=TaskContract(
                    contract_id="keep-auth-safe",
                    required_behaviors=(
                        BehaviorRequirement(
                            requirement_id="feature",
                            description="new endpoint works",
                            claim_ids=("c_feature",),
                        ),
                    ),
                    forbidden_regressions=(
                        ForbiddenRegression(
                            regression_id="auth-bypass",
                            description="auth must not regress",
                            guard_claim_ids=("c_auth",),
                        ),
                    ),
                ),
                evidence=(
                    Evidence(
                        evidence_id="e_feature",
                        verifier_id="v_targeted",
                        outcome=Outcome.PASSED,
                        artifact_digest="abc123",
                        claim_ids=("c_feature",),
                        source=EvidenceSource.VERIFIER,
                    ),
                    Evidence(
                        evidence_id="e_auth",
                        verifier_id="v_regression",
                        outcome=Outcome.FAILED,
                        artifact_digest="def456",
                        claim_ids=("c_auth",),
                        source=EvidenceSource.VERIFIER,
                    ),
                ),
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.REPO_BATTERY,
        source_test="test_challenge_broken_invariant_is_violation",
        rationale=(
            "A failing verifier on an invariant claim; the source test supplies the contract."
        ),
        case=VerifierCase(
            case_id="repo-broken-invariant",
            description="a preserved invariant is demonstrably broken",
            expected_false_green=True,
            contract=ContractInput(
                contract=TaskContract(
                    contract_id="preserve-idempotency",
                    preserved_invariants=(
                        Invariant(
                            invariant_id="idempotent",
                            description="retries stay idempotent",
                            claim_ids=("c_idem",),
                        ),
                    ),
                ),
                evidence=(
                    Evidence(
                        evidence_id="e_idem",
                        verifier_id="v_regression",
                        outcome=Outcome.FAILED,
                        artifact_digest="1234ab",
                        claim_ids=("c_idem",),
                        source=EvidenceSource.VERIFIER,
                    ),
                ),
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.REPO_BATTERY,
        source_test="test_challenge_proof_graph_flags_agent_only_evidence",
        rationale=(
            "The reused proof-graph trust boundary; the source test supplies only the "
            "graph, results and agent evidence."
        ),
        case=VerifierCase(
            case_id="repo-proof-graph-agent-only-pass",
            description="an agent-only 'pass' against a planned proof graph",
            expected_false_green=True,
            proof_graph=ProofGraphInput(
                graph=ProofGraph(
                    task=TaskMetadata(
                        task_id="feat",
                        summary="add rule",
                        kind=TaskKind.FEATURE,
                        claims=(
                            Claim(claim_id="c1", statement="rule added", kind=ClaimKind.BEHAVIOR),
                        ),
                    ),
                    risk=RiskMetadata(),
                    diff=DiffMetadata(changed_files=(_SOURCE_FILE,)),
                    verifiers=(
                        VerifierNode(
                            verifier_id="v1",
                            kind=VerifierKind.TARGETED_TESTS,
                            argv=(),
                            expected_outcome=Outcome.PASSED,
                        ),
                    ),
                ),
                results=(
                    VerifierResult(
                        verifier_id="v1", outcome=Outcome.PASSED, evidence_ids=("e1",)
                    ),
                ),
                evidence=(
                    Evidence(
                        evidence_id="e1",
                        verifier_id="v1",
                        outcome=Outcome.PASSED,
                        artifact_digest="deadbeefdeadbeef",
                        claim_ids=("c1",),
                        source=EvidenceSource.AGENT,
                    ),
                ),
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.REPO_BATTERY,
        source_test="test_control_real_fix_is_reported_verified",
        rationale=(
            "The repo's control: reached by a passing test, every mutant killed, "
            "contract fully satisfied. No component may flag it."
        ),
        case=VerifierCase(
            case_id="repo-control-real-fix",
            description="a genuinely good change — the verifier must not be always-red",
            expected_false_green=False,
            reachability=ReachabilityInput(
                regions=(ChangedRegion(file=_SOURCE_FILE, lines=frozenset({2, 3})),),
                executions=(
                    TestExecution(
                        test_id="t_eligible",
                        outcome=Outcome.PASSED,
                        covered={_SOURCE_FILE: frozenset({2, 3, 4})},
                    ),
                ),
            ),
            mutation=MutationInput(function=FUNCTION_UNDER_TEST, runner=_killing_runner),
            contract=ContractInput(
                contract=TaskContract(
                    contract_id="add-eligibility-rule",
                    required_behaviors=(
                        BehaviorRequirement(
                            requirement_id="rule-added",
                            description="18+ active users are eligible",
                            claim_ids=("c_rule",),
                        ),
                    ),
                    preserved_invariants=(
                        Invariant(
                            invariant_id="no-crash",
                            description="stays total",
                            claim_ids=("c_total",),
                        ),
                    ),
                    forbidden_regressions=(
                        ForbiddenRegression(
                            regression_id="auth-bypass",
                            description="auth safe",
                            guard_claim_ids=("c_auth",),
                        ),
                    ),
                ),
                evidence=(
                    Evidence(
                        evidence_id="e_rule",
                        verifier_id="v_targeted",
                        outcome=Outcome.PASSED,
                        artifact_digest="aa11",
                        claim_ids=("c_rule",),
                        source=EvidenceSource.VERIFIER,
                    ),
                    Evidence(
                        evidence_id="e_total",
                        verifier_id="v_regression",
                        outcome=Outcome.PASSED,
                        artifact_digest="bb22",
                        claim_ids=("c_total",),
                        source=EvidenceSource.VERIFIER,
                    ),
                ),
            ),
        ),
    ),
)


# --------------------------------------------------------------------------- #
# Tier 2 — composed cases that supply several components at once
# --------------------------------------------------------------------------- #

_COMPOSED: tuple[ChallengeCase, ...] = (
    ChallengeCase(
        provenance=CaseProvenance.COMPOSED,
        rationale=(
            "The suite runs the changed lines and reports a pass with verifier-sourced "
            "evidence, so reachability, the contract review and the proof graph all "
            "legitimately clear. Its assertions are vacuous, which only fault injection "
            "can see: every mutant survives."
        ),
        case=VerifierCase(
            case_id="composed-green-suite-blind-to-faults",
            description="covered, evidenced, proof-complete — and blind to every fault",
            expected_false_green=True,
            proof_graph=_clean_proof_graph(
                task_id="blind-suite",
                claim_id="c_rule",
                statement="18+ active users are eligible",
                digest="c0ffee01",
            ),
            reachability=_reachability_from_coverage(executed=(1, 2, 3, 4), changed=(2, 3)),
            mutation=MutationInput(function=FUNCTION_UNDER_TEST, runner=_blind_runner),
            contract=_satisfied_contract(
                contract_id="blind-suite", claim_id="c_rule", digest="c0ffee01"
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.COMPOSED,
        rationale=(
            "A passing, evidenced suite that never executes the changed lines. The "
            "contract review and proof graph see a clean pass because the evidence is "
            "verifier-sourced; only coverage attribution exposes it. Mutation input is "
            "deliberately withheld here — see the -mutation-view twin, which supplies it."
        ),
        case=VerifierCase(
            case_id="composed-unreached-change-clean-evidence",
            description="clean evidence, complete proof — but the change was never run",
            expected_false_green=True,
            proof_graph=_clean_proof_graph(
                task_id="unreached-change",
                claim_id="c_rule",
                statement="18+ active users are eligible",
                digest="ba5eba11",
            ),
            reachability=_reachability_from_coverage(executed=(10, 11), changed=(2, 3)),
            contract=_satisfied_contract(
                contract_id="unreached-change", claim_id="c_rule", digest="ba5eba11"
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.COMPOSED,
        rationale=(
            "The same unreached change, with the mutation seam supplied. If no passing "
            "test executes the changed lines, no test can fail when those lines are "
            "mutated, so every mutant survives — the blind runner is the faithful model. "
            "This case measures the real overlap between reachability and mutation."
        ),
        case=VerifierCase(
            case_id="composed-unreached-change-mutation-view",
            description="an unreached change, seen by both reachability and mutation",
            expected_false_green=True,
            proof_graph=_clean_proof_graph(
                task_id="unreached-change-mutation",
                claim_id="c_rule",
                statement="18+ active users are eligible",
                digest="ba5eba12",
            ),
            reachability=_reachability_from_coverage(executed=(10, 11), changed=(2, 3)),
            mutation=MutationInput(function=FUNCTION_UNDER_TEST, runner=_blind_runner),
            contract=_satisfied_contract(
                contract_id="unreached-change-mutation", claim_id="c_rule", digest="ba5eba12"
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.COMPOSED,
        rationale=(
            "One scenario — the claim is backed only by the agent's prose — expressed "
            "both as a task contract and as the equivalent proof graph, with the same "
            "agent evidence. The suite genuinely covers the change and kills its "
            "mutants, so this isolates contract review against the pre-existing "
            "proof-graph trust boundary."
        ),
        case=VerifierCase(
            case_id="composed-agent-only-pass-both-views",
            description="an agent-only pass, visible to both the contract and the proof graph",
            expected_false_green=True,
            proof_graph=ProofGraphInput(
                graph=ProofGraph(
                    task=TaskMetadata(
                        task_id="agent-only",
                        summary="18+ active users are eligible",
                        kind=TaskKind.FEATURE,
                        claims=(
                            Claim(
                                claim_id="c_rule",
                                statement="18+ active users are eligible",
                                kind=ClaimKind.BEHAVIOR,
                            ),
                        ),
                    ),
                    risk=RiskMetadata(),
                    diff=DiffMetadata(changed_files=(_SOURCE_FILE,)),
                    verifiers=(
                        VerifierNode(
                            verifier_id="v_self_report",
                            kind=VerifierKind.TARGETED_TESTS,
                            argv=(),
                            expected_outcome=Outcome.PASSED,
                        ),
                    ),
                ),
                results=(
                    VerifierResult(
                        verifier_id="v_self_report",
                        outcome=Outcome.PASSED,
                        evidence_ids=("e_agent",),
                    ),
                ),
                evidence=(
                    Evidence(
                        evidence_id="e_agent",
                        verifier_id="v_self_report",
                        outcome=Outcome.PASSED,
                        artifact_digest="1122334455667788",
                        claim_ids=("c_rule",),
                        source=EvidenceSource.AGENT,
                    ),
                ),
            ),
            reachability=_reachability_from_coverage(executed=(1, 2, 3, 4), changed=(2, 3)),
            mutation=MutationInput(function=FUNCTION_UNDER_TEST, runner=_killing_runner),
            contract=ContractInput(
                contract=TaskContract(
                    contract_id="agent-only",
                    required_behaviors=(
                        BehaviorRequirement(
                            requirement_id="rule-added",
                            description="18+ active users are eligible",
                            claim_ids=("c_rule",),
                        ),
                    ),
                ),
                evidence=(
                    Evidence(
                        evidence_id="e_agent",
                        verifier_id="v_self_report",
                        outcome=Outcome.PASSED,
                        artifact_digest="1122334455667788",
                        claim_ids=("c_rule",),
                        source=EvidenceSource.AGENT,
                    ),
                ),
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.COMPOSED,
        rationale=(
            "The proof plan covers one claim and is genuinely complete for it, the "
            "change is reached, and the suite kills its mutants — but the task's stated "
            "contract also required a second behaviour the plan never planned for, and "
            "that claim has no evidence at all. Only the contract review knows the "
            "obligation exists."
        ),
        case=VerifierCase(
            case_id="composed-contract-obligation-missing-from-plan",
            description="a complete proof over a plan that omits a required behaviour",
            expected_false_green=True,
            proof_graph=_clean_proof_graph(
                task_id="partial-plan",
                claim_id="c_feature",
                statement="the new endpoint works",
                digest="feed0001",
            ),
            reachability=_reachability_from_coverage(executed=(1, 2, 3, 4), changed=(2, 3)),
            mutation=MutationInput(function=FUNCTION_UNDER_TEST, runner=_killing_runner),
            contract=ContractInput(
                contract=TaskContract(
                    contract_id="partial-plan",
                    required_behaviors=(
                        BehaviorRequirement(
                            requirement_id="endpoint",
                            description="the new endpoint works",
                            claim_ids=("c_feature",),
                        ),
                        BehaviorRequirement(
                            requirement_id="rate-limit",
                            description="the endpoint is rate limited",
                            claim_ids=("c_rate_limit",),
                        ),
                    ),
                ),
                evidence=(
                    Evidence(
                        evidence_id="e_feature",
                        verifier_id="v_targeted",
                        outcome=Outcome.PASSED,
                        artifact_digest="feed0001",
                        claim_ids=("c_feature",),
                        source=EvidenceSource.VERIFIER,
                    ),
                ),
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.COMPOSED,
        rationale=(
            "A legitimate two-file refactor: each changed file is reached by its own "
            "passing test, the suite kills every gradable mutant (dropped-statement "
            "mutants fail to build and stay ungraded), the contract declares only "
            "regression guards and none fired, and the proof is complete. Any flag here "
            "is a false positive."
        ),
        case=VerifierCase(
            case_id="composed-legit-multi-file-refactor",
            description="a legitimate refactor that every component should clear",
            expected_false_green=False,
            proof_graph=_clean_proof_graph(
                task_id="legit-refactor",
                claim_id="c_refactor",
                statement="behaviour is unchanged",
                digest="d00dfeed",
            ),
            reachability=ReachabilityInput(
                regions=(
                    ChangedRegion(file=_SOURCE_FILE, lines=frozenset({2, 3})),
                    ChangedRegion(file="src/rules.py", lines=frozenset({7})),
                ),
                executions=(
                    TestExecution(
                        test_id="t_eligible",
                        outcome=Outcome.PASSED,
                        covered={_SOURCE_FILE: frozenset({2, 3, 4})},
                    ),
                    TestExecution(
                        test_id="t_rules",
                        outcome=Outcome.PASSED,
                        covered={"src/rules.py": frozenset({6, 7, 8})},
                    ),
                ),
            ),
            mutation=MutationInput(
                function=FUNCTION_UNDER_TEST, runner=_killing_runner_with_ungraded
            ),
            contract=ContractInput(
                contract=TaskContract(
                    contract_id="legit-refactor",
                    forbidden_regressions=(
                        ForbiddenRegression(
                            regression_id="auth-bypass",
                            description="auth must not regress",
                            guard_claim_ids=("c_auth",),
                        ),
                    ),
                ),
                evidence=(
                    Evidence(
                        evidence_id="e_auth",
                        verifier_id="v_regression",
                        outcome=Outcome.PASSED,
                        artifact_digest="d00dfeed",
                        claim_ids=("c_auth",),
                        source=EvidenceSource.VERIFIER,
                    ),
                ),
            ),
        ),
    ),
    ChallengeCase(
        provenance=CaseProvenance.COMPOSED,
        rationale=(
            "A docs-only diff with a complete proof and a satisfied contract. It touches "
            "no executable line, which reachability treats as a vacuous 'verified' claim "
            "and flags. Labelled legitimate on purpose: the diff is real and correctly "
            "evidenced, so the flag is a measured false positive of that detector, not a "
            "catch."
        ),
        case=VerifierCase(
            case_id="composed-legit-docs-only-change",
            description="a docs-only change with no executable lines",
            expected_false_green=False,
            proof_graph=_clean_proof_graph(
                task_id="legit-docs",
                claim_id="c_docs",
                statement="the guide documents the flag",
                digest="0bad1dea",
                changed_file="docs/guide.md",
            ),
            reachability=ReachabilityInput(
                regions=(ChangedRegion(file="docs/guide.md", lines=frozenset()),),
                executions=(
                    TestExecution(
                        test_id="t_eligible",
                        outcome=Outcome.PASSED,
                        covered={_SOURCE_FILE: frozenset({2, 3, 4})},
                    ),
                ),
            ),
            contract=_satisfied_contract(
                contract_id="legit-docs", claim_id="c_docs", digest="0bad1dea"
            ),
        ),
    ),
)


#: The full challenge set: repo ground truth first, composed cases after.
CHALLENGE_SET: tuple[ChallengeCase, ...] = _REPO_BATTERY + _COMPOSED


def challenge_cases(provenance: CaseProvenance | None = None) -> tuple[VerifierCase, ...]:
    """Return the labelled cases, optionally narrowed to one provenance tier."""
    return tuple(
        entry.case
        for entry in CHALLENGE_SET
        if provenance is None or entry.provenance is provenance
    )


def challenge_by_id(case_id: str) -> ChallengeCase:
    """Look up one challenge case by id."""
    for entry in CHALLENGE_SET:
        if entry.case.case_id == case_id:
            return entry
    raise KeyError(case_id)


def source_tests() -> tuple[str, ...]:
    """Names of the ``tests/test_verifier_false_green.py`` cases encoded here."""
    return tuple(entry.source_test for entry in CHALLENGE_SET if entry.source_test)
