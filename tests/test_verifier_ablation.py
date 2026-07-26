"""Component ablation over the false-green challenge set.

Every test here is offline and deterministic: the ablation replays a fixed
labelled challenge set through pure detectors. No agent, no LLM, no network, no
subprocess, no clock, no unseeded randomness — so this file is safe to run in
CI on every commit at zero cost.
"""

from __future__ import annotations

import socket
import subprocess
from typing import Any

import pytest

from oh_no_my_claudecode.proof_graph import Outcome, evaluate_proof
from oh_no_my_claudecode.verifier import (
    COMPONENT_ORDER,
    CaseOutcome,
    CaseProvenance,
    ComponentRole,
    ComponentStatus,
    FunctionUnderTest,
    Mutant,
    MutationInput,
    VerifierCase,
    VerifierComponent,
    VerifierConfig,
    assess_reachability,
    challenge_by_id,
    challenge_cases,
    component_subsets,
    is_false_green,
    review_contract,
    run_ablation,
    run_components,
    run_mutation_campaign,
)

# The golden table. Each row is
# ``label -> (caught, missed, false positives, cleared, not applicable)``.
# Locked in so any change in a detector's power shows up as a diff here rather
# than as an unattributable "the verifier got better".
_FUNCTION_UNDER_TEST = FunctionUnderTest(
    qualname="is_eligible",
    source=(
        "def is_eligible(age, active):\n"
        "    if age >= 18 and active:\n"
        "        return True\n"
        "    return False"
    ),
)

EXPECTED_COUNTS: dict[str, tuple[int, int, int, int, int]] = {
    "none": (0, 13, 0, 10, 0),
    "proof-graph": (2, 4, 0, 9, 8),
    "reachability": (4, 3, 0, 10, 6),
    "mutation": (4, 2, 0, 9, 8),
    "contract": (5, 3, 0, 10, 5),
    "proof-graph+reachability": (6, 2, 0, 10, 5),
    "proof-graph+mutation": (6, 2, 0, 10, 5),
    "proof-graph+contract": (6, 3, 0, 10, 4),
    "reachability+mutation": (7, 2, 0, 10, 4),
    "reachability+contract": (9, 1, 0, 10, 3),
    "mutation+contract": (9, 1, 0, 10, 3),
    "proof-graph+reachability+mutation": (9, 1, 0, 10, 3),
    "proof-graph+reachability+contract": (10, 1, 0, 10, 2),
    "proof-graph+mutation+contract": (10, 1, 0, 10, 2),
    "reachability+mutation+contract": (12, 0, 0, 10, 1),
    "proof-graph+reachability+mutation+contract": (13, 0, 0, 10, 0),
}


# --------------------------------------------------------------------------- #
# Composition surface
# --------------------------------------------------------------------------- #
def test_component_subsets_are_exhaustive_and_deterministically_ordered() -> None:
    subsets = component_subsets()
    assert len(subsets) == 2 ** len(COMPONENT_ORDER)
    labels = [config.label for config in subsets]
    assert labels[0] == "none"
    assert labels[-1] == "proof-graph+reachability+mutation+contract"
    assert len(set(labels)) == len(labels)
    # Smallest subsets first, then canonical component order.
    assert [len(config.components) for config in subsets] == sorted(
        len(config.components) for config in subsets
    )
    assert [config.label for config in component_subsets()] == labels


def test_config_surface_toggles_components_without_touching_detectors() -> None:
    config = VerifierConfig.only(VerifierComponent.MUTATION)
    assert config.components == (VerifierComponent.MUTATION,)
    assert config.is_enabled(VerifierComponent.MUTATION)
    assert not config.is_enabled(VerifierComponent.CONTRACT)
    assert config.with_components(VerifierComponent.CONTRACT).label == "mutation+contract"
    assert VerifierConfig.full().without_components(VerifierComponent.PROOF_GRAPH).label == (
        "reachability+mutation+contract"
    )
    assert VerifierConfig.nothing().label == "none"


def test_disabled_component_is_never_invoked() -> None:
    """A component absent from the config must not run at all."""

    def exploding_runner(_mutant: Mutant) -> Outcome:
        raise AssertionError("a disabled component was invoked")

    case = VerifierCase(
        case_id="canary",
        description="mutation must not run when disabled",
        expected_false_green=True,
        mutation=MutationInput(
            function=FunctionUnderTest(qualname="f", source="def f():\n    return 1"),
            runner=exploding_runner,
        ),
    )
    verdict = run_components(case, VerifierConfig.only(VerifierComponent.REACHABILITY))
    assert verdict.flagged is False
    assert verdict.skipped_components == (VerifierComponent.REACHABILITY,)
    with pytest.raises(AssertionError, match="disabled component"):
        run_components(case, VerifierConfig.only(VerifierComponent.MUTATION))


@pytest.mark.parametrize(
    ("case_id", "component"),
    [
        ("repo-unreached-change", VerifierComponent.REACHABILITY),
        ("repo-blind-suite", VerifierComponent.MUTATION),
        ("repo-agent-only-contract-evidence", VerifierComponent.CONTRACT),
        ("repo-proof-graph-agent-only-pass", VerifierComponent.PROOF_GRAPH),
    ],
)
def test_composition_matches_calling_the_detector_directly(
    case_id: str, component: VerifierComponent
) -> None:
    """The composition routes inputs; it must not re-derive any verdict."""
    case = challenge_by_id(case_id).case
    verdict = run_components(case, VerifierConfig.only(component))

    direct: bool
    if component is VerifierComponent.REACHABILITY:
        assert case.reachability is not None
        report = assess_reachability(case.reachability.regions, case.reachability.executions)
        direct = is_false_green(report, claimed_verified=case.reachability.claimed_verified)
    elif component is VerifierComponent.MUTATION:
        assert case.mutation is not None
        direct = run_mutation_campaign(case.mutation.function, case.mutation.runner).weak_tests
    elif component is VerifierComponent.CONTRACT:
        assert case.contract is not None
        direct = not review_contract(case.contract.contract, case.contract.evidence).satisfied
    else:
        assert case.proof_graph is not None
        direct = evaluate_proof(
            case.proof_graph.graph, case.proof_graph.results, case.proof_graph.evidence
        ).false_green

    assert verdict.flagged is direct


# --------------------------------------------------------------------------- #
# Honesty: a component that cannot run is skipped with a reason
# --------------------------------------------------------------------------- #
def test_component_without_input_is_skipped_with_a_reason_not_zero_catches() -> None:
    case = challenge_by_id("repo-blind-suite").case  # mutation input only
    verdict = run_components(case, VerifierConfig.full())
    by_component = {finding.component: finding for finding in verdict.findings}

    for component in (
        VerifierComponent.PROOF_GRAPH,
        VerifierComponent.REACHABILITY,
        VerifierComponent.CONTRACT,
    ):
        finding = by_component[component]
        assert finding.status is ComponentStatus.SKIPPED
        assert "supplied for this case" in finding.reason
    assert by_component[VerifierComponent.MUTATION].status is ComponentStatus.FLAGGED


def test_case_with_no_applicable_component_is_not_applicable_not_missed() -> None:
    report = run_ablation()
    mutation_only = report.subset("mutation")
    proof_graph_case = next(
        result for result in mutation_only.results if result.case_id.startswith("repo-proof-graph")
    )
    assert proof_graph_case.outcome is CaseOutcome.NOT_APPLICABLE
    assert proof_graph_case.case_id not in mutation_only.missed
    assert proof_graph_case.case_id not in mutation_only.caught


def test_zero_mutation_budget_reports_skipped_rather_than_no_survivors() -> None:
    """An ungraded campaign must not masquerade as a clean bill of health."""
    case = challenge_by_id("repo-blind-suite").case
    verdict = run_components(
        case, VerifierConfig.only(VerifierComponent.MUTATION, mutation_limit=0)
    )
    finding = verdict.findings[0]
    assert finding.status is ComponentStatus.SKIPPED
    assert finding.reason == "the mutation budget graded no mutants"
    assert verdict.flagged is False


def test_all_mutants_erroring_is_skipped_not_cleared() -> None:
    """"No survivors" from an ungradable campaign is not a clean bill of health."""

    def always_errors(_mutant: Mutant) -> Outcome:
        return Outcome.ERROR

    case = VerifierCase(
        case_id="ungradable",
        description="every mutant fails to build",
        expected_false_green=True,
        mutation=MutationInput(function=_FUNCTION_UNDER_TEST, runner=always_errors),
    )
    verdict = run_components(case, VerifierConfig.only(VerifierComponent.MUTATION))
    finding = verdict.findings[0]
    assert finding.status is ComponentStatus.SKIPPED
    assert "no mutant could be graded" in finding.reason
    assert verdict.flagged is False
    # The case must therefore score as unmeasured, not as a miss.
    assert run_ablation([case]).subset("mutation").not_applicable == ("ungradable",)


# --------------------------------------------------------------------------- #
# Per-subset verdict counts: stable and deterministic
# --------------------------------------------------------------------------- #
def test_every_subset_has_the_expected_stable_verdict_counts() -> None:
    report = run_ablation()
    actual = {result.label: result.counts for result in report.subsets}
    assert actual == EXPECTED_COUNTS
    total = len(report.case_ids)
    for result in report.subsets:
        assert sum(result.counts) == total, result.label


def test_ablation_is_deterministic_across_repeated_runs() -> None:
    first = run_ablation()
    second = run_ablation()
    assert first == second
    assert first.render() == second.render()
    assert first.render_table() == second.render_table()


def test_mutation_budget_and_seed_are_deterministic() -> None:
    seeded = run_ablation(mutation_limit=3, mutation_seed=7)
    assert seeded == run_ablation(mutation_limit=3, mutation_seed=7)
    # A budget may only reduce power, never invent catches.
    full_budget = run_ablation().full
    assert set(seeded.full.caught) <= set(full_budget.caught)


# --------------------------------------------------------------------------- #
# Monotonicity: more components can never mean fewer catches
# --------------------------------------------------------------------------- #
def test_full_combination_is_at_least_as_strong_as_any_subset() -> None:
    report = run_ablation()
    full = report.full
    assert full.label == "proof-graph+reachability+mutation+contract"
    for result in report.subsets:
        assert set(result.caught) <= set(full.caught), result.label
        assert len(result.caught) <= len(full.caught), result.label
    assert full.missed == ()


def test_enabling_a_component_never_loses_a_catch() -> None:
    """Union semantics must hold for every subset/superset pair.

    If this ever fails, a component is *suppressing* another's finding — a real
    bug, not a tuning issue.
    """
    report = run_ablation()
    by_label = {result.label: result for result in report.subsets}
    for config in component_subsets():
        base = by_label[config.label]
        for component in COMPONENT_ORDER:
            if config.is_enabled(component):
                continue
            bigger = by_label[config.with_components(component).label]
            lost = set(base.caught) - set(bigger.caught)
            assert not lost, f"{config.label} + {component.value} lost catches: {sorted(lost)}"


def test_a_superset_never_gains_a_false_positive_it_cannot_explain() -> None:
    """Every false positive must be attributable to a component that flagged it."""
    report = run_ablation()
    for result in report.subsets:
        for case in result.results:
            if case.outcome is CaseOutcome.FALSE_POSITIVE:
                assert case.flagged_by, f"{result.label}/{case.case_id} flagged by nobody"
                assert case.reasons


# --------------------------------------------------------------------------- #
# Legitimate controls are measured, not assumed away
# --------------------------------------------------------------------------- #
def test_full_verifier_clears_all_legitimate_controls() -> None:
    report = run_ablation()
    assert report.full.false_positives == ()
    docs = next(
        case
        for case in report.full.results
        if case.case_id == "composed-legit-docs-only-change"
    )
    assert docs.outcome is CaseOutcome.CLEARED
    assert docs.flagged_by == ()


def test_no_component_flags_the_repo_control_case() -> None:
    control = challenge_by_id("repo-control-real-fix").case
    assert control.expected_false_green is False
    for config in component_subsets():
        verdict = run_components(control, config)
        assert verdict.flagged is False, config.label


# --------------------------------------------------------------------------- #
# Attribution: which components are load-bearing
# --------------------------------------------------------------------------- #
def test_repo_battery_tier_makes_every_component_look_load_bearing() -> None:
    """One-detector-per-case cases cannot separate overlap from uniqueness."""
    report = run_ablation(challenge_cases(CaseProvenance.REPO_BATTERY))
    for component in COMPONENT_ORDER:
        attribution = report.attribution(component)
        assert attribution.role is ComponentRole.LOAD_BEARING, component.value
        assert attribution.unique_catches


def test_composed_tier_shows_proof_graph_is_redundant_with_contract_review() -> None:
    """The non-circular measurement: cases that feed several components at once."""
    report = run_ablation(challenge_cases(CaseProvenance.COMPOSED))
    proof_graph = report.attribution(VerifierComponent.PROOF_GRAPH)
    assert proof_graph.role is ComponentRole.REDUNDANT
    assert proof_graph.unique_catches == ()
    assert proof_graph.solo_catches == ("composed-agent-only-pass-both-views",)

    contract = report.attribution(VerifierComponent.CONTRACT)
    assert "composed-agent-only-pass-both-views" in contract.solo_catches

    for component in (
        VerifierComponent.REACHABILITY,
        VerifierComponent.MUTATION,
        VerifierComponent.CONTRACT,
    ):
        attribution = report.attribution(component)
        assert attribution.role is ComponentRole.LOAD_BEARING, component.value
        assert len(attribution.unique_catches) == 1, component.value


def test_unique_catches_are_measured_by_removal_from_the_full_set() -> None:
    report = run_ablation()
    full = set(report.full.caught)
    for component in COMPONENT_ORDER:
        without = report.subset(VerifierConfig.full().without_components(component).label)
        assert set(report.attribution(component).unique_catches) == full - set(without.caught)


def test_no_component_is_inert_or_unexercised_on_the_full_set() -> None:
    report = run_ablation()
    for component in COMPONENT_ORDER:
        attribution = report.attribution(component)
        assert attribution.role is not ComponentRole.INERT, component.value
        assert attribution.role is not ComponentRole.NOT_EXERCISED, component.value
        assert attribution.exercised_on


def test_unexercised_component_is_reported_as_unmeasured_not_zero() -> None:
    """A component with no input anywhere must never be scored as 0 catches."""
    lonely = challenge_by_id("repo-blind-suite").case  # mutation input only
    report = run_ablation([lonely])
    contract = report.attribution(VerifierComponent.CONTRACT)
    assert contract.role is ComponentRole.NOT_EXERCISED
    assert "unmeasured, not zero" in contract.reason
    assert report.attribution(VerifierComponent.MUTATION).role is ComponentRole.LOAD_BEARING


# --------------------------------------------------------------------------- #
# The ablation is offline: it costs nothing to run
# --------------------------------------------------------------------------- #
def test_ablation_runs_with_no_subprocess_and_no_socket(monkeypatch: Any) -> None:
    def no_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the ablation must not spawn a process")

    def no_socket(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the ablation must not open a socket")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    monkeypatch.setattr(subprocess, "Popen", no_subprocess)
    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)

    report = run_ablation()
    assert report.full.caught
    assert report.render()


def test_challenge_set_is_labelled_and_non_degenerate() -> None:
    report = run_ablation()
    assert len(report.false_green_case_ids) >= 8
    assert len(report.legitimate_case_ids) >= 2
    assert set(report.case_ids) == {case.case_id for case in challenge_cases()}
    # The naive verifier (no component enabled) must catch nothing at all —
    # otherwise the challenge set is not actually adversarial.
    naive = report.subset("none")
    assert naive.caught == ()
    assert len(naive.missed) == len(report.false_green_case_ids)
