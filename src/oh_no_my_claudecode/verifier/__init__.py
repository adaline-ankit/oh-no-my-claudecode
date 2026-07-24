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
"""

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

__all__ = [
    "BehaviorRequirement",
    "ChangedRegion",
    "ContractReview",
    "ContractVerdict",
    "ForbiddenRegression",
    "FunctionUnderTest",
    "Invariant",
    "Mutant",
    "MutantTestRunner",
    "MutationOperator",
    "MutationReport",
    "ReachabilityReport",
    "TaskContract",
    "TestExecution",
    "UnreachedRegion",
    "assess_reachability",
    "generate_mutants",
    "is_false_green",
    "review_contract",
    "run_mutation_campaign",
]
