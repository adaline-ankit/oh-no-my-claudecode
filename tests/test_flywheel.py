"""Tests for onmc flywheel: summarize, recommend, and the CLI command.

The aggregation core is exercised by injecting receipt dicts directly — no
files, no real loop/agent/clock.  All numbers are deterministic.  The CLI tests
seed synthetic ``run-*.json`` receipts in a temp onmc project and assert exit
codes and ``--json`` shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.flywheel.analyze import (
    MIN_SAMPLES,
    load_trajectories,
    recommend,
    summarize,
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
    started_at: str | None = None,
    ended_at: str | None = None,
) -> dict[str, Any]:
    """Build a minimal trajectory receipt dict (schema_version "2" keys)."""
    return {
        "schema_version": "2",
        "goal": goal,
        "agent": "claude",
        "model": model,
        "verified": verified,
        "stop_reason": "converged" if verified else "max-iterations",
        "cost_usd": cost_usd,
        "wall_seconds": wall_seconds,
        "started_at": started_at,
        "ended_at": ended_at,
    }


# ---------------------------------------------------------------------------
# summarize: verified_rate math
# ---------------------------------------------------------------------------


def test_verified_rate_math_per_model() -> None:
    trajectories = [
        _receipt(model="opus", verified=True),
        _receipt(model="opus", verified=True),
        _receipt(model="opus", verified=False),
        _receipt(model="sonnet", verified=False),
        _receipt(model="sonnet", verified=False),
    ]
    report = summarize(trajectories)

    assert report.total == 5
    assert report.verified_total == 2

    by = {s.model: s for s in report.by_model}
    assert by["opus"].runs == 3
    assert by["opus"].verified == 2
    assert by["opus"].verified_rate == round(2 / 3, 4)
    assert by["sonnet"].runs == 2
    assert by["sonnet"].verified == 0
    assert by["sonnet"].verified_rate == 0.0


def test_avg_wall_math() -> None:
    report = summarize(
        [
            _receipt(model="m", wall_seconds=10.0),
            _receipt(model="m", wall_seconds=20.0),
            _receipt(model="m", wall_seconds=30.0),
        ]
    )
    assert report.by_model[0].avg_wall == 20.0


# ---------------------------------------------------------------------------
# avg_cost is None (n/a) when all costs null — never fabricated 0.0
# ---------------------------------------------------------------------------


def test_avg_cost_is_none_when_all_costs_null() -> None:
    report = summarize(
        [
            _receipt(model="m", cost_usd=None),
            _receipt(model="m", cost_usd=None),
            _receipt(model="m", cost_usd=None),
        ]
    )
    stat = report.by_model[0]
    assert stat.avg_cost is None  # explicitly NOT 0.0
    assert "n/a" in report.note.lower()


def test_avg_cost_partial_averages_only_known() -> None:
    report = summarize(
        [
            _receipt(model="m", cost_usd=0.20),
            _receipt(model="m", cost_usd=None),
            _receipt(model="m", cost_usd=0.40),
        ]
    )
    # Mean over the two runs that reported a cost, not over all three.
    assert report.by_model[0].avg_cost == round((0.20 + 0.40) / 2, 4)
    assert "partial" in report.note.lower()


# ---------------------------------------------------------------------------
# ranking: best model first
# ---------------------------------------------------------------------------


def test_ranking_orders_best_model_first() -> None:
    trajectories = (
        [_receipt(model="winner", verified=True) for _ in range(3)]
        + [_receipt(model="loser", verified=False) for _ in range(3)]
    )
    report = summarize(trajectories)
    assert report.by_model[0].model == "winner"
    assert report.best is not None and report.best.model == "winner"
    assert report.worst is not None and report.worst.model == "loser"


def test_ranking_tiebreak_prefers_more_runs_then_cheaper() -> None:
    # Same verified rate (100%): more runs wins; then cheaper.
    trajectories = (
        [_receipt(model="big", verified=True, cost_usd=0.50) for _ in range(4)]
        + [_receipt(model="small", verified=True, cost_usd=0.01) for _ in range(3)]
    )
    report = summarize(trajectories)
    assert report.by_model[0].model == "big"  # more runs breaks the rate tie


# ---------------------------------------------------------------------------
# recommend: insufficient data path
# ---------------------------------------------------------------------------


def test_recommend_insufficient_data_under_min_samples() -> None:
    report = summarize([_receipt(), _receipt()])  # 2 < MIN_SAMPLES(3)
    tips = recommend(report)
    assert len(tips) == 1
    assert "insufficient data" in tips[0]
    assert "2 runs" in tips[0]


def test_recommend_empty_is_insufficient() -> None:
    report = summarize([])
    tips = recommend(report)
    assert len(tips) == 1
    assert "insufficient data (0 runs)" in tips[0]


def test_recommend_names_best_model_when_enough_samples() -> None:
    trajectories = (
        [_receipt(model="opus", verified=True) for _ in range(3)]
        + [_receipt(model="sonnet", verified=False) for _ in range(3)]
    )
    report = summarize(trajectories)
    tips = recommend(report)
    assert any("prefer opus" in t for t in tips)
    assert any("avoid" in t and "sonnet" in t for t in tips)


def test_recommend_cost_shows_na_not_fabricated() -> None:
    trajectories = [_receipt(model="m", verified=True, cost_usd=None) for _ in range(3)]
    report = summarize(trajectories)
    tips = recommend(report)
    assert any("n/a" in t for t in tips)
    assert not any("$0.0000" in t for t in tips)


# ---------------------------------------------------------------------------
# goal keyword grouping + per-keyword winner
# ---------------------------------------------------------------------------


def test_goal_keyword_winner() -> None:
    trajectories = [
        _receipt(model="opus", verified=True, goal="fix the parser bug"),
        _receipt(model="opus", verified=True, goal="parser refactor pass"),
        _receipt(model="sonnet", verified=False, goal="parser cleanup"),
    ]
    report = summarize(trajectories)
    kw = {s.keyword: s for s in report.by_goal_keyword}
    assert "parser" in kw
    assert kw["parser"].runs == 3
    assert kw["parser"].best_model == "opus"
    assert kw["parser"].best_model_verified == 2
    # stopwords like "the" and "fix" are excluded
    assert "the" not in kw
    assert "fix" not in kw


def test_recommend_surfaces_goal_keyword_winner() -> None:
    trajectories = (
        [_receipt(model="opus", verified=True, goal="parser work") for _ in range(2)]
        + [_receipt(model="opus", verified=True, goal="database migration") for _ in range(2)]
    )
    report = summarize(trajectories)
    tips = recommend(report)
    assert any("for goals like" in t for t in tips)


# ---------------------------------------------------------------------------
# corrupt / missing-key receipts are skipped, not crashed
# ---------------------------------------------------------------------------


def test_corrupt_and_missing_key_receipts_are_skipped() -> None:
    trajectories: list[Any] = [
        _receipt(model="ok", verified=True),
        None,  # not a dict
        "garbage",  # not a dict
        {},  # empty — treated as unknown/unverified, still counts as a run
        # bad types -> skipped
        {"verified": "not-a-bool", "wall_seconds": "abc", "cost_usd": "xyz"},
        {"model": "partial", "verified": True},  # missing cost/wall -> defaults
    ]
    # Must not raise.
    report = summarize(trajectories)
    models = {s.model for s in report.by_model}
    assert "ok" in models
    assert "partial" in models
    # empty dict -> model "unknown"
    assert "unknown" in models
    # The bad-types receipt was dropped: total counts only coercible dicts.
    assert report.total == 3


def test_missing_cost_key_treated_as_unknown_not_zero() -> None:
    report = summarize(
        [
            {"model": "m", "verified": True, "wall_seconds": 5.0},  # no cost_usd key
            {"model": "m", "verified": True, "wall_seconds": 5.0},
            {"model": "m", "verified": True, "wall_seconds": 5.0},
        ]
    )
    assert report.by_model[0].avg_cost is None  # not 0.0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def _write_receipt(receipts_dir: Path, name: str, data: dict[str, Any]) -> None:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    (receipts_dir / name).write_text(json.dumps(data), encoding="utf-8")


def test_load_trajectories_reads_receipt_dir(tmp_path: Path) -> None:
    receipts = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts, "run-1.json", _receipt(model="opus", verified=True))
    _write_receipt(receipts, "run-2.json", _receipt(model="sonnet", verified=False))
    # a corrupt file must be skipped, not crash
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / "run-bad.json").write_text("{not json", encoding="utf-8")

    loaded = load_trajectories(tmp_path)
    assert len(loaded) == 2
    report = summarize(loaded)
    assert report.total == 2


def test_load_trajectories_missing_dir_is_empty(tmp_path: Path) -> None:
    assert load_trajectories(tmp_path) == []


def test_cli_flywheel_json(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app

    # Make cwd + repo root resolve to the temp project.
    (tmp_path / ".git").mkdir()
    receipts = tmp_path / ".agent-memory" / "receipts"
    for i in range(3):
        _write_receipt(receipts, f"run-{i}.json", _receipt(model="opus", verified=True))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.flywheel.commands.discover_repo_root",
        lambda _p: tmp_path,
    )

    result = _RUNNER.invoke(app, ["flywheel", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 3
    assert payload["verified_total"] == 3
    assert payload["best"]["model"] == "opus"
    assert "recommendations" in payload


def test_cli_flywheel_graceful_no_receipts(tmp_path: Path, monkeypatch: Any) -> None:
    from oh_no_my_claudecode.cli import app

    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.flywheel.commands.discover_repo_root",
        lambda _p: tmp_path,
    )

    result = _RUNNER.invoke(app, ["flywheel", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total"] == 0
    assert "insufficient data" in payload["recommendations"][0]


def test_min_samples_is_three() -> None:
    # Guards the documented threshold the recommend path depends on.
    assert MIN_SAMPLES == 3
