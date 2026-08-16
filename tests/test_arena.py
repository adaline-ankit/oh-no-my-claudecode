"""Arena: dominance orders the ladder, equals tie, paired scores become battles."""

from __future__ import annotations

from oh_no_my_claudecode.experiment.arena import battles_from_scores, fit_ladder

TASKS = [f"t{i}" for i in range(12)]


def _scores(threshold: int) -> dict[str, float]:
    return {t: 1.0 if int(t[1:]) < threshold else 0.0 for t in TASKS}


def test_paired_scores_become_battles_and_dominance_orders_the_ladder() -> None:
    scores = {"strong": _scores(10), "mid": _scores(6), "weak": _scores(2)}
    ladder = fit_ladder(battles_from_scores(scores))
    assert [r.variant_id for r in ladder] == ["strong", "mid", "weak"]
    assert ladder[0].elo > ladder[1].elo > ladder[2].elo
    assert ladder[0].elo - ladder[2].elo > 100  # clear dominance, clear gap


def test_equal_variants_land_at_equal_elo() -> None:
    scores = {"a": _scores(6), "b": _scores(6)}  # identical outcomes → all ties
    ladder = fit_ladder(battles_from_scores(scores))
    assert abs(ladder[0].elo - ladder[1].elo) < 1e-6
    assert abs(ladder[0].elo - 1000.0) < 1e-6  # centered scale


def test_deterministic_and_needs_two_variants() -> None:
    scores = {"a": _scores(8), "b": _scores(4)}
    battles = battles_from_scores(scores)
    assert fit_ladder(battles) == fit_ladder(battles)
    import pytest

    with pytest.raises(ValueError, match="at least two"):
        fit_ladder({})
