"""R4: genuine lift promotes with CI; noise never does; records seal the evidence."""

from __future__ import annotations

from oh_no_my_claudecode.experiment.evolve import HarnessVariant, evolve_step

TASKS = [f"t{i}" for i in range(12)]

CHAMPION = HarnessVariant.from_config("champ", {"compaction": "none"})
BETTER = HarnessVariant.from_config("better", {"compaction": "verified"})
NOISE = HarnessVariant.from_config("noise", {"compaction": "random"})


def _runner(variant_id: str, task: str) -> bool:
    # Ground truth: champion passes t0-t3; "better" passes t0-t9; "noise"
    # trades wins and losses (same rate as champion, different tasks).
    index = int(task[1:])
    if variant_id == "champ":
        return index < 4
    if variant_id == "better":
        return index < 10
    return 4 <= index < 8  # noise: 4 passes, all different from champion's


def test_genuine_lift_is_promoted_with_ci_backing() -> None:
    result = evolve_step(CHAMPION, [BETTER, NOISE], TASKS, _runner, seed=11)
    assert result.promoted is True
    assert result.winner_id == "better"
    assert result.delta_ci95[0] > 0.0  # the bar: CI excludes zero
    rates = dict(result.pass_rates)
    assert rates["better"] > rates["champ"]
    # Deterministic, hashable evidence
    again = evolve_step(CHAMPION, [BETTER, NOISE], TASKS, _runner, seed=11)
    assert again == result
    assert len(result.record_hash) == 64


def test_noise_never_dethrones_the_champion() -> None:
    result = evolve_step(CHAMPION, [NOISE], TASKS, _runner, seed=11)
    assert result.promoted is False
    assert result.winner_id == "champ"  # equal mean, different tasks → CI straddles 0


def test_no_challengers_keeps_champion_without_promotion() -> None:
    result = evolve_step(CHAMPION, [], TASKS, _runner, seed=11)
    assert result.promoted is False
    assert result.winner_id == "champ"
