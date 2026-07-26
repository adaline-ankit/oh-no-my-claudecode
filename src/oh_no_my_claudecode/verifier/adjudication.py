"""Fail-closed completion adjudication over deterministic verifier evidence."""

from __future__ import annotations

from dataclasses import dataclass

from .test_integrity import TestIntegrityReport, assess_test_integrity


@dataclass(frozen=True, slots=True)
class CompletionEvidence:
    """Frozen evidence needed to independently adjudicate one claimed fix."""

    baseline_failure_reproduced: bool | None
    final_verifier_passed: bool | None
    changed_code_reached: bool | None
    mutation_graded: int | None
    mutation_killed: int | None
    critical_mutants_survived: int | None
    primary_verifier_passed: bool | None
    secondary_verifier_passed: bool | None
    requires_secondary_verifier: bool
    test_diff: str
    protected_paths: tuple[str, ...]
    agent_claimed_complete: bool
    llm_review: str | None = None


@dataclass(frozen=True, slots=True)
class CompletionAdjudication:
    """Independent verdict; advisory model review never contributes to pass."""

    complete: bool
    false_green: bool
    reasons: tuple[str, ...]
    deterministic_evidence: tuple[str, ...]
    advisory_llm_review: str | None
    test_integrity: TestIntegrityReport


def adjudicate_completion(evidence: CompletionEvidence) -> CompletionAdjudication:
    """Return a fail-closed verdict over baseline, reachability, mutation and tests."""

    integrity = assess_test_integrity(
        evidence.test_diff,
        protected_paths=evidence.protected_paths,
        baseline_failure_reproduced=evidence.baseline_failure_reproduced,
        final_verifier_passed=evidence.final_verifier_passed,
    )
    reasons = list(integrity.reasons)
    observed: list[str] = []

    def _require_true(value: bool | None, missing: str, failed: str, observed_name: str) -> None:
        if value is None:
            reasons.append(missing)
        elif value is not True:
            reasons.append(failed)
        else:
            observed.append(observed_name)

    _require_true(
        evidence.baseline_failure_reproduced,
        "baseline failure reproduction evidence missing",
        "seeded baseline did not fail the verifier",
        "baseline-failure-reproduced",
    )
    _require_true(
        evidence.final_verifier_passed,
        "final verifier evidence missing",
        "final verifier did not pass",
        "final-verifier-passed",
    )
    _require_true(
        evidence.changed_code_reached,
        "changed-code reachability evidence missing",
        "changed production code was not reached by passing tests",
        "changed-code-reached",
    )
    _require_true(
        evidence.primary_verifier_passed,
        "primary verifier evidence missing",
        "primary verifier did not pass",
        "primary-verifier-passed",
    )
    if evidence.requires_secondary_verifier:
        _require_true(
            evidence.secondary_verifier_passed,
            "secondary verifier evidence missing",
            "secondary verifier did not pass",
            "secondary-verifier-passed",
        )

    if evidence.mutation_graded is None:
        reasons.append("targeted mutation evidence missing")
    elif evidence.mutation_graded <= 0:
        reasons.append("targeted mutation campaign graded no mutants")
    else:
        observed.append(f"mutation-graded:{evidence.mutation_graded}")
        if evidence.mutation_killed is None:
            reasons.append("killed-mutant evidence missing")
        elif evidence.mutation_killed <= 0:
            reasons.append("targeted mutation campaign killed no mutants")
        else:
            observed.append(f"mutation-killed:{evidence.mutation_killed}")
        if evidence.critical_mutants_survived is None:
            reasons.append("critical-mutant survival evidence missing")
        elif evidence.critical_mutants_survived:
            reasons.append(
                f"{evidence.critical_mutants_survived} critical targeted mutant(s) survived"
            )
        else:
            observed.append("critical-mutants-survived:0")

    if integrity.safe:
        observed.append("protected-suite-integrity")
    canonical = tuple(dict.fromkeys(reasons))
    return CompletionAdjudication(
        complete=not canonical,
        false_green=bool(canonical),
        reasons=canonical,
        deterministic_evidence=tuple(observed),
        advisory_llm_review=evidence.llm_review,
        test_integrity=integrity,
    )


__all__ = ["CompletionAdjudication", "CompletionEvidence", "adjudicate_completion"]
