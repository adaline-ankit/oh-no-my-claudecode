"""Tests for ``onmc bounty`` — task wager + payout ledger.

Coverage
--------
- post creates a bounty with correct fields.
- list_bounties returns only open bounties when filtered; all when unfiltered.
- payout multiplier: easy=1×, med=2×, hard=3×.
- claim awards payout, updates board status, appends to ledger.
- balance sums ledger entries after multiple claims.
- forfeit closes bounty unpaid (no ledger entry).
- balance returns 0 on empty dir.
- determinism: same inputs produce same payout.
- --json CLI envelope shapes for post, list, board, claim, balance.
- unknown id graceful error (KeyError → exit code 1).
- invalid difficulty raises ValueError (pure, no I/O).
- claim on non-open bounty raises ValueError.
- forfeit on non-open bounty raises ValueError.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.bounty.board import (
    STATUS_CLAIMED,
    STATUS_FORFEITED,
    STATUS_OPEN,
    balance,
    claim,
    forfeit,
    list_bounties,
    payout,
    post,
    total_pot,
)
from oh_no_my_claudecode.cli import app

_RUNNER = CliRunner()
_TS = "2026-07-06T00:00:00+00:00"
_TS2 = "2026-07-06T01:00:00+00:00"
_TS3 = "2026-07-06T02:00:00+00:00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bounty_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".onmc" / "bounty"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# post creates bounty
# ---------------------------------------------------------------------------


def test_post_creates_bounty(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    b = post("fix the auth bug", 50, "med", bounty_dir=bd, now_iso=_TS, bounty_id="test0001")
    assert b.id == "test0001"
    assert b.task == "fix the auth bug"
    assert b.reward == 50
    assert b.difficulty == "med"
    assert b.status == STATUS_OPEN
    assert b.payout_awarded == 0
    assert b.posted_at == _TS


def test_post_persists_to_board(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    post("task A", 10, "easy", bounty_dir=bd, now_iso=_TS, bounty_id="aaaa0001")
    bounties = list_bounties(bounty_dir=bd)
    assert len(bounties) == 1
    assert bounties[0].id == "aaaa0001"


def test_post_invalid_reward_raises(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    with pytest.raises(ValueError, match="reward must be > 0"):
        post("task", 0, "easy", bounty_dir=bd, now_iso=_TS)


def test_post_invalid_difficulty_raises(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    with pytest.raises(ValueError, match="difficulty must be one of"):
        post("task", 10, "extreme", bounty_dir=bd, now_iso=_TS)


# ---------------------------------------------------------------------------
# list_bounties — filter by status
# ---------------------------------------------------------------------------


def test_list_bounties_returns_only_open_when_filtered(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    post("open task", 10, "easy", bounty_dir=bd, now_iso=_TS, bounty_id="open0001")
    b2 = post("claimed task", 20, "med", bounty_dir=bd, now_iso=_TS, bounty_id="clmd0001")
    claim(b2.id, bounty_dir=bd, now_iso=_TS2)

    open_only = list_bounties(bounty_dir=bd, status=STATUS_OPEN)
    assert len(open_only) == 1
    assert open_only[0].id == "open0001"

    all_b = list_bounties(bounty_dir=bd)
    assert len(all_b) == 2


def test_list_bounties_empty_dir(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    assert list_bounties(bounty_dir=bd) == []


# ---------------------------------------------------------------------------
# payout multiplier
# ---------------------------------------------------------------------------


def test_payout_easy_multiplier() -> None:
    assert payout(100, "easy") == 100


def test_payout_med_multiplier() -> None:
    assert payout(100, "med") == 200


def test_payout_hard_multiplier() -> None:
    assert payout(100, "hard") == 300


def test_payout_invalid_difficulty_raises() -> None:
    with pytest.raises(ValueError, match="difficulty must be one of"):
        payout(100, "impossible")


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_payout_deterministic() -> None:
    """Same inputs always produce the same payout — no randomness."""
    assert payout(75, "med") == payout(75, "med")
    assert payout(50, "hard") == 150


# ---------------------------------------------------------------------------
# claim awards payout
# ---------------------------------------------------------------------------


def test_claim_awards_payout(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    b = post("big task", 100, "hard", bounty_dir=bd, now_iso=_TS, bounty_id="big00001")
    claimed = claim(b.id, bounty_dir=bd, now_iso=_TS2)
    assert claimed.status == STATUS_CLAIMED
    assert claimed.payout_awarded == 300
    assert claimed.resolved_at == _TS2


def test_claim_updates_board(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    b = post("task", 50, "easy", bounty_dir=bd, now_iso=_TS, bounty_id="updt0001")
    claim(b.id, bounty_dir=bd, now_iso=_TS2)
    bounties = list_bounties(bounty_dir=bd)
    assert bounties[0].status == STATUS_CLAIMED


def test_claim_unknown_id_raises(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    with pytest.raises(KeyError, match="not found"):
        claim("nonexistent", bounty_dir=bd, now_iso=_TS)


def test_claim_non_open_raises(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    b = post("task", 50, "med", bounty_dir=bd, now_iso=_TS, bounty_id="nonopen1")
    claim(b.id, bounty_dir=bd, now_iso=_TS2)
    with pytest.raises(ValueError, match="not open"):
        claim(b.id, bounty_dir=bd, now_iso=_TS3)


# ---------------------------------------------------------------------------
# balance sums ledger
# ---------------------------------------------------------------------------


def test_balance_sums_multiple_claims(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    b1 = post("t1", 50, "easy", bounty_dir=bd, now_iso=_TS, bounty_id="b1000001")
    b2 = post("t2", 100, "med", bounty_dir=bd, now_iso=_TS, bounty_id="b2000002")
    claim(b1.id, bounty_dir=bd, now_iso=_TS2)   # +50
    claim(b2.id, bounty_dir=bd, now_iso=_TS3)   # +200
    assert balance(bounty_dir=bd) == 250


def test_balance_empty(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    assert balance(bounty_dir=bd) == 0


# ---------------------------------------------------------------------------
# forfeit closes unpaid
# ---------------------------------------------------------------------------


def test_forfeit_closes_unpaid(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    b = post("obsolete task", 30, "easy", bounty_dir=bd, now_iso=_TS, bounty_id="forf0001")
    forfeited = forfeit(b.id, bounty_dir=bd, now_iso=_TS2, reason="no longer needed")
    assert forfeited.status == STATUS_FORFEITED
    assert forfeited.payout_awarded == 0
    assert forfeited.forfeit_reason == "no longer needed"


def test_forfeit_does_not_add_to_ledger(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    b = post("task", 50, "hard", bounty_dir=bd, now_iso=_TS, bounty_id="nolg0001")
    forfeit(b.id, bounty_dir=bd, now_iso=_TS2)
    assert balance(bounty_dir=bd) == 0


def test_forfeit_unknown_id_raises(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    with pytest.raises(KeyError, match="not found"):
        forfeit("doesnotexist", bounty_dir=bd, now_iso=_TS)


def test_forfeit_non_open_raises(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    b = post("task", 50, "med", bounty_dir=bd, now_iso=_TS, bounty_id="nonop002")
    forfeit(b.id, bounty_dir=bd, now_iso=_TS2)
    with pytest.raises(ValueError, match="not open"):
        forfeit(b.id, bounty_dir=bd, now_iso=_TS3)


# ---------------------------------------------------------------------------
# total_pot
# ---------------------------------------------------------------------------


def test_total_pot_sums_open_payouts(tmp_path: Path) -> None:
    bd = _bounty_dir(tmp_path)
    post("t1", 10, "easy", bounty_dir=bd, now_iso=_TS, bounty_id="pot00001")  # 10
    post("t2", 20, "hard", bounty_dir=bd, now_iso=_TS, bounty_id="pot00002")  # 60
    assert total_pot(bounty_dir=bd) == 70


# ---------------------------------------------------------------------------
# CLI --json envelope shapes
# ---------------------------------------------------------------------------


def test_cli_post_json_envelope(tmp_path: Path) -> None:
    result = _RUNNER.invoke(
        app,
        ["bounty", "post", "my task", "--reward", "50", "--difficulty", "easy", "--json"],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "bounty_posted"
    assert "bounty" in data
    assert data["payout_if_claimed"] == 50


def test_cli_list_json_envelope(tmp_path: Path) -> None:
    result = _RUNNER.invoke(
        app, ["bounty", "list", "--json"], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "bounty_list"
    assert isinstance(data["open"], list)
    assert "total_pot" in data


def test_cli_board_json_envelope(tmp_path: Path) -> None:
    result = _RUNNER.invoke(
        app, ["bounty", "board", "--json"], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "bounty_board"
    assert isinstance(data["bounties"], list)


def test_cli_balance_json_envelope(tmp_path: Path) -> None:
    result = _RUNNER.invoke(
        app, ["bounty", "balance", "--json"], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "bounty_balance"
    assert "total_earned" in data
    assert isinstance(data["total_earned"], int)


def test_cli_claim_unknown_id_exits_1() -> None:
    """CLI exits with code 1 for an unknown bounty id."""
    result = _RUNNER.invoke(
        app,
        ["bounty", "claim", "nonexistent00"],
        catch_exceptions=False,
    )
    # unknown id → exit 1
    assert result.exit_code == 1


def test_cli_claim_json_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Claim via CLI with a known bounty in a tmp dir."""
    import oh_no_my_claudecode.bounty.commands as cmds
    from oh_no_my_claudecode.bounty.board import BOUNTY_SUBDIR

    # Monkey-patch _resolve_bounty_dir to return our tmp dir
    bd = tmp_path / BOUNTY_SUBDIR
    bd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cmds, "_resolve_bounty_dir", lambda: bd)

    from oh_no_my_claudecode.bounty.board import post as core_post

    b = core_post("cli test task", 80, "med", bounty_dir=bd, now_iso=_TS, bounty_id="clitest1")

    result = _RUNNER.invoke(
        app, ["bounty", "claim", b.id, "--json"], catch_exceptions=False
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["kind"] == "bounty_claimed"
    assert data["bounty"]["payout_awarded"] == 160
    assert data["bounty"]["status"] == "claimed"
