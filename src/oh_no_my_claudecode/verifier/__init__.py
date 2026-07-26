"""Stronger independent verifier: reachability, mutation, and contract review.

This package layers three orthogonal, pure false-green defences on top of the
existing proof-graph trust boundary (which already rejects agent-sourced
evidence as non-authoritative in
:func:`oh_no_my_claudecode.proof_graph.evaluator.evaluate_proof`):

- :mod:`~oh_no_my_claudecode.verifier.reachability` — was the changed code
  actually exercised by a *passing* test?
- :mod:`~oh_no_my_claudecode.verifier.mutation` — does the suite *bite* when the
  code under test is deliberately broken?
- :mod:`~oh_no_my_claudecode.verifier.contract_review` — does the passing
  verifier evidence satisfy the task's stated semantic contract?

Every entry point is pure over injected data; nothing here runs a test, shells a
process, or trusts agent prose.

Those detectors were previously all-or-nothing, so their individual contribution
could not be measured. Two modules add that measurement without duplicating any
detection logic:

- :mod:`~oh_no_my_claudecode.verifier.composition` — the config surface for
  running an explicit *subset* of components over one change.
- :mod:`~oh_no_my_claudecode.verifier.ablation` — an offline, deterministic,
  zero-cost ablation of every subset over the
  :mod:`~oh_no_my_claudecode.verifier.challenges` false-green challenge set.
"""

from oh_no_my_claudecode.verifier.ablation import (
    AblationReport,
    CaseOutcome,
    CaseResult,
    ComponentAttribution,
    ComponentRole,
    SubsetResult,
    run_ablation,
)
from oh_no_my_claudecode.verifier.adjudication import (
    CompletionAdjudication,
    CompletionEvidence,
    adjudicate_completion,
)
from oh_no_my_claudecode.verifier.calibration import (
    DEFAULT_EXTERNAL_CORPUS_PATH,
    CalibrationCaseResult,
    ExpectedLabel,
    ExternalCalibrationReport,
    ExternalSource,
    ExternalVerifierCase,
    ExternalVerifierCorpus,
    calibrate_external_corpus,
    load_external_corpus,
    wilson_interval,
)
from oh_no_my_claudecode.verifier.challenges import (
    CHALLENGE_SET,
    CaseProvenance,
    ChallengeCase,
    challenge_by_id,
    challenge_cases,
    source_tests,
)
from oh_no_my_claudecode.verifier.composition import (
    COMPONENT_ORDER,
    PACKAGE_COMPONENTS,
    ComponentFinding,
    ComponentStatus,
    CompositeVerdict,
    ContractInput,
    MutationInput,
    ProofGraphInput,
    ReachabilityInput,
    VerifierCase,
    VerifierComponent,
    VerifierConfig,
    component_subsets,
    run_components,
)
from oh_no_my_claudecode.verifier.contract_review import (
    BehaviorRequirement,
    ContractReview,
    ContractVerdict,
    ForbiddenRegression,
    Invariant,
    TaskContract,
    review_contract,
)
from oh_no_my_claudecode.verifier.mutation import (
    FunctionUnderTest,
    Mutant,
    MutantTestRunner,
    MutationOperator,
    MutationReport,
    generate_mutants,
    run_mutation_campaign,
)
from oh_no_my_claudecode.verifier.reachability import (
    ChangedRegion,
    ReachabilityReport,
    TestExecution,
    UnreachedRegion,
    assess_reachability,
    is_false_green,
)
from oh_no_my_claudecode.verifier.test_integrity import (
    TestIntegrityReport,
    assess_test_integrity,
)

__all__ = [
    "CHALLENGE_SET",
    "COMPONENT_ORDER",
    "PACKAGE_COMPONENTS",
    "AblationReport",
    "BehaviorRequirement",
    "CaseOutcome",
    "CaseProvenance",
    "CaseResult",
    "CalibrationCaseResult",
    "ChallengeCase",
    "ChangedRegion",
    "CompletionAdjudication",
    "CompletionEvidence",
    "ComponentAttribution",
    "ComponentFinding",
    "ComponentRole",
    "ComponentStatus",
    "CompositeVerdict",
    "ContractInput",
    "ContractReview",
    "ContractVerdict",
    "DEFAULT_EXTERNAL_CORPUS_PATH",
    "ExpectedLabel",
    "ExternalCalibrationReport",
    "ExternalSource",
    "ExternalVerifierCase",
    "ExternalVerifierCorpus",
    "ForbiddenRegression",
    "FunctionUnderTest",
    "Invariant",
    "Mutant",
    "MutantTestRunner",
    "MutationInput",
    "MutationOperator",
    "MutationReport",
    "ProofGraphInput",
    "ReachabilityInput",
    "ReachabilityReport",
    "SubsetResult",
    "TaskContract",
    "TestExecution",
    "TestIntegrityReport",
    "UnreachedRegion",
    "VerifierCase",
    "VerifierComponent",
    "VerifierConfig",
    "assess_reachability",
    "assess_test_integrity",
    "adjudicate_completion",
    "calibrate_external_corpus",
    "challenge_by_id",
    "challenge_cases",
    "component_subsets",
    "generate_mutants",
    "is_false_green",
    "load_external_corpus",
    "review_contract",
    "run_ablation",
    "run_components",
    "run_mutation_campaign",
    "source_tests",
    "wilson_interval",
]
