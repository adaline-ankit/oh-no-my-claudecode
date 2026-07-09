"""Tests for the ``onmc budget`` token/cost guardian.

Covers the pure decision core (:func:`evaluate` thresholds incl. exact
boundaries, deny-nothing when uncapped), the impure boundary
(:func:`check_budget` summing spend over a window from seeded receipts, window
filtering by an injected ``now_ms``), config round-tripping (:func:`set_cap`),
and the CLI (``budget check`` exiting non-zero when blocked). CLI assertions
exercise flags via ``CliRunner`` and never assert on Rich ``--help`` output.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.budget.config import (
    DEFAULT_WARN_RATIO,
    DEFAULT_WINDOW,
    BudgetConfig,
    budget_config_path,
    load_budget_config,
    save_budget_config,
    set_cap,
)
from oh_no_my_claudecode.budget.guard import (
    BudgetDecision,
    check_budget,
    evaluate,
    sum_spend,
)
from oh_no_my_claudecode.cli import app

_RUNNER = CliRunner()
_NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)
_NOW_MS = int(_NOW.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _receipt(
    *,
    goal: str = "do a thing",
    model: str | None = "claude-opus-4-8",
    verified: bool = True,
    cost_usd: float | None = 0.10,
    started_at: str | None = "2026-07-06T10:00:00Z",
    ended_at: str | None = "2026-07-06T10:01:00Z",
) -> dict[str, Any]:
    """Build a minimal receipt dict matching schema_version "2" keys."""
    return {
        "schema_version": "2",
        "goal": goal,
        "agent": "claude",
        "model": model,
        "verified": verified,
        "cost_usd": cost_usd,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def _write_receipt(receipts_dir: Path, filename: str, **kw: Any) -> Path:
    receipts_dir.mkdir(parents=True, exist_ok=True)
    dest = receipts_dir / filename
    dest.write_text(json.dumps(_receipt(**kw)), encoding="utf-8")
    return dest


def _make_git_repo(tmp_path: Path) -> None:
    """Initialise a bare git repo so ``discover_repo_root`` succeeds."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)


# ---------------------------------------------------------------------------
# evaluate() — pure thresholds
# ---------------------------------------------------------------------------


def test_evaluate_ok_below_warn() -> None:
    d = evaluate(5.0, 100.0, warn_ratio=0.8)
    assert d.state == "ok"
    assert d.allowed is True
    assert d.ratio == 0.05


def test_evaluate_warn_at_exact_warn_boundary() -> None:
    # spend == warn_ratio * cap → warn (inclusive boundary).
    d = evaluate(80.0, 100.0, warn_ratio=0.8)
    assert d.state == "warn"
    assert d.allowed is True


def test_evaluate_warn_between_thresholds() -> None:
    d = evaluate(90.0, 100.0, warn_ratio=0.8)
    assert d.state == "warn"
    assert d.allowed is True


def test_evaluate_blocked_at_exact_cap_boundary() -> None:
    # spend == cap → blocked (inclusive boundary), not allowed.
    d = evaluate(100.0, 100.0, warn_ratio=0.8)
    assert d.state == "blocked"
    assert d.allowed is False


def test_evaluate_blocked_over_cap() -> None:
    d = evaluate(150.0, 100.0)
    assert d.state == "blocked"
    assert d.allowed is False
    assert d.ratio == 1.5


def test_evaluate_no_cap_is_ok_and_allowed() -> None:
    # No cap configured must NEVER block — deny-nothing default.
    d = evaluate(9999.0, None)
    assert d.state == "ok"
    assert d.allowed is True
    assert d.cap_usd is None
    assert d.ratio == 0.0


def test_evaluate_zero_cap_blocks_any_spend() -> None:
    d = evaluate(0.01, 0.0)
    assert d.state == "blocked"
    assert d.allowed is False
    assert d.ratio == 1.0


def test_evaluate_is_frozen() -> None:
    d = evaluate(1.0, 10.0)
    assert isinstance(d, BudgetDecision)
    try:
        d.allowed = False  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("BudgetDecision should be frozen")


# ---------------------------------------------------------------------------
# sum_spend / check_budget — window filtering + summation
# ---------------------------------------------------------------------------


def test_sum_spend_day_window_sums_known_costs() -> None:
    receipts = [
        _receipt(goal="a", cost_usd=5.0),
        _receipt(goal="b", cost_usd=None),  # unknown cost contributes nothing
        _receipt(goal="c", cost_usd=2.5),
    ]
    assert sum_spend(receipts, window="day", now=_NOW) == 7.5


def test_check_budget_no_config_is_unlimited(tmp_path: Path) -> None:
    # Even with expensive receipts, no config → never blocks.
    _write_receipt(tmp_path / ".agent-memory" / "receipts", "run-a.json", cost_usd=1000.0)
    d = check_budget(tmp_path, now_ms=_NOW_MS)
    assert d.cap_usd is None
    assert d.state == "ok"
    assert d.allowed is True


def test_check_budget_blocks_when_over_cap(tmp_path: Path) -> None:
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-a.json", cost_usd=30.0)
    _write_receipt(receipts_dir, "run-b.json", cost_usd=25.0)
    set_cap(tmp_path, 50.0, "day", 0.8)

    d = check_budget(tmp_path, now_ms=_NOW_MS)
    assert d.spend_usd == 55.0
    assert d.state == "blocked"
    assert d.allowed is False


def test_check_budget_ok_when_under_cap(tmp_path: Path) -> None:
    _write_receipt(tmp_path / ".agent-memory" / "receipts", "run-a.json", cost_usd=10.0)
    set_cap(tmp_path, 50.0, "day", 0.8)

    d = check_budget(tmp_path, now_ms=_NOW_MS)
    assert d.spend_usd == 10.0
    assert d.state == "ok"
    assert d.allowed is True


def test_check_budget_window_excludes_old_receipts(tmp_path: Path) -> None:
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    # Recent receipt: inside a 1-day window ending at _NOW.
    _write_receipt(
        receipts_dir,
        "run-recent.json",
        cost_usd=5.0,
        started_at="2026-07-06T10:00:00Z",
        ended_at="2026-07-06T10:01:00Z",
    )
    # Old receipt: 16 days before _NOW — outside the day window.
    _write_receipt(
        receipts_dir,
        "run-old.json",
        cost_usd=100.0,
        started_at="2026-06-20T10:00:00Z",
        ended_at="2026-06-20T10:01:00Z",
    )
    set_cap(tmp_path, 50.0, "day", 0.8)

    day = check_budget(tmp_path, now_ms=_NOW_MS)
    # Old $100 receipt is excluded by the day window → only $5 counts.
    assert day.spend_usd == 5.0
    assert day.state == "ok"
    assert day.allowed is True


def test_check_budget_all_window_includes_old_receipts(tmp_path: Path) -> None:
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-recent.json", cost_usd=5.0)
    _write_receipt(
        receipts_dir,
        "run-old.json",
        cost_usd=100.0,
        started_at="2026-06-20T10:00:00Z",
        ended_at="2026-06-20T10:01:00Z",
    )
    set_cap(tmp_path, 50.0, "all", 0.8)

    d = check_budget(tmp_path, now_ms=_NOW_MS)
    # "all" window spans back to the oldest receipt → both count.
    assert d.spend_usd == 105.0
    assert d.state == "blocked"
    assert d.allowed is False


# ---------------------------------------------------------------------------
# config — round-trip + idempotency
# ---------------------------------------------------------------------------


def test_set_cap_round_trips(tmp_path: Path) -> None:
    path = set_cap(tmp_path, 25.0, "week", 0.75)
    assert path == budget_config_path(tmp_path)
    cfg = load_budget_config(tmp_path)
    assert cfg.cap_usd == 25.0
    assert cfg.window == "week"
    assert cfg.warn_ratio == 0.75


def test_set_cap_is_idempotent(tmp_path: Path) -> None:
    p1 = set_cap(tmp_path, 25.0, "week", 0.75)
    first = p1.read_text(encoding="utf-8")
    p2 = set_cap(tmp_path, 25.0, "week", 0.75)
    second = p2.read_text(encoding="utf-8")
    assert first == second


def test_negative_cap_becomes_unlimited(tmp_path: Path) -> None:
    set_cap(tmp_path, -1.0, "day", 0.8)
    cfg = load_budget_config(tmp_path)
    assert cfg.cap_usd is None


def test_load_missing_config_is_unlimited(tmp_path: Path) -> None:
    cfg = load_budget_config(tmp_path)
    assert cfg == BudgetConfig()
    assert cfg.cap_usd is None
    assert cfg.window == DEFAULT_WINDOW
    assert cfg.warn_ratio == DEFAULT_WARN_RATIO


def test_load_malformed_config_is_unlimited(tmp_path: Path) -> None:
    path = budget_config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")
    cfg = load_budget_config(tmp_path)
    assert cfg.cap_usd is None


def test_save_config_clamps_warn_ratio(tmp_path: Path) -> None:
    save_budget_config(tmp_path, BudgetConfig(cap_usd=10.0, window="day", warn_ratio=5.0))
    cfg = load_budget_config(tmp_path)
    assert cfg.warn_ratio == 1.0


def test_invalid_window_falls_back_to_default(tmp_path: Path) -> None:
    set_cap(tmp_path, 10.0, "fortnight", 0.8)
    cfg = load_budget_config(tmp_path)
    assert cfg.window == DEFAULT_WINDOW


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_check_exits_nonzero_when_blocked(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    _write_receipt(tmp_path / ".agent-memory" / "receipts", "run-a.json", cost_usd=100.0)
    # window "all" so the verdict is deterministic regardless of the real clock.
    set_cap(tmp_path, 10.0, "all", 0.8)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["budget", "check", "--json"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["state"] == "blocked"
    assert data["allowed"] is False


def test_cli_check_exits_zero_when_ok(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    _write_receipt(tmp_path / ".agent-memory" / "receipts", "run-a.json", cost_usd=1.0)
    set_cap(tmp_path, 100.0, "all", 0.8)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["budget", "check", "--json"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
    assert json.loads(result.output)["state"] == "ok"


def test_cli_check_uncapped_exits_zero(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    _write_receipt(tmp_path / ".agent-memory" / "receipts", "run-a.json", cost_usd=9999.0)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["budget", "check", "--json"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
    assert json.loads(result.output)["cap_usd"] is None


def test_cli_status_json_shape(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    _write_receipt(tmp_path / ".agent-memory" / "receipts", "run-a.json", cost_usd=5.0)
    set_cap(tmp_path, 50.0, "all", 0.8)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["budget", "status", "--json"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
    data = json.loads(result.output)
    for key in ("allowed", "spend_usd", "cap_usd", "ratio", "state", "window", "reason"):
        assert key in data


def test_cli_status_never_changes_exit_code_when_blocked(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    _write_receipt(tmp_path / ".agent-memory" / "receipts", "run-a.json", cost_usd=100.0)
    set_cap(tmp_path, 10.0, "all", 0.8)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(app, ["budget", "status", "--json"], catch_exceptions=False)
    finally:
        os.chdir(orig)

    # status is read-only: blocked state, but always exit 0.
    assert result.exit_code == 0
    assert json.loads(result.output)["state"] == "blocked"


def test_cli_set_writes_config(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(
            app,
            ["budget", "set", "--cap-usd", "42", "--window", "week", "--warn-ratio", "0.9"],
            catch_exceptions=False,
        )
    finally:
        os.chdir(orig)

    assert result.exit_code == 0
    cfg = load_budget_config(tmp_path)
    assert cfg.cap_usd == 42.0
    assert cfg.window == "week"
    assert cfg.warn_ratio == 0.9


def test_cli_set_rejects_bad_window(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(
            app,
            ["budget", "set", "--cap-usd", "42", "--window", "century"],
            catch_exceptions=False,
        )
    finally:
        os.chdir(orig)

    assert result.exit_code == 1


def test_cli_check_notify_writes_notify_log(tmp_path: Path) -> None:
    _make_git_repo(tmp_path)
    _write_receipt(tmp_path / ".agent-memory" / "receipts", "run-a.json", cost_usd=100.0)
    set_cap(tmp_path, 10.0, "all", 0.8)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _RUNNER.invoke(
            app, ["budget", "check", "--json", "--notify"], catch_exceptions=False
        )
    finally:
        os.chdir(orig)

    assert result.exit_code == 1
    # FileSink is the default notify sink → a JSONL alert should be recorded.
    log_path = tmp_path / ".onmc" / "notify.log"
    assert log_path.exists()
    assert "budget" in log_path.read_text(encoding="utf-8").lower()
