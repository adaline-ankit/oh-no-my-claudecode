"""Judge Audit — calibrate any LLM judge against executed ground truth.

The judge literature's cracks are known (position bias, verbosity bias,
self-preference), and our own G3 measurement found a frontier judge at
AUROC 0.485 ≈ chance on verified-vs-false-green discrimination. The missing
instrument is per-repo calibration: does THIS judge add signal on THIS
distribution? We own the ground truth others lack — executed-test outcomes —
so the audit is just statistics, no LLM required to run it.

Inputs are past episodes labeled by the gate (verified True/False) plus the
judge's score for each. Outputs: rank AUROC with a seeded bootstrap CI,
verbosity bias (rank correlation of score with response length), optional
self-preference (same-family score inflation), and a blunt verdict.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JudgedEpisode:
    """One historical episode: the gate's truth vs the judge's opinion."""

    episode_id: str
    verified: bool  # ground truth from executed verification
    judge_score: float  # the judge's confidence the episode succeeded
    response_length: int = 0  # for verbosity-bias measurement
    agent_family: str = ""  # e.g. "claude", "gpt" — for self-preference
    judge_family: str = ""


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks (1-based), ties shared — the standard rank transform."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _auroc(episodes: Sequence[JudgedEpisode]) -> float:
    """Rank AUROC (Mann-Whitney): P(score_verified > score_false), ties = ½."""
    ranks = _ranks([e.judge_score for e in episodes])
    positives = [r for r, e in zip(ranks, episodes, strict=True) if e.verified]
    n_pos, n_neg = len(positives), len(episodes) - len(positives)
    if n_pos == 0 or n_neg == 0:
        raise ValueError("audit needs both verified and false episodes")
    rank_sum = sum(positives)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman rho — rank correlation, robust to scale."""
    if len(xs) < 3:
        return 0.0
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    if vx == 0 or vy == 0:
        return 0.0
    return float(cov / (vx * vy))


@dataclass(frozen=True, slots=True)
class JudgeAuditReport:
    """The verdict on a judge, measured against executed truth."""

    auroc: float
    auroc_ci95: tuple[float, float]
    n_verified: int
    n_false: int
    verbosity_bias: float  # rho(score, length); high = pays for words
    self_preference: float | None  # same-family minus other-family mean score
    verdict: str  # "chance" | "weak" | "signal"

    def to_dict(self) -> dict[str, object]:
        return {
            "auroc": round(self.auroc, 4),
            "auroc_ci95": [round(self.auroc_ci95[0], 4), round(self.auroc_ci95[1], 4)],
            "n_verified": self.n_verified,
            "n_false": self.n_false,
            "verbosity_bias": round(self.verbosity_bias, 4),
            "self_preference": None
            if self.self_preference is None
            else round(self.self_preference, 4),
            "verdict": self.verdict,
        }


def audit_judge(
    episodes: Sequence[JudgedEpisode],
    *,
    seed: int = 0,
    resamples: int = 2000,
) -> JudgeAuditReport:
    """Score a judge against the gate's ground truth. Deterministic under seed.

    Verdict bands: CI-low > 0.5 and point ≥ 0.7 → "signal"; CI-low > 0.5 →
    "weak"; otherwise "chance" — a judge whose CI includes coin-flip earns
    no gating authority on this repo.
    """
    point = _auroc(episodes)

    rng = random.Random(seed)  # noqa: S311 — statistical bootstrap, not cryptography
    resampled: list[float] = []
    n = len(episodes)
    for _ in range(resamples):
        sample = [episodes[rng.randrange(n)] for _ in range(n)]
        try:
            resampled.append(_auroc(sample))
        except ValueError:
            continue  # a resample without both classes carries no information
    resampled.sort()
    if resampled:
        low = resampled[int(0.025 * len(resampled))]
        high = resampled[min(len(resampled) - 1, int(0.975 * len(resampled)))]
    else:
        low = high = point

    verbosity = _spearman(
        [e.judge_score for e in episodes], [float(e.response_length) for e in episodes]
    )

    self_pref: float | None = None
    same = [e.judge_score for e in episodes if e.judge_family and e.judge_family == e.agent_family]
    other = [e.judge_score for e in episodes if e.judge_family and e.agent_family != e.judge_family]
    if same and other:
        self_pref = sum(same) / len(same) - sum(other) / len(other)

    if low > 0.5 and point >= 0.7:
        verdict = "signal"
    elif low > 0.5:
        verdict = "weak"
    else:
        verdict = "chance"

    return JudgeAuditReport(
        auroc=point,
        auroc_ci95=(low, high),
        n_verified=sum(1 for e in episodes if e.verified),
        n_false=sum(1 for e in episodes if not e.verified),
        verbosity_bias=verbosity,
        self_preference=self_pref,
        verdict=verdict,
    )


__all__ = ["JudgeAuditReport", "JudgedEpisode", "audit_judge"]
