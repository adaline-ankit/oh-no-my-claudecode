"""Tests for ``onmc whip`` — steering directive queue + reward signal ledger.

Coverage
--------
- enqueue + pending FIFO order within each kind.
- consume returns redirects before nudges (priority order), then empties queue.
- clear empties the queue and returns the count.
- record_signal appends treat / crack to rewards.jsonl.
- tally aggregates correctly per goal and per agent.
- empty-state: all functions graceful on absent directory / empty files.
- determinism: two identical enqueue calls produce identical records (given same ts).
- --json CLI envelope shape for pending, clear, tally.
- invalid kind raises ValueError (pure, no I/O).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.whip.steer import (
    clear,
    consume,
    enqueue,
    pending,
    record_signal,
    tally,
)

_RUNNER = CliRunner()
_TS = "2026-07-05T00:00:00+00:00"
_TS2 = "2026-07-05T00:01:00+00:00"
_TS3 = "2026-07-05T00:02:00+00:00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _whip_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".onmc" / "whip"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Directive queue — enqueue + pending (FIFO within kind)
# ---------------------------------------------------------------------------


def test_enqueue_nudge_fifo(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    enqueue("nudge", "first nudge", whip_dir=wd, ts=_TS)
    enqueue("nudge", "second nudge", whip_dir=wd, ts=_TS2)
    items = pending(whip_dir=wd)
    assert len(items) == 2
    assert items[0]["msg"] == "first nudge"
    assert items[1]["msg"] == "second nudge"
    assert items[0]["kind"] == "nudge"


def test_enqueue_redirect_before_nudge_in_pending(tmp_path: Path) -> None:
    """Redirects surface before nudges regardless of insertion order."""
    wd = _whip_dir(tmp_path)
    enqueue("nudge", "gentle", whip_dir=wd, ts=_TS)
    enqueue("redirect", "STOP", whip_dir=wd, ts=_TS2)
    items = pending(whip_dir=wd)
    assert items[0]["kind"] == "redirect"
    assert items[1]["kind"] == "nudge"


def test_pending_does_not_consume(tmp_path: Path) -> None:
    """pending() is read-only — calling it twice returns same items."""
    wd = _whip_dir(tmp_path)
    enqueue("nudge", "hello", whip_dir=wd, ts=_TS)
    first = pending(whip_dir=wd)
    second = pending(whip_dir=wd)
    assert first == second
    assert len(first) == 1


# ---------------------------------------------------------------------------
# consume — priority order + atomically empties queue
# ---------------------------------------------------------------------------


def test_consume_priority_order(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    enqueue("nudge", "nudge-A", whip_dir=wd, ts=_TS)
    enqueue("redirect", "redirect-B", whip_dir=wd, ts=_TS2)
    enqueue("nudge", "nudge-C", whip_dir=wd, ts=_TS3)
    items = consume(whip_dir=wd)
    assert items[0]["kind"] == "redirect"
    assert items[0]["msg"] == "redirect-B"
    assert items[1]["msg"] == "nudge-A"
    assert items[2]["msg"] == "nudge-C"


def test_consume_empties_queue(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    enqueue("nudge", "one", whip_dir=wd, ts=_TS)
    first = consume(whip_dir=wd)
    assert len(first) == 1
    second = consume(whip_dir=wd)
    assert second == []


def test_consume_empty_state_graceful(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    result = consume(whip_dir=wd)
    assert result == []


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_returns_count(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    enqueue("nudge", "a", whip_dir=wd, ts=_TS)
    enqueue("redirect", "b", whip_dir=wd, ts=_TS2)
    count = clear(whip_dir=wd)
    assert count == 2
    assert pending(whip_dir=wd) == []


def test_clear_empty_returns_zero(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    assert clear(whip_dir=wd) == 0


# ---------------------------------------------------------------------------
# record_signal + tally
# ---------------------------------------------------------------------------


def test_record_treat_and_crack(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    record_signal("treat", goal="refactor parser", agent="claude", reason="clean",
                  whip_dir=wd, ts=_TS)
    record_signal("crack", goal="refactor parser", agent="claude", reason="missed test",
                  whip_dir=wd, ts=_TS2)
    t = tally(whip_dir=wd)
    assert t["treats"] == 1
    assert t["cracks"] == 1
    assert t["total"] == 2


def test_tally_aggregates_per_goal(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    record_signal("treat", goal="goal-A", agent="x", reason="", whip_dir=wd, ts=_TS)
    record_signal("treat", goal="goal-A", agent="x", reason="", whip_dir=wd, ts=_TS2)
    record_signal("crack", goal="goal-B", agent="x", reason="", whip_dir=wd, ts=_TS3)
    t = tally(whip_dir=wd)
    assert t["by_goal"]["goal-A"] == {"treats": 2, "cracks": 0}
    assert t["by_goal"]["goal-B"] == {"treats": 0, "cracks": 1}


def test_tally_aggregates_per_agent(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    record_signal("treat", goal="g", agent="agent-1", reason="", whip_dir=wd, ts=_TS)
    record_signal("crack", goal="g", agent="agent-2", reason="", whip_dir=wd, ts=_TS2)
    t = tally(whip_dir=wd)
    assert t["by_agent"]["agent-1"] == {"treats": 1, "cracks": 0}
    assert t["by_agent"]["agent-2"] == {"treats": 0, "cracks": 1}


def test_tally_empty_state(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    t = tally(whip_dir=wd)
    assert t["total"] == 0
    assert t["treats"] == 0
    assert t["cracks"] == 0
    assert t["by_goal"] == {}
    assert t["by_agent"] == {}


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_enqueue_deterministic(tmp_path: Path) -> None:
    """Two identical enqueue calls with same ts produce identical records."""
    wd1 = tmp_path / "w1"
    wd2 = tmp_path / "w2"
    wd1.mkdir()
    wd2.mkdir()
    r1 = enqueue("nudge", "same msg", whip_dir=wd1, ts=_TS)
    r2 = enqueue("nudge", "same msg", whip_dir=wd2, ts=_TS)
    assert r1 == r2


# ---------------------------------------------------------------------------
# Invalid kind raises ValueError (pure, no I/O)
# ---------------------------------------------------------------------------


def test_invalid_directive_kind_raises(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    with pytest.raises(ValueError, match="nudge.*redirect"):
        enqueue("shout", "bad", whip_dir=wd, ts=_TS)


def test_invalid_signal_kind_raises(tmp_path: Path) -> None:
    wd = _whip_dir(tmp_path)
    with pytest.raises(ValueError, match="treat.*crack"):
        record_signal("bribe", goal="g", agent="a", reason="", whip_dir=wd, ts=_TS)


# ---------------------------------------------------------------------------
# CLI --json envelope shape
# ---------------------------------------------------------------------------


def test_cli_pending_json_envelope(tmp_path: Path) -> None:
    """``onmc whip pending --json`` emits {kind, directives} envelope."""
    result = _RUNNER.invoke(app, ["whip", "pending", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["kind"] == "whip_pending"
    assert isinstance(data["directives"], list)


def test_cli_tally_json_envelope(tmp_path: Path) -> None:
    """``onmc whip tally --json`` emits {kind, tally} envelope."""
    result = _RUNNER.invoke(app, ["whip", "tally", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["kind"] == "whip_tally"
    assert "treats" in data["tally"]
    assert "cracks" in data["tally"]


def test_cli_clear_json_envelope(tmp_path: Path) -> None:
    """``onmc whip clear --json`` emits {kind, discarded} envelope."""
    result = _RUNNER.invoke(app, ["whip", "clear", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["kind"] == "whip_clear"
    assert isinstance(data["discarded"], int)
