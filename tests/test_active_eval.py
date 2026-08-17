"""Active eval: informative tasks ranked first, budget buys more signal."""

from __future__ import annotations

from math import isclose

import pytest

from oh_no_my_claudecode.experiment.active_eval import (
    expected_disagreement,
    expected_information,
    rank_tasks,
    select_under_budget,
)


def test_disagreement_peaks_when_variants_diverge() -> None:
    # A always passes, B always fails -> certain disagreement
    assert expected_disagreement(1.0, 0.0) == 1.0
    # both certain to pass -> no disagreement, no information
    assert expected_disagreement(1.0, 1.0) == 0.0
    # coin flips -> 0.5
    assert isclose(expected_disagreement(0.5, 0.5), 0.5)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        expected_disagreement(1.2, 0.5)


def test_ranking_puts_divergent_tasks_first() -> None:
    prior_a = {"agree_hi": 0.95, "diverge": 0.9, "agree_lo": 0.1}
    prior_b = {"agree_hi": 0.95, "diverge": 0.1, "agree_lo": 0.1}
    ranked = rank_tasks(prior_a, prior_b)
    assert ranked[0].task_id == "diverge"  # the only informative one leads
    assert ranked[0].disagreement > ranked[1].disagreement


def test_budget_selection_beats_a_naive_pick() -> None:
    # t0/t4 are certain agreement (both 1.0) -> zero information; t1 diverges.
    prior_a = {f"t{i}": p for i, p in enumerate([1.0, 0.9, 0.5, 0.5, 1.0])}
    prior_b = {f"t{i}": p for i, p in enumerate([1.0, 0.1, 0.5, 0.5, 1.0])}
    picked = select_under_budget(prior_a, prior_b, budget=2)
    assert "t1" in picked  # 0.9 vs 0.1 -> most informative, must be chosen

    active_info = expected_information(prior_a, prior_b, picked)
    naive_info = expected_information(prior_a, prior_b, ["t0", "t4"])  # certain agree -> 0
    assert active_info > naive_info  # same 2-task cost, strictly more signal
    assert naive_info == 0.0


def test_only_common_tasks_are_rankable() -> None:
    assert rank_tasks({"x": 0.5}, {"y": 0.5}) == []
    assert select_under_budget({"a": 0.9}, {"a": 0.1}, budget=5) == ["a"]
