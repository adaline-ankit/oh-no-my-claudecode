"""Judge audit: good judges earn 'signal', coin-flips earn 'chance', biases surface."""

from __future__ import annotations

from oh_no_my_claudecode.evals.judge_audit import JudgedEpisode, audit_judge


def _episodes(scorer, n: int = 40) -> list[JudgedEpisode]:
    episodes = []
    for i in range(n):
        verified = i % 2 == 0
        episodes.append(
            JudgedEpisode(
                episode_id=f"e{i}",
                verified=verified,
                judge_score=scorer(i, verified),
                response_length=100 + i * 37,
                agent_family="claude" if i % 4 < 2 else "gpt",
                judge_family="claude",
            )
        )
    return episodes


def test_discriminating_judge_earns_signal() -> None:
    report = audit_judge(_episodes(lambda i, v: 0.9 if v else 0.1), seed=3)
    assert report.verdict == "signal"
    assert report.auroc == 1.0
    assert report.auroc_ci95[0] > 0.5


def test_coin_flip_judge_earns_chance_g3_finding() -> None:
    # Score depends only on episode index parity-of-3 — uncorrelated with truth.
    report = audit_judge(_episodes(lambda i, v: (i % 3) / 2), seed=3)
    assert report.verdict == "chance"
    assert report.auroc_ci95[0] <= 0.5  # CI includes the coin flip


def test_verbosity_and_self_preference_biases_surface() -> None:
    # Judge pays for words: score is a pure function of response length.
    report = audit_judge(_episodes(lambda i, v: 100 + i * 37), seed=3)
    assert report.verbosity_bias > 0.95
    # Same-family inflation: claude-judged claude episodes scored higher.
    inflated = audit_judge(_episodes(lambda i, v: 0.8 if (i % 4 < 2) else 0.4), seed=3)
    assert inflated.self_preference is not None and inflated.self_preference > 0.3


def test_deterministic_under_seed() -> None:
    episodes = _episodes(lambda i, v: 0.7 if v else 0.3)
    assert audit_judge(episodes, seed=11) == audit_judge(episodes, seed=11)
