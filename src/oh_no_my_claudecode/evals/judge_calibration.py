"""Judge calibration — is the judge's *confidence* trustworthy?

`judge_audit.py` answers discrimination: does the judge rank good episodes
above bad ones (AUROC)? This answers the orthogonal, equally-important
question interviewers love to separate: when the judge says "0.9 confident",
does it actually succeed 90% of the time? A judge can discriminate perfectly
(AUROC 1.0) and still be wildly overconfident, or vice-versa.

    brier   mean squared error between confidence and 0/1 outcome (lower better)
    ece     expected calibration error — |confidence − accuracy| averaged over
            confidence bins, weighted by bin population (lower better)
    reliability  the per-bin (confidence, accuracy) pairs = the reliability
                 diagram, in numbers

Verdict pairs the two axes so nobody ships a judge that looks good on one:
a judge is TRUSTWORTHY only if it both discriminates (AUROC ≥ bar, measured
elsewhere) and is calibrated (ECE ≤ bar). Deterministic, offline, no numpy.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from oh_no_my_claudecode.evals.judge_audit import JudgedEpisode


def brier_score(episodes: Sequence[JudgedEpisode]) -> float:
    """Mean squared error of confidence vs outcome. 0 = perfect, 0.25 = coin."""
    if not episodes:
        raise ValueError("cannot score an empty episode list")
    total = sum((e.judge_score - (1.0 if e.verified else 0.0)) ** 2 for e in episodes)
    return total / len(episodes)


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    lo: float
    hi: float
    count: int
    mean_confidence: float
    accuracy: float

    @property
    def gap(self) -> float:
        return abs(self.mean_confidence - self.accuracy)


def reliability_bins(episodes: Sequence[JudgedEpisode], *, bins: int = 10) -> list[ReliabilityBin]:
    """Group episodes by confidence bin; empty bins are omitted."""
    if bins <= 0:
        raise ValueError("bins must be positive")
    buckets: list[list[JudgedEpisode]] = [[] for _ in range(bins)]
    for episode in episodes:
        # clamp into [0,1]; the top edge (1.0) lands in the last bin
        score = min(max(episode.judge_score, 0.0), 1.0)
        index = min(int(score * bins), bins - 1)
        buckets[index].append(episode)
    result: list[ReliabilityBin] = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        mean_conf = sum(e.judge_score for e in bucket) / len(bucket)
        accuracy = sum(1 for e in bucket if e.verified) / len(bucket)
        result.append(
            ReliabilityBin(index / bins, (index + 1) / bins, len(bucket), mean_conf, accuracy)
        )
    return result


def expected_calibration_error(episodes: Sequence[JudgedEpisode], *, bins: int = 10) -> float:
    """Population-weighted average |confidence − accuracy| across bins."""
    if not episodes:
        raise ValueError("cannot compute ECE on an empty list")
    n = len(episodes)
    return sum(b.gap * b.count / n for b in reliability_bins(episodes, bins=bins))


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    brier: float
    ece: float
    n: int
    calibrated: bool
    reliability: tuple[ReliabilityBin, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "brier": round(self.brier, 4),
            "ece": round(self.ece, 4),
            "n": self.n,
            "calibrated": self.calibrated,
            "reliability": [
                {
                    "range": [round(b.lo, 2), round(b.hi, 2)],
                    "count": b.count,
                    "mean_confidence": round(b.mean_confidence, 4),
                    "accuracy": round(b.accuracy, 4),
                    "gap": round(b.gap, 4),
                }
                for b in self.reliability
            ],
        }


def calibrate_judge(
    episodes: Sequence[JudgedEpisode],
    *,
    bins: int = 10,
    ece_threshold: float = 0.1,
) -> CalibrationReport:
    """Full calibration report. ``calibrated`` iff ECE ≤ threshold.

    Pair with :func:`~.judge_audit.audit_judge` for the discrimination axis:
    only a judge that clears BOTH bars should be trusted as an evaluator.
    """
    ece = expected_calibration_error(episodes, bins=bins)
    return CalibrationReport(
        brier=brier_score(episodes),
        ece=ece,
        n=len(episodes),
        calibrated=ece <= ece_threshold,
        reliability=tuple(reliability_bins(episodes, bins=bins)),
    )


__all__ = [
    "CalibrationReport",
    "ReliabilityBin",
    "brier_score",
    "calibrate_judge",
    "expected_calibration_error",
    "reliability_bins",
]
