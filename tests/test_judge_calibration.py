"""Calibration: a perfectly-calibrated judge scores clean; overconfidence caught."""

from __future__ import annotations

from math import isclose

import pytest

from oh_no_my_claudecode.evals.judge_audit import JudgedEpisode
from oh_no_my_claudecode.evals.judge_calibration import (
    brier_score,
    calibrate_judge,
    expected_calibration_error,
)


def _ep(score: float, verified: bool, i: int = 0) -> JudgedEpisode:
    return JudgedEpisode(
        episode_id=f"e{score}-{verified}-{i}", verified=verified, judge_score=score
    )


def test_calibrated_judge_has_low_ece_and_brier() -> None:
    # In the 0.9 bin, 9/10 verified true -> confidence matches accuracy.
    episodes = [_ep(0.9, True, i) for i in range(9)] + [_ep(0.9, False, 9)]
    report = calibrate_judge(episodes)
    assert isclose(report.ece, 0.0, abs_tol=1e-9)  # 0.9 confidence, 0.9 accuracy
    assert report.calibrated is True
    assert isclose(brier_score(episodes), 0.9 * 0.01 + 0.1 * 0.81, abs_tol=1e-9)


def test_overconfident_judge_is_caught() -> None:
    # Judge says 0.99 every time but is right only half the time.
    episodes = [_ep(0.99, i % 2 == 0, i) for i in range(20)]
    report = calibrate_judge(episodes)
    assert report.ece > 0.4  # ~|0.99 - 0.5|
    assert report.calibrated is False  # discrimination could still be fine — this axis isn't


def test_reliability_diagram_and_edges() -> None:
    episodes = [_ep(0.1, False), _ep(0.95, True), _ep(1.0, True)]
    report = calibrate_judge(episodes, bins=10)
    # 1.0 confidence lands in the last bin, not out of range
    assert report.reliability[-1].hi == 1.0
    assert all(0.0 <= b.accuracy <= 1.0 for b in report.reliability)
    with pytest.raises(ValueError):
        expected_calibration_error([])
