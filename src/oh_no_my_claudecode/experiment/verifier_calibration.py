"""Verifier calibration gates for externally-citable ONMC claims.

The benchmark gate can show whether an agent condition passed tasks. It cannot
show whether ONMC's verifier is strict enough to trust those passes. This module
turns the offline verifier challenge ablation into a claim gate: false-green
sensitivity, legitimate-change specificity, and corpus size must all be explicit
before ONMC can publish improvement or SOTA claims.
"""

from __future__ import annotations

from dataclasses import dataclass

from oh_no_my_claudecode.verifier.ablation import (
    AblationReport,
    CaseOutcome,
    run_ablation,
)

__all__ = [
    "VerifierCalibrationReport",
    "calibrate_default_verifier",
    "calibrate_verifier_ablation",
]


@dataclass(frozen=True, slots=True)
class VerifierCalibrationReport:
    """Sensitivity/specificity gate for the independent verifier."""

    claim_ready: bool
    sensitivity: float
    specificity: float
    false_green_cases: int
    legitimate_cases: int
    caught_false_green: int
    missed_false_green: int
    cleared_legitimate: int
    false_positive_legitimate: int
    min_sensitivity: float
    min_specificity: float
    min_false_green_cases: int
    min_legitimate_cases: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_ready": self.claim_ready,
            "sensitivity": self.sensitivity,
            "specificity": self.specificity,
            "false_green_cases": self.false_green_cases,
            "legitimate_cases": self.legitimate_cases,
            "caught_false_green": self.caught_false_green,
            "missed_false_green": self.missed_false_green,
            "cleared_legitimate": self.cleared_legitimate,
            "false_positive_legitimate": self.false_positive_legitimate,
            "min_sensitivity": self.min_sensitivity,
            "min_specificity": self.min_specificity,
            "min_false_green_cases": self.min_false_green_cases,
            "min_legitimate_cases": self.min_legitimate_cases,
            "reasons": list(self.reasons),
        }


def calibrate_default_verifier(
    *,
    min_sensitivity: float = 0.95,
    min_specificity: float = 0.98,
    min_false_green_cases: int = 10,
    min_legitimate_cases: int = 10,
) -> VerifierCalibrationReport:
    """Run the offline default verifier ablation and return its claim gate."""

    return calibrate_verifier_ablation(
        run_ablation(),
        min_sensitivity=min_sensitivity,
        min_specificity=min_specificity,
        min_false_green_cases=min_false_green_cases,
        min_legitimate_cases=min_legitimate_cases,
    )


def calibrate_verifier_ablation(
    report: AblationReport,
    *,
    min_sensitivity: float = 0.95,
    min_specificity: float = 0.98,
    min_false_green_cases: int = 10,
    min_legitimate_cases: int = 10,
) -> VerifierCalibrationReport:
    """Convert an ablation report into a publication gate."""

    if not 0 <= min_sensitivity <= 1:
        raise ValueError("min_sensitivity must be between 0 and 1")
    if not 0 <= min_specificity <= 1:
        raise ValueError("min_specificity must be between 0 and 1")
    if min_false_green_cases < 1:
        raise ValueError("min_false_green_cases must be positive")
    if min_legitimate_cases < 1:
        raise ValueError("min_legitimate_cases must be positive")

    full = report.full
    caught = sum(1 for result in full.results if result.outcome is CaseOutcome.CAUGHT)
    missed = sum(1 for result in full.results if result.outcome is CaseOutcome.MISSED)
    cleared = sum(1 for result in full.results if result.outcome is CaseOutcome.CLEARED)
    false_positive = sum(
        1 for result in full.results if result.outcome is CaseOutcome.FALSE_POSITIVE
    )
    false_green_cases = caught + missed
    legitimate_cases = cleared + false_positive
    sensitivity = caught / false_green_cases if false_green_cases else 0.0
    specificity = cleared / legitimate_cases if legitimate_cases else 0.0

    reasons: list[str] = []
    if false_green_cases < min_false_green_cases:
        reasons.append(
            f"verifier false-green corpus has {false_green_cases} case(s); "
            f"requires {min_false_green_cases}"
        )
    if legitimate_cases < min_legitimate_cases:
        reasons.append(
            f"verifier legitimate-control corpus has {legitimate_cases} case(s); "
            f"requires {min_legitimate_cases}"
        )
    if sensitivity < min_sensitivity:
        reasons.append(
            f"verifier sensitivity {sensitivity:.3f} below target {min_sensitivity:.3f}"
        )
    if specificity < min_specificity:
        reasons.append(
            f"verifier specificity {specificity:.3f} below target {min_specificity:.3f}"
        )

    return VerifierCalibrationReport(
        claim_ready=not reasons,
        sensitivity=sensitivity,
        specificity=specificity,
        false_green_cases=false_green_cases,
        legitimate_cases=legitimate_cases,
        caught_false_green=caught,
        missed_false_green=missed,
        cleared_legitimate=cleared,
        false_positive_legitimate=false_positive,
        min_sensitivity=min_sensitivity,
        min_specificity=min_specificity,
        min_false_green_cases=min_false_green_cases,
        min_legitimate_cases=min_legitimate_cases,
        reasons=tuple(reasons),
    )
