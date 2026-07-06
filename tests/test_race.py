"""Tests for onmc race: cluster_by_goal, build_leaderboard, race, and the CLI.

The tournament core is exercised by injecting receipt dicts directly — no
files, no real loop/agent/clock. All numbers are deterministic. The CLI tests
seed synthetic ``run-*.json`` receipts in a temp onmc project and assert exit
codes and ``--json`` shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.race.race import (
    MIN_VERIFIED_RUNS,
    build_leaderboard,
    cluster_by_goal,
    goal_keywords,
    race,
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
        "cost_usd": cost_usd,
        "wall_seconds": wall_seconds,
    }


# ---------------------------------------------------------------------------
# goal_keywords
# ---------------------------------------------------------------------------


def test_goal_keywords_strips_stopwords_and_short_words() -> None:
    kws = goal_keywords("fix the parser bug in the CLI")
    assert "parser" in kws
    assert "bug" in kws
    assert "the" not in kws
    assert "fix" not in kws  # stopword
    assert "in" not in kws  # too short / stopword


def test_goal_keywords_dedupes_preserving_order() -> None:
    kws = goal_keywords("parser parser refactor parser")
    assert kws == ["parser", "refactor"]


# ---------------------------------------------------------------------------
# cluster_by_goal
# ---------------------------------------------------------------------------


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
    # A query that is entirely stopwords yields no keywords, so nothing
    # matches — never silently falls back to "match everything".
    receipts = [_receipt(goal="parser work")]
    matched, keywords = cluster_by_goal(receipts, "the a to of")
    assert matched == []
    assert keywords == []


def test_cluster_by_goal_no_matches_returns_empty() -> None:
    receipts = [_receipt(goal="database migration script")]
    matched, keywords = cluster_by_goal(receipts, "parser refactor")
    assert matched == []
    assert keywords == ["parser", "refactor"]


def test_cluster_by_goal_skips_uncoercible_receipts() -> None:
    receipts: list[Any] = [None, "garbage", _receipt(goal="parser work")]
    matched, _keywords = cluster_by_goal(receipts, "parser")
    assert len(matched) == 1


# ---------------------------------------------------------------------------
# build_leaderboard: verified_rate + avg math
# ---------------------------------------------------------------------------


def test_leaderboard_verified_rate_math() -> None:
    clean, _kw = cluster_by_goal(
        [
            _receipt(model="opus", verified=True, goal="parser work"),
            _receipt(model="opus", verified=True, goal="parser work"),
            _receipt(model="opus", verified=False, goal="parser work"),
            _receipt(model="sonnet", verified=False, goal="parser work"),
        ],
        "parser",
    )
    board = build_leaderboard(clean)
    by = {row.model: row for row in board}
    assert by["opus"].runs == 3
    assert by["opus"].verified == 2
    assert by["opus"].verified_rate == round(2 / 3, 4)
    assert by["sonnet"].verified_rate == 0.0


def test_leaderboard_avg_wall_math() -> None:
    clean, _kw = cluster_by_goal(
        [
            _receipt(model="m", wall_seconds=10.0, goal="parser work"),
            _receipt(model="m", wall_seconds=20.0, goal="parser work"),
            _receipt(model="m", wall_seconds=30.0, goal="parser work"),
        ],
        "parser",
    )
    board = build_leaderboard(clean)
    assert board[0].avg_wall_seconds == 20.0


def test_leaderboard_avg_cost_none_when_all_null() -> None:
    clean, _kw = cluster_by_goal(
        [_receipt(model="m", cost_usd=None, goal="parser work") for _ in range(3)],
        "parser",
    )
    board = build_leaderboard(clean)
    assert board[0].avg_cost is None  # explicitly NOT 0.0


def test_leaderboard_avg_cost_partial_averages_only_known() -> None:
    clean, _kw = cluster_by_goal(
        [
            _receipt(model="m", cost_usd=0.20, goal="parser work"),
            _receipt(model="m", cost_usd=None, goal="parser work"),
            _receipt(model="m", cost_usd=0.40, goal="parser work"),
        ],
        "parser",
    )
    board = build_leaderboard(clean)
    assert board[0].avg_cost == round((0.20 + 0.40) / 2, 4)


def test_leaderboard_ranking_orders_best_first() -> None:
    clean, _kw = cluster_by_goal(
        [_receipt(model="winner", verified=True, goal="parser work") for _ in range(3)]
        + [_receipt(model="loser", verified=False, goal="parser work") for _ in range(3)],
        "parser",
    )
    board = build_leaderboard(clean)
    assert board[0].model == "winner"
    assert board[-1].model == "loser"


def test_leaderboard_tiebreak_prefers_cheaper_then_more_runs() -> None:
    expensive = [
        _receipt(model="expensive", verified=True, cost_usd=0.50, goal="parser work")
        for _ in range(4)
    ]
    cheap = [
        _receipt(model="cheap", verified=True, cost_usd=0.01, goal="parser work") for _ in range(3)
    ]
    clean, _kw = cluster_by_goal(expensive + cheap, "parser")
    board = build_leaderboard(clean)
    # Same verified rate (100%): cheaper wins the tie.
    assert board[0].model == "cheap"


# ---------------------------------------------------------------------------
# race: winner declaration + insufficient data
# ---------------------------------------------------------------------------


def test_race_declares_winner_with_enough_verified_runs() -> None:
    receipts = [_receipt(model="opus", verified=True, goal="parser refactor") for _ in range(3)] + [
        _receipt(model="sonnet", verified=False, goal="parser refactor") for _ in range(3)
    ]
    result = race(receipts, query="parser refactor")
    assert result.winner is not None
    assert result.winner.model == "opus"
    assert result.verified_runs == 3


def test_race_insufficient_data_under_min_verified_runs() -> None:
    # Only 2 verified runs total < MIN_VERIFIED_RUNS(3).
    receipts = [_receipt(model="opus", verified=True, goal="parser refactor") for _ in range(2)]
    result = race(receipts, query="parser refactor")
    assert result.winner is None
    assert "insufficient" in result.note.lower() or "need" in result.note.lower()


def test_race_no_matches_is_insufficient() -> None:
    receipts = [_receipt(goal="totally unrelated database work")]
    result = race(receipts, query="parser refactor")
    assert result.total_runs == 0
    assert result.winner is None
    assert "no matching" in result.note.lower()


def test_race_empty_receipts_is_insufficient() -> None:
    result = race([], query="parser refactor")
    assert result.total_runs == 0
    assert result.winner is None


def test_race_all_mode_skips_clustering() -> None:
    receipts = [_receipt(model="opus", verified=True, goal="parser work") for _ in range(2)] + [
        _receipt(model="opus", verified=True, goal="database migration") for _ in range(1)
    ]
    result = race(receipts, query=None)
    assert result.query is None
    assert result.matched_keywords == []
    assert result.total_runs == 3
    assert result.winner is not None
    assert result.winner.model == "opus"


def test_race_cost_never_fabricated_in_winner() -> None:
    receipts = [
        _receipt(model="opus", verified=True, cost_usd=None, goal="parser work") for _ in range(3)
    ]
    result = race(receipts, query="parser")
    assert result.winner is not None
    assert result.winner.avg_cost is None


def test_min_verified_runs_is_three() -> None:
    # Guards the documented threshold the winner-declaration path depends on.
    assert MIN_VERIFIED_RUNS == 3


def test_race_corrupt_receipts_are_skipped_not_crashed() -> None:
    receipts: list[Any] = [
        _receipt(model="ok", verified=True, goal="parser work"),
        None,
        "garbage",
        {"verified": "not-a-bool", "wall_seconds": "abc", "cost_usd": "xyz", "goal": "parser work"},
    ]
    # Must not raise.
    result = race(receipts, query="parser")
    assert result.total_runs == 1
    assert result.leaderboard[0].model == "ok"


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def _write_receipt(receipts_dir: Path, name: str, data: dict[str, Any]) -> None:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    (receipts_dir / name).write_text(json.dumps(data), encoding="utf-8")


def test_cli_race_json_with_goal(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app

    (tmp_path / ".git").mkdir()
    receipts = tmp_path / ".agent-memory" / "receipts"
    for i in range(3):
        _write_receipt(
            receipts,
            f"run-{i}.json",
            _receipt(model="opus", verified=True, goal="parser refactor pass"),
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.race.commands.discover_repo_root",
        lambda _p: tmp_path,
    )

    result = _RUNNER.invoke(app, ["race", "parser refactor", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total_runs"] == 3
    assert payload["winner"]["model"] == "opus"


def test_cli_race_all_flag(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app

    (tmp_path / ".git").mkdir()
    receipts = tmp_path / ".agent-memory" / "receipts"
    for i in range(3):
        _write_receipt(receipts, f"run-{i}.json", _receipt(model="opus", verified=True))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.race.commands.discover_repo_root",
        lambda _p: tmp_path,
    )

    result = _RUNNER.invoke(app, ["race", "--all", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["query"] is None
    assert payload["total_runs"] == 3


def test_cli_race_requires_goal_or_all(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.race.commands.discover_repo_root",
        lambda _p: tmp_path,
    )

    result = _RUNNER.invoke(app, ["race"])
    assert result.exit_code == 1


def test_cli_race_rejects_goal_and_all_together(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.race.commands.discover_repo_root",
        lambda _p: tmp_path,
    )

    result = _RUNNER.invoke(app, ["race", "parser", "--all"])
    assert result.exit_code == 1


def test_cli_race_graceful_no_receipts(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.race.commands.discover_repo_root",
        lambda _p: tmp_path,
    )

    result = _RUNNER.invoke(app, ["race", "parser", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total_runs"] == 0
    assert payload["winner"] is None
