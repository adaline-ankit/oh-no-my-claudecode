"""Explicit, ablatable composition of the independent verifier's components.

The detectors in this package (:mod:`~oh_no_my_claudecode.verifier.reachability`,
:mod:`~oh_no_my_claudecode.verifier.mutation`,
:mod:`~oh_no_my_claudecode.verifier.contract_review`) are independent and pure,
but until now they were only ever run *together*: the harness folds their union
into one false-green gate. That makes their individual contribution
unmeasurable — nobody can say whether mutation catches false greens reachability
misses, or whether one component carries the whole benefit.

This module adds the missing surface and nothing else:

- :class:`VerifierComponent` names each toggleable component, including the
  *pre-existing* :attr:`VerifierComponent.PROOF_GRAPH` trust boundary
  (:func:`oh_no_my_claudecode.proof_graph.evaluate_proof`) so the new detectors
  can be measured against the baseline that already existed.
- :class:`VerifierConfig` is the config surface: an explicit set of enabled
  components plus the mutation budget/seed.
- :class:`VerifierCase` bundles the per-component inputs for one change.
- :func:`run_components` dispatches to the existing detectors and returns a
  per-component :class:`ComponentFinding`.

Design rules this module obeys:

- **No duplicated detector logic.** Every finding is produced by calling the
  existing public entry point; this module only routes inputs and normalises
  verdicts. Disabling a component cannot change how an enabled one behaves.
- **Union semantics.** A composite flags a change when *any* enabled component
  flags it, so a superset is monotone: it can never lose a catch a subset had.
- **A component with no input is SKIPPED with a reason**, never silently
  counted as "found nothing". A missing input is unmeasured, not clean.
- **Pure and deterministic.** No clock, no network, no subprocess, no unseeded
  randomness (the mutation budget is selected from an explicit seed).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations

from oh_no_my_claudecode.proof_graph.evaluator import evaluate_proof
from oh_no_my_claudecode.proof_graph.models import Evidence, ProofGraph, VerifierResult
from oh_no_my_claudecode.verifier.contract_review import TaskContract, review_contract
from oh_no_my_claudecode.verifier.mutation import (
    FunctionUnderTest,
    MutantTestRunner,
    run_mutation_campaign,
)
from oh_no_my_claudecode.verifier.reachability import (
    ChangedRegion,
    TestExecution,
    assess_reachability,
    is_false_green,
)


class VerifierComponent(StrEnum):
    """One independently toggleable false-green detector.

    :attr:`PROOF_GRAPH` is the pre-existing trust boundary, included so the
    ablation can ask whether the newer detectors add anything over it.
    """

    PROOF_GRAPH = "proof-graph"
    REACHABILITY = "reachability"
    MUTATION = "mutation"
    CONTRACT = "contract"


#: Canonical component order. Every label, table row and subset enumeration in
#: this package derives its ordering from this tuple, so output is stable.
COMPONENT_ORDER: tuple[VerifierComponent, ...] = tuple(VerifierComponent)

#: The pre-existing baseline that shipped before this package.
BASELINE_COMPONENTS: tuple[VerifierComponent, ...] = (VerifierComponent.PROOF_GRAPH,)

#: The detectors this package added — the ones rule 20 asks us to justify.
PACKAGE_COMPONENTS: tuple[VerifierComponent, ...] = (
    VerifierComponent.REACHABILITY,
    VerifierComponent.MUTATION,
    VerifierComponent.CONTRACT,
)


class ComponentStatus(StrEnum):
    """Outcome of running one component against one case."""

    #: The component positively identified a false green.
    FLAGGED = "flagged"
    #: The component ran against real input and found nothing wrong.
    CLEARED = "cleared"
    #: The component had no input for this case. Unmeasured, not clean.
    SKIPPED = "skipped"


def _canonical(components: Sequence[VerifierComponent]) -> tuple[VerifierComponent, ...]:
    """Return *components* de-duplicated and in :data:`COMPONENT_ORDER` order."""
    unique = set(components)
    return tuple(component for component in COMPONENT_ORDER if component in unique)


@dataclass(frozen=True, slots=True)
class VerifierConfig:
    """Which components run, plus their deterministic knobs.

    This is the whole composition surface. ``enabled`` is authoritative: a
    component absent from it is not consulted at all.
    """

    enabled: frozenset[VerifierComponent] = frozenset()
    mutation_limit: int | None = None
    mutation_seed: int = 0

    def __post_init__(self) -> None:
        if self.mutation_limit is not None and self.mutation_limit < 0:
            raise ValueError("VerifierConfig.mutation_limit must not be negative")

    @classmethod
    def full(cls, *, mutation_limit: int | None = None, mutation_seed: int = 0) -> VerifierConfig:
        """Every component enabled — what the harness runs today."""
        return cls(
            enabled=frozenset(COMPONENT_ORDER),
            mutation_limit=mutation_limit,
            mutation_seed=mutation_seed,
        )

    @classmethod
    def only(
        cls,
        *components: VerifierComponent,
        mutation_limit: int | None = None,
        mutation_seed: int = 0,
    ) -> VerifierConfig:
        """Exactly *components* enabled — the single-component ablation arm."""
        return cls(
            enabled=frozenset(components),
            mutation_limit=mutation_limit,
            mutation_seed=mutation_seed,
        )

    @classmethod
    def nothing(cls) -> VerifierConfig:
        """No component enabled — the naive verifier that always says PASS."""
        return cls(enabled=frozenset())

    @property
    def components(self) -> tuple[VerifierComponent, ...]:
        """Enabled components in canonical order."""
        return _canonical(tuple(self.enabled))

    @property
    def label(self) -> str:
        """Stable, human-readable name for this subset (``"none"`` when empty)."""
        components = self.components
        if not components:
            return "none"
        return "+".join(component.value for component in components)

    def is_enabled(self, component: VerifierComponent) -> bool:
        """Whether *component* runs under this config."""
        return component in self.enabled

    def with_components(self, *components: VerifierComponent) -> VerifierConfig:
        """Return a copy with *components* additionally enabled."""
        return VerifierConfig(
            enabled=self.enabled | frozenset(components),
            mutation_limit=self.mutation_limit,
            mutation_seed=self.mutation_seed,
        )

    def without_components(self, *components: VerifierComponent) -> VerifierConfig:
        """Return a copy with *components* disabled."""
        return VerifierConfig(
            enabled=self.enabled - frozenset(components),
            mutation_limit=self.mutation_limit,
            mutation_seed=self.mutation_seed,
        )


def component_subsets(
    components: Sequence[VerifierComponent] = COMPONENT_ORDER,
    *,
    include_empty: bool = True,
    mutation_limit: int | None = None,
    mutation_seed: int = 0,
) -> tuple[VerifierConfig, ...]:
    """Enumerate every subset of *components*, smallest first.

    Deterministic: subsets are ordered by size and then by
    :data:`COMPONENT_ORDER`, so the ablation table has a fixed row order.
    """
    ordered = _canonical(components)
    start = 0 if include_empty else 1
    return tuple(
        VerifierConfig(
            enabled=frozenset(subset),
            mutation_limit=mutation_limit,
            mutation_seed=mutation_seed,
        )
        for size in range(start, len(ordered) + 1)
        for subset in combinations(ordered, size)
    )


# --------------------------------------------------------------------------- #
# Per-component inputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ProofGraphInput:
    """Inputs for the pre-existing proof-graph trust boundary."""

    graph: ProofGraph
    results: tuple[VerifierResult, ...]
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class ReachabilityInput:
    """Inputs for :func:`~...reachability.assess_reachability`."""

    regions: tuple[ChangedRegion, ...]
    executions: tuple[TestExecution, ...]
    claimed_verified: bool = True


@dataclass(frozen=True, slots=True)
class MutationInput:
    """Inputs for :func:`~...mutation.run_mutation_campaign`.

    ``runner`` is the documented injected seam. The ablation supplies pure
    in-process runners so the campaign spawns no process; the real CLI wires
    :class:`~...adapters.SubprocessMutantRunner` here instead.
    """

    function: FunctionUnderTest
    runner: MutantTestRunner


@dataclass(frozen=True, slots=True)
class ContractInput:
    """Inputs for :func:`~...contract_review.review_contract`."""

    contract: TaskContract
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class VerifierCase:
    """One change presented to the verifier, with a ground-truth label.

    ``expected_false_green`` is the label: ``True`` for a change a naive
    verifier calls PASS but which is not genuinely verified, ``False`` for a
    legitimate change that must not be flagged. Per-component inputs are
    optional — an absent input makes that component :attr:`ComponentStatus.SKIPPED`
    for this case rather than silently clean.
    """

    case_id: str
    description: str
    expected_false_green: bool
    proof_graph: ProofGraphInput | None = None
    reachability: ReachabilityInput | None = None
    mutation: MutationInput | None = None
    contract: ContractInput | None = None

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("VerifierCase.case_id must not be empty")

    def supplied_components(self) -> tuple[VerifierComponent, ...]:
        """Components this case actually carries input for, canonically ordered."""
        supplied = {
            VerifierComponent.PROOF_GRAPH: self.proof_graph is not None,
            VerifierComponent.REACHABILITY: self.reachability is not None,
            VerifierComponent.MUTATION: self.mutation is not None,
            VerifierComponent.CONTRACT: self.contract is not None,
        }
        return tuple(component for component in COMPONENT_ORDER if supplied[component])


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ComponentFinding:
    """What one component concluded about one case."""

    component: VerifierComponent
    status: ComponentStatus
    reason: str

    def __post_init__(self) -> None:
        if self.status is not ComponentStatus.CLEARED and not self.reason.strip():
            raise ValueError(f"{self.component.value} {self.status.value} finding needs a reason")

    @property
    def flagged(self) -> bool:
        return self.status is ComponentStatus.FLAGGED

    @property
    def skipped(self) -> bool:
        return self.status is ComponentStatus.SKIPPED


@dataclass(frozen=True, slots=True)
class CompositeVerdict:
    """Union verdict of the enabled components over one case."""

    case_id: str
    config_label: str
    findings: tuple[ComponentFinding, ...]

    @property
    def flagged(self) -> bool:
        """``True`` when at least one enabled component flagged a false green."""
        return any(finding.flagged for finding in self.findings)

    @property
    def flagged_by(self) -> tuple[VerifierComponent, ...]:
        return tuple(finding.component for finding in self.findings if finding.flagged)

    @property
    def cleared_by(self) -> tuple[VerifierComponent, ...]:
        return tuple(
            finding.component
            for finding in self.findings
            if finding.status is ComponentStatus.CLEARED
        )

    @property
    def skipped_components(self) -> tuple[VerifierComponent, ...]:
        return tuple(finding.component for finding in self.findings if finding.skipped)

    @property
    def ran(self) -> bool:
        """Whether any enabled component had input to run against."""
        return any(not finding.skipped for finding in self.findings)

    @property
    def reasons(self) -> tuple[str, ...]:
        """De-duplicated reasons from the components that flagged."""
        return tuple(dict.fromkeys(finding.reason for finding in self.findings if finding.flagged))


def _first_reason(reasons: Sequence[str], fallback: str) -> str:
    """First detector reason, or *fallback* when the detector gave none."""
    for reason in reasons:
        if reason.strip():
            return reason
    return fallback


def _skipped(component: VerifierComponent, reason: str) -> ComponentFinding:
    return ComponentFinding(component=component, status=ComponentStatus.SKIPPED, reason=reason)


def _flagged(component: VerifierComponent, reason: str) -> ComponentFinding:
    return ComponentFinding(component=component, status=ComponentStatus.FLAGGED, reason=reason)


def _cleared(component: VerifierComponent) -> ComponentFinding:
    return ComponentFinding(component=component, status=ComponentStatus.CLEARED, reason="")


def _run_proof_graph(case: VerifierCase, _config: VerifierConfig) -> ComponentFinding:
    """Delegate to :func:`~oh_no_my_claudecode.proof_graph.evaluate_proof`."""
    component = VerifierComponent.PROOF_GRAPH
    data = case.proof_graph
    if data is None:
        return _skipped(component, "no proof graph, results or evidence supplied for this case")
    assessment = evaluate_proof(data.graph, data.results, data.evidence)
    if assessment.false_green:
        return _flagged(component, _first_reason(assessment.reasons, "proof is incomplete"))
    return _cleared(component)


def _run_reachability(case: VerifierCase, _config: VerifierConfig) -> ComponentFinding:
    """Delegate to :func:`~...reachability.assess_reachability` + ``is_false_green``."""
    component = VerifierComponent.REACHABILITY
    data = case.reachability
    if data is None:
        return _skipped(component, "no changed regions or per-test coverage supplied for this case")
    report = assess_reachability(data.regions, data.executions)
    if is_false_green(report, claimed_verified=data.claimed_verified):
        return _flagged(component, _first_reason(report.reasons, "changed code is not reached"))
    return _cleared(component)


def _run_mutation(case: VerifierCase, config: VerifierConfig) -> ComponentFinding:
    """Delegate to :func:`~...mutation.run_mutation_campaign`."""
    component = VerifierComponent.MUTATION
    data = case.mutation
    if data is None:
        return _skipped(component, "no function under test or mutant runner supplied for this case")
    report = run_mutation_campaign(
        data.function,
        data.runner,
        limit=config.mutation_limit,
        seed=config.mutation_seed,
    )
    if report.weak_tests:
        survivors = ", ".join(mutant.mutant_id for mutant in report.survived[:3])
        suffix = "" if report.survivors <= 3 else f" (+{report.survivors - 3} more)"
        return _flagged(
            component,
            f"{report.survivors}/{report.total} mutants survived (score "
            f"{report.mutation_score:.2f}): {survivors}{suffix}",
        )
    if report.total == 0:
        return _skipped(component, "the mutation budget graded no mutants")
    if not report.killed:
        # Every mutant errored: nothing was graded, so "no survivors" is not a
        # clean bill of health. Report it as unmeasured, never as cleared.
        return _skipped(
            component,
            f"no mutant could be graded: all {report.total} errored",
        )
    return _cleared(component)


def _run_contract(case: VerifierCase, _config: VerifierConfig) -> ComponentFinding:
    """Delegate to :func:`~...contract_review.review_contract`."""
    component = VerifierComponent.CONTRACT
    data = case.contract
    if data is None:
        return _skipped(component, "no task contract or evidence supplied for this case")
    review = review_contract(data.contract, data.evidence)
    if not review.satisfied:
        return _flagged(
            component,
            _first_reason(review.reasons, f"contract review returned {review.verdict.value}"),
        )
    return _cleared(component)


#: One component's delegate: pure input routing plus verdict normalisation.
ComponentDelegate = Callable[[VerifierCase, VerifierConfig], ComponentFinding]

#: Component -> the delegating runner. This is the only dispatch table; adding a
#: component means adding one entry and one ``_run_*`` delegate.
_COMPONENT_RUNNERS: dict[VerifierComponent, ComponentDelegate] = {
    VerifierComponent.PROOF_GRAPH: _run_proof_graph,
    VerifierComponent.REACHABILITY: _run_reachability,
    VerifierComponent.MUTATION: _run_mutation,
    VerifierComponent.CONTRACT: _run_contract,
}


def run_components(case: VerifierCase, config: VerifierConfig) -> CompositeVerdict:
    """Run exactly the components *config* enables against *case*.

    Pure and deterministic. Findings are emitted in :data:`COMPONENT_ORDER`, and
    each one comes from the component's own public entry point — this function
    re-implements no detection logic. A component without input for *case* is
    reported :attr:`ComponentStatus.SKIPPED` with a reason.
    """
    findings = tuple(
        _COMPONENT_RUNNERS[component](case, config) for component in config.components
    )
    return CompositeVerdict(case_id=case.case_id, config_label=config.label, findings=findings)
