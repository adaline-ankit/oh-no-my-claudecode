from __future__ import annotations

from oh_no_my_claudecode.experiment.verifier_calibration import calibrate_default_verifier


def test_default_verifier_calibration_reports_sensitivity_and_specificity_gate() -> None:
    report = calibrate_default_verifier()

    assert report.caught_false_green == 13
    assert report.missed_false_green == 0
    assert report.false_green_cases == 13
    assert report.cleared_legitimate == 10
    assert report.false_positive_legitimate == 0
    assert report.legitimate_cases == 10
    assert report.sensitivity == 1.0
    assert report.specificity == 1.0
    assert report.claim_ready is True
    assert report.reasons == ()
