from __future__ import annotations

from oh_no_my_claudecode.experiment.verifier_calibration import calibrate_default_verifier


def test_default_verifier_calibration_reports_sensitivity_and_specificity_gate() -> None:
    report = calibrate_default_verifier()

    assert report.caught_false_green == 13
    assert report.missed_false_green == 0
    assert report.false_green_cases == 13
    assert report.cleared_legitimate == 2
    assert report.false_positive_legitimate == 1
    assert report.legitimate_cases == 3
    assert report.sensitivity == 1.0
    assert round(report.specificity, 3) == 0.667
    assert report.claim_ready is False
    assert any("legitimate-control corpus" in reason for reason in report.reasons)
    assert any("specificity" in reason for reason in report.reasons)
