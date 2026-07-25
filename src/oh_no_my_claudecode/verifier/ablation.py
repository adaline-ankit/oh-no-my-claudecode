"""Offline component ablation for the independent verifier.

This answers the question the verifier package could not answer before: **what
does each component contribute?** It replays the false-green challenge set
(:mod:`oh_no_my_claudecode.verifier.challenges`, the data form of
``tests/test_verifier_false_green.py``) under every subset of components and
reports, per subset, how many known false greens were caught, how many were
missed, and how many *legitimate* changes were wrongly flagged.

False positives are weighted as heavily as catches on purpose: a component that
flags everything catches every false green and is worthless.

**This ablation is offline, free and deterministic.** It runs against a fixed
challenge set — no live agent, no LLM call, no network, no subprocess, no clock,
no unseeded randomness — so it costs nothing and is safe to run in CI on every
commit. It is the one ablation in the claim protocol that needs no paid calls.

Honesty rules encoded here rather than left to the reader:

- A component with no input for a case is :attr:`~...composition.ComponentStatus.SKIPPED`
  and the case is scored :attr:`CaseOutcome.NOT_APPLICABLE` when *every* enabled
  component skipped. It is never silently scored as a miss or as zero catches.
- A component that never ran on any case is reported
  :attr:`ComponentRole.NOT_EXERCISED` with a reason — not "0 catches".
- ``unique_catches`` is measured by removal: cases the full set catches and loses
  when this one component is switched off. That, not raw catch count, is what
  makes a component load-bearing.

Adapter coverage: the coverage adapter
(:func:`~...adapters.build_changed_regions` /
:func:`~...adapters.coverage_to_executions`) *is* exercised — composed cases feed
reachability through it from an inline ``coverage json`` document, which needs no
I/O. :class:`~...adapters.SubprocessMutantRunner` is deliberately *not*
exercised: grading a mutant with it spawns a process, which would break the
offline guarantee. The mutation component is driven through its documented
injected-runner seam instead, which is the same interface that adapter
implements.

Run it directly for the table::

    python -m oh_no_my_claudecode.verifier.ablation
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from oh_no_my_claudecode.verifier.challenges import CHALLENGE_SET, challenge_cases
from oh_no_my_claudecode.verifier.composition import (
    COMPONENT_ORDER,
    CompositeVerdict,
    VerifierCase,
    VerifierComponent,
    VerifierConfig,
    component_subsets,
    run_components,
)


class CaseOutcome(StrEnum):
    """How one subset scored on one labelled case."""

    #: Known false green, correctly flagged.
    CAUGHT = "caught"
    #: Known false green that ran through the enabled components unflagged.
    MISSED = "missed"
    #: Legitimate change wrongly flagged. Counts against the subset.
    FALSE_POSITIVE = "false-positive"
    #: Legitimate change correctly left alone.
    CLEARED = "cleared"
    #: No enabled component had input. Unmeasured — neither catch nor miss.
    NOT_APPLICABLE = "not-applicable"


class ComponentRole(StrEnum):
    """The verdict on one component's contribution — the rule-20 answer."""

    #: Removing it from the full set loses at least one catch.
    LOAD_BEARING = "load-bearing"
    #: It catches real false greens, but nothing another enabled component misses.
    REDUNDANT = "redundant"
    #: It ran and never caught anything. Dead weight on this challenge set.
    INERT = "inert"
    #: It had no input on any case, so its contribution is unmeasured, not zero.
    NOT_EXERCISED = "not-exercised"


@dataclass(frozen=True, slots=True)
class CaseResult:
    """One subset's result on one case, with the attribution detail."""

    case_id: str
    expected_false_green: bool
    outcome: CaseOutcome
    flagged_by: tuple[VerifierComponent, ...]
    skipped: tuple[VerifierComponent, ...]
    reasons: tuple[str, ...]

    @property
    def caught(self) -> bool:
        return self.outcome is CaseOutcome.CAUGHT


def _score(verdict: CompositeVerdict, case: VerifierCase) -> CaseResult:
    """Score one composite verdict against the case's ground-truth label."""
    if verdict.findings and not verdict.ran:
        outcome = CaseOutcome.NOT_APPLICABLE
    elif not verdict.findings:
        # The empty subset — the naive verifier. It flags nothing, so a false
        # green sails through; that is the baseline the ablation measures against.
        outcome = CaseOutcome.MISSED if case.expected_false_green else CaseOutcome.CLEARED
    elif case.expected_false_green:
        outcome = CaseOutcome.CAUGHT if verdict.flagged else CaseOutcome.MISSED
    else:
        outcome = CaseOutcome.FALSE_POSITIVE if verdict.flagged else CaseOutcome.CLEARED
    return CaseResult(
        case_id=case.case_id,
        expected_false_green=case.expected_false_green,
        outcome=outcome,
        flagged_by=verdict.flagged_by,
        skipped=verdict.skipped_components,
        reasons=verdict.reasons,
    )


@dataclass(frozen=True, slots=True)
class SubsetResult:
    """Aggregate performance of one component subset over the whole set."""

    label: str
    components: tuple[VerifierComponent, ...]
    results: tuple[CaseResult, ...]

    def _ids(self, outcome: CaseOutcome) -> tuple[str, ...]:
        return tuple(result.case_id for result in self.results if result.outcome is outcome)

    @property
    def caught(self) -> tuple[str, ...]:
        return self._ids(CaseOutcome.CAUGHT)

    @property
    def missed(self) -> tuple[str, ...]:
        return self._ids(CaseOutcome.MISSED)

    @property
    def false_positives(self) -> tuple[str, ...]:
        return self._ids(CaseOutcome.FALSE_POSITIVE)

    @property
    def cleared(self) -> tuple[str, ...]:
        return self._ids(CaseOutcome.CLEARED)

    @property
    def not_applicable(self) -> tuple[str, ...]:
        return self._ids(CaseOutcome.NOT_APPLICABLE)

    @property
    def counts(self) -> tuple[int, int, int, int, int]:
        """``(caught, missed, false positives, cleared, not applicable)``."""
        return (
            len(self.caught),
            len(self.missed),
            len(self.false_positives),
            len(self.cleared),
            len(self.not_applicable),
        )


@dataclass(frozen=True, slots=True)
class ComponentAttribution:
    """What one component contributed, and whether it is load-bearing."""

    component: VerifierComponent
    role: ComponentRole
    reason: str
    solo_catches: tuple[str, ...]
    unique_catches: tuple[str, ...]
    solo_false_positives: tuple[str, ...]
    exercised_on: tuple[str, ...]

    @property
    def load_bearing(self) -> bool:
        return self.role is ComponentRole.LOAD_BEARING


@dataclass(frozen=True, slots=True)
class AblationReport:
    """Full per-subset and per-component ablation over a labelled case set."""

    case_ids: tuple[str, ...]
    false_green_case_ids: tuple[str, ...]
    legitimate_case_ids: tuple[str, ...]
    subsets: tuple[SubsetResult, ...]
    attributions: tuple[ComponentAttribution, ...]

    def subset(self, label: str) -> SubsetResult:
        """Look up one subset row by its label (e.g. ``"mutation"``)."""
        for result in self.subsets:
            if result.label == label:
                return result
        raise KeyError(label)

    @property
    def full(self) -> SubsetResult:
        """The all-components row — the configuration the harness runs today."""
        return self.subsets[-1]

    def attribution(self, component: VerifierComponent) -> ComponentAttribution:
        """Look up one component's attribution."""
        for entry in self.attributions:
            if entry.component is component:
                return entry
        raise KeyError(component)

    def render_table(self) -> str:
        """Render the per-subset table. Deterministic, byte-stable text."""
        header = ("subset", "caught", "missed", "false-pos", "cleared", "n/a")
        rows = [
            (
                result.label,
                *(str(value) for value in result.counts),
            )
            for result in self.subsets
        ]
        widths = [
            max(len(header[column]), *(len(row[column]) for row in rows))
            for column in range(len(header))
        ]

        def _line(cells: Sequence[str]) -> str:
            first = cells[0].ljust(widths[0])
            rest = "  ".join(
                cell.rjust(widths[column + 1]) for column, cell in enumerate(cells[1:])
            )
            return f"{first}  {rest}".rstrip()

        out = [_line(header), "  ".join("-" * width for width in widths)]
        out.extend(_line(row) for row in rows)
        return "\n".join(out)

    def render_attribution(self) -> str:
        """Render the per-component load-bearing verdict. Deterministic text."""
        lines = []
        for entry in self.attributions:
            lines.append(f"{entry.component.value}: {entry.role.value} — {entry.reason}")
            lines.append(f"  solo catches      : {', '.join(entry.solo_catches) or '(none)'}")
            lines.append(f"  unique catches    : {', '.join(entry.unique_catches) or '(none)'}")
            lines.append(
                f"  solo false-pos    : {', '.join(entry.solo_false_positives) or '(none)'}"
            )
            lines.append(f"  exercised on      : {len(entry.exercised_on)} case(s)")
        return "\n".join(lines)

    def render(self) -> str:
        """Full text report: provenance note, subset table, attribution."""
        return "\n\n".join(
            (
                "verifier component ablation — offline, deterministic, zero-cost",
                f"cases: {len(self.case_ids)} "
                f"({len(self.false_green_case_ids)} known false green, "
                f"{len(self.legitimate_case_ids)} legitimate)",
                self.render_table(),
                self.render_attribution(),
            )
        )


def _verdicts(
    cases: Sequence[VerifierCase],
    config: VerifierConfig,
) -> tuple[CaseResult, ...]:
    return tuple(_score(run_components(case, config), case) for case in cases)


def _attribute(
    component: VerifierComponent,
    by_label: dict[str, SubsetResult],
    full: VerifierConfig,
) -> ComponentAttribution:
    """Measure one component's solo and marginal (removal) contribution."""
    solo = by_label[VerifierConfig.only(component).label]
    without = by_label[full.without_components(component).label]
    full_caught = by_label[full.label].caught
    unique = tuple(case_id for case_id in full_caught if case_id not in without.caught)
    exercised = tuple(
        result.case_id
        for result in solo.results
        if result.outcome is not CaseOutcome.NOT_APPLICABLE
    )

    if not exercised:
        role = ComponentRole.NOT_EXERCISED
        reason = "no case in this set supplies input for it; contribution is unmeasured, not zero"
    elif unique:
        role = ComponentRole.LOAD_BEARING
        reason = (
            f"removing it from the full set loses {len(unique)} catch(es) "
            f"no other component makes"
        )
    elif solo.caught:
        role = ComponentRole.REDUNDANT
        reason = (
            f"catches {len(solo.caught)} case(s) on its own, but every one is also "
            "caught by another enabled component"
        )
    else:
        role = ComponentRole.INERT
        reason = f"ran on {len(exercised)} case(s) and caught nothing"

    return ComponentAttribution(
        component=component,
        role=role,
        reason=reason,
        solo_catches=solo.caught,
        unique_catches=unique,
        solo_false_positives=solo.false_positives,
        exercised_on=exercised,
    )


def run_ablation(
    cases: Sequence[VerifierCase] | None = None,
    *,
    components: Sequence[VerifierComponent] = COMPONENT_ORDER,
    mutation_limit: int | None = None,
    mutation_seed: int = 0,
) -> AblationReport:
    """Replay *cases* under every subset of *components* and attribute the results.

    Offline and deterministic: the same inputs always produce a byte-identical
    report. *cases* defaults to the full challenge set.
    """
    labelled = tuple(cases) if cases is not None else challenge_cases()
    if not labelled:
        raise ValueError("run_ablation needs at least one labelled case")
    seen: set[str] = set()
    for case in labelled:
        if case.case_id in seen:
            raise ValueError(f"duplicate case_id: {case.case_id}")
        seen.add(case.case_id)

    configs = component_subsets(
        components,
        mutation_limit=mutation_limit,
        mutation_seed=mutation_seed,
    )
    subsets = tuple(
        SubsetResult(
            label=config.label,
            components=config.components,
            results=_verdicts(labelled, config),
        )
        for config in configs
    )
    by_label = {result.label: result for result in subsets}
    full = configs[-1]
    attributions = tuple(
        _attribute(component, by_label, full) for component in full.components
    )
    return AblationReport(
        case_ids=tuple(case.case_id for case in labelled),
        false_green_case_ids=tuple(
            case.case_id for case in labelled if case.expected_false_green
        ),
        legitimate_case_ids=tuple(
            case.case_id for case in labelled if not case.expected_false_green
        ),
        subsets=subsets,
        attributions=attributions,
    )


def main() -> int:
    """Print the ablation over the full challenge set. No network, no cost."""
    report = run_ablation()
    lines = [
        report.render(),
        "",
        f"challenge cases in the set: {len(CHALLENGE_SET)}",
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
