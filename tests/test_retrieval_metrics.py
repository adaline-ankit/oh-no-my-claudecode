"""IR metrics: known-answer cases + the edge cases a wrong metric hides in."""

from __future__ import annotations

from math import isclose

from oh_no_my_claudecode.evals.retrieval_metrics import (
    mean_scores,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    score_ranking,
)


def test_known_answers_perfect_and_reversed() -> None:
    grades = {"a": 3.0, "b": 2.0, "c": 1.0}
    perfect = ["a", "b", "c", "d"]
    assert isclose(ndcg_at_k(perfect, grades, 3), 1.0)  # ideal order -> 1.0
    assert isclose(recall_at_k(perfect, {"a", "b", "c"}, 3), 1.0)
    assert isclose(precision_at_k(perfect, {"a", "b", "c"}, 3), 1.0)

    worst = ["d", "e", "c", "b", "a"]  # relevant items pushed to the back
    assert ndcg_at_k(worst, grades, 3) < 0.5  # graded discount punishes late hits


def test_mrr_is_first_hit_rank() -> None:
    assert reciprocal_rank(["x", "y", "a"], {"a"}) == 1 / 3
    assert reciprocal_rank(["a", "y", "z"], {"a"}) == 1.0
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0  # no hit


def test_edge_cases_do_not_return_plausible_wrong_numbers() -> None:
    # no relevant items anywhere -> everything 0, never a divide-by-zero
    assert recall_at_k(["a", "b"], set(), 5) == 0.0
    assert ndcg_at_k(["a", "b"], {}, 5) == 0.0
    # k larger than the ranking is fine
    assert isclose(recall_at_k(["a"], {"a", "b"}, 10), 0.5)
    # k <= 0 precision is defined as 0, not a crash
    assert precision_at_k(["a"], {"a"}, 0) == 0.0


def test_score_and_macro_average() -> None:
    s1 = score_ranking(["a", "b"], {"a": 1.0, "b": 1.0}, k=2)
    s2 = score_ranking(["x", "a"], {"a": 1.0}, k=2)
    avg = mean_scores([s1, s2])
    assert avg.k == 2
    assert isclose(avg.mrr, (1.0 + 0.5) / 2)
    assert "ndcg_at_k" in avg.to_dict()
