"""Tests for onmc estimate: cluster_by_goal, build_estimate, and the CLI.

The forecasting core is exercised by injecting receipt dicts directly — no
files, no real loop/agent/clock. All numbers are deterministic. The CLI tests
seed synthetic ``run-*.json`` receipts in a temp onmc project and assert exit
codes and ``--json`` shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.estimate.estimate import (
    MIN_SIMILAR_RUNS,
    build_estimate,
    cluster_by_goal,
    goal_keywords,
)

_RUNNER = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receipt(
    *,
    model: str | None = "claude-opus-4-8",
    verified: bool = True,
    cost_usd: float | None = 0.10,
    wall_seconds: float = 60.0,
    iterations: int | None = 3,
    goal: str = "refactor the parser module",
) -> dict[str, Any]:
    """Build a minimal receipt dict (schema_version "2" keys)."""
    return {
        "schema_version": "2",
        "goal": goal,
        "agent": "claude",
        "model": model,
        "verified": verified,
        "stop_reason": "converged" if verified else "max-iterations",
        "iterations": iterations,
        "cost_usd": cost_usd,
        "wall_seconds": wall_seconds,
    }


# ---------------------------------------------------------------------------
# goal_keywords / cluster_by_goal (shared derivation, sanity-checked here too)
# ---------------------------------------------------------------------------


def test_goal_keywords_strips_stopwords_and_short_words() -> None:
    kws = goal_keywords("fix the parser bug in the CLI")
    assert "parser" in kws
    assert "bug" in kws
    assert "the" not in kws
    assert "fix" not in kws


def test_cluster_by_goal_matches_keyword_overlap() -> None:
    receipts = [
        _receipt(goal="refactor the parser module"),
        _receipt(goal="parser cleanup pass"),
        _receipt(goal="unrelated database migration"),
    ]
    matched, keywords = cluster_by_goal(receipts, "parser improvements")
    assert len(matched) == 2
    assert "parser" in keywords


def test_cluster_by_goal_empty_query_keywords_matches_nothing() -> None:
    receipts = [_receipt(goal="parser work")]
    matched, keywords = cluster_by_goal(receipts, "the a to of")
    assert matched == []
    assert keywords == []


# ---------------------------------------------------------------------------
# build_estimate: cluster matching + confident estimate
# ---------------------------------------------------------------------------


def test_build_estimate_matches_similar_cluster_only() -> None:
    receipts = [
        _receipt(goal="refactor the parser module", cost_usd=0.10),
        _receipt(goal="parser cleanup pass", cost_usd=0.20),
        _receipt(goal="parser edge cases", cost_usd=0.30),
        _receipt(goal="unrelated database migration", cost_usd=99.0),
    ]
    est = build_estimate(receipts, "parser refactor work")
    assert est.sample_size == 3
    assert "parser" in est.matched_keywords
    assert est.fallback == "none"
    assert est.confidence == "high"
    assert est.expected_cost_usd == 0.20  # median of 0.10/0.20/0.30


def test_build_estimate_median_and_range_math() -> None:
    receipts = [
        _receipt(goal="parser work", cost_usd=0.10, wall_seconds=10.0, iterations=1),
        _receipt(goal="parser work", cost_usd=0.20, wall_seconds=20.0, iterations=2),
        _receipt(goal="parser work", cost_usd=0.30, wall_seconds=30.0, iterations=3),
        _receipt(goal="parser work", cost_usd=0.40, wall_seconds=40.0, iterations=4),
    ]
    est = build_estimate(receipts, "parser")
    assert est.expected_cost_usd == 0.25  # median of 4 values averages middle two
    assert est.cost_range.low == 0.10
    assert est.cost_range.high == 0.40
    assert est.expected_wall_seconds == 25.0
    assert est.wall_seconds_range.low == 10.0
    assert est.wall_seconds_range.high == 40.0
    assert est.expected_iterations == 2.5
    assert est.iterations_range.low == 1.0
    assert est.iterations_range.high == 4.0


def test_build_estimate_verified_probability_math() -> None:
    receipts = [
        _receipt(goal="parser work", verified=True),
        _receipt(goal="parser work", verified=True),
        _receipt(goal="parser work", verified=False),
        _receipt(goal="parser work", verified=False),
    ]
    est = build_estimate(receipts, "parser")
    assert est.verified_probability == 0.5


def test_build_estimate_cost_never_fabricated_when_all_null() -> None:
    receipts = [
        _receipt(goal="parser work", cost_usd=None) for _ in range(3)
    ]
    est = build_estimate(receipts, "parser")
    assert est.expected_cost_usd is None
    assert est.cost_range.low is None
    assert est.cost_range.high is None


def test_build_estimate_cost_partial_uses_only_known() -> None:
    receipts = [
        _receipt(goal="parser work", cost_usd=0.10),
        _receipt(goal="parser work", cost_usd=None),
        _receipt(goal="parser work", cost_usd=0.30),
    ]
    est = build_estimate(receipts, "parser")
    assert est.expected_cost_usd == 0.20  # median of known costs only (0.10, 0.30)


# ---------------------------------------------------------------------------
# Model conditioning
# ---------------------------------------------------------------------------


def test_build_estimate_model_conditioning_filters_cluster() -> None:
    receipts = [
        _receipt(model="opus", goal="parser work", cost_usd=1.0),
        _receipt(model="opus", goal="parser work", cost_usd=1.0),
        _receipt(model="opus", goal="parser work", cost_usd=1.0),
        _receipt(model="sonnet", goal="parser work", cost_usd=0.10),
        _receipt(model="sonnet", goal="parser work", cost_usd=0.10),
        _receipt(model="sonnet", goal="parser work", cost_usd=0.10),
    ]
    est = build_estimate(receipts, "parser", model="sonnet")
    assert est.sample_size == 3
    assert est.expected_cost_usd == 0.10
    assert est.model == "sonnet"


def test_build_estimate_model_conditioning_can_starve_cluster() -> None:
    # Only 1 sonnet run matches the goal keyword — below MIN_SIMILAR_RUNS,
    # even though there'd be enough runs without the model filter.
    receipts = [
        _receipt(model="opus", goal="parser work", cost_usd=1.0),
        _receipt(model="opus", goal="parser work", cost_usd=1.0),
        _receipt(model="sonnet", goal="parser work", cost_usd=0.10),
        _receipt(model="sonnet", goal="totally unrelated migration", cost_usd=5.0),
        _receipt(model="sonnet", goal="totally unrelated migration", cost_usd=5.0),
    ]
    est = build_estimate(receipts, "parser", model="sonnet")
    assert est.confidence == "low"
    # Falls back to overall corpus filtered by model=sonnet (3 runs).
    assert est.fallback == "overall"
    assert est.sample_size == 3


# ---------------------------------------------------------------------------
# Insufficient-history fallback
# ---------------------------------------------------------------------------


def test_build_estimate_insufficient_similar_falls_back_to_overall() -> None:
    receipts = [
        _receipt(goal="parser work", cost_usd=0.10),  # only 1 similar run
        _receipt(goal="database migration", cost_usd=1.0),
        _receipt(goal="database migration", cost_usd=2.0),
        _receipt(goal="database migration", cost_usd=3.0),
    ]
    est = build_estimate(receipts, "parser refactor")
    assert est.fallback == "overall"
    assert est.confidence == "low"
    assert est.sample_size == 4  # falls back to the whole corpus
    assert "not enough similar history" in est.note.lower()


def test_build_estimate_overall_corpus_also_thin() -> None:
    receipts = [_receipt(goal="parser work", cost_usd=0.10)]
    est = build_estimate(receipts, "parser refactor")
    assert est.fallback == "overall"
    assert est.sample_size == 1
    assert "too few" in est.note.lower() or "only" in est.note.lower()


# ---------------------------------------------------------------------------
# Empty-state
# ---------------------------------------------------------------------------


def test_build_estimate_no_history_at_all() -> None:
    est = build_estimate([], "parser refactor")
    assert est.fallback == "empty"
    assert est.sample_size == 0
    assert est.expected_cost_usd is None
    assert est.verified_probability is None
    assert "no run receipts found" in est.note.lower()


def test_build_estimate_no_history_for_requested_model() -> None:
    receipts = [_receipt(model="opus", goal="parser work") for _ in range(5)]
    est = build_estimate(receipts, "parser", model="gpt-5")
    assert est.fallback == "empty"
    assert est.sample_size == 0


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


def test_build_estimate_corrupt_receipts_are_skipped_not_crashed() -> None:
    receipts: list[Any] = [
        _receipt(goal="parser work"),
        _receipt(goal="parser work"),
        _receipt(goal="parser work"),
        None,
        "garbage",
        {"verified": "not-a-bool", "wall_seconds": "abc", "cost_usd": "xyz", "goal": "parser work"},
    ]
    # Must not raise.
    est = build_estimate(receipts, "parser")
    assert est.sample_size == 3


def test_min_similar_runs_is_three() -> None:
    assert MIN_SIMILAR_RUNS == 3


def test_build_estimate_deterministic_repeat_calls() -> None:
    receipts = [
        _receipt(goal="parser work", cost_usd=0.10 * i, wall_seconds=float(i)) for i in range(1, 5)
    ]
    est1 = build_estimate(receipts, "parser")
    est2 = build_estimate(receipts, "parser")
    assert est1.to_dict() == est2.to_dict()


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def _write_receipt(receipts_dir: Path, name: str, data: dict[str, Any]) -> None:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    (receipts_dir / name).write_text(json.dumps(data), encoding="utf-8")


def test_cli_estimate_json_with_goal(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app

    (tmp_path / ".git").mkdir()
    receipts = tmp_path / ".agent-memory" / "receipts"
    for i in range(3):
        _write_receipt(
            receipts,
            f"run-{i}.json",
            _receipt(goal="parser refactor pass", cost_usd=0.10 * (i + 1)),
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.estimate.commands.discover_repo_root",
        lambda _p: tmp_path,
    )

    result = _RUNNER.invoke(app, ["estimate", "parser refactor", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["sample_size"] == 3
    assert payload["fallback"] == "none"


def test_cli_estimate_with_model_flag(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app

    (tmp_path / ".git").mkdir()
    receipts = tmp_path / ".agent-memory" / "receipts"
    for i in range(3):
        _write_receipt(
            receipts, f"run-{i}.json", _receipt(model="sonnet", goal="parser work")
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.estimate.commands.discover_repo_root",
        lambda _p: tmp_path,
    )

    result = _RUNNER.invoke(app, ["estimate", "parser", "--model", "sonnet", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["model"] == "sonnet"
    assert payload["sample_size"] == 3


def test_cli_estimate_graceful_no_receipts(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.estimate.commands.discover_repo_root",
        lambda _p: tmp_path,
    )

    result = _RUNNER.invoke(app, ["estimate", "parser", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["fallback"] == "empty"
    assert payload["sample_size"] == 0
