"""Tests for the mission-bridge trust-card builder + renderers.

Coverage (deterministic, offline)
---------------------------------
1.  build_card maps a seeded manifest+receipt to UnitLines with correct
    verified/held and honest per-unit cost.
2.  A unit with no receipt -> held, not shipped (even if manifest verified).
3.  A manifest-unverified unit -> held.
4.  total_cost_usd is summed from receipts.
5.  total_cost_usd is None ("n/a") when receipts carry no cost.
6.  An empty / missing swarm -> empty card, no crash.
7.  render_slack_blocks includes approve-all + per-unit approve action_ids.
8.  render_telegram callback_data mirrors the Slack action_ids.
9.  render_plain lists every unit and honest totals.
10. build_card is deterministic (same inputs -> equal card).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.missionbridge.card import (
    ACTION_ABORT,
    ACTION_APPROVE_ALL,
    build_card,
    render_plain,
    render_slack_blocks,
    render_telegram,
)

# ---------------------------------------------------------------------------
# Seeding helpers — build a real .onmc/swarm/<id>/manifest.json + receipts so
# the dashboard reader path is exercised end-to-end.
# ---------------------------------------------------------------------------


def _write_receipt(
    repo: Path,
    name: str,
    *,
    verified: bool = True,
    diff_sha: str = "deadbeef",
    receipt_hash: str = "cafef00d1234",
    cost_usd: float | None = 0.25,
    pr_url: str | None = None,
) -> Path:
    receipts = repo / ".agent-memory" / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    path = receipts / name
    payload: dict[str, Any] = {
        "verified": verified,
        "diff_sha": diff_sha,
        "receipt_hash": receipt_hash,
        "tokens_used": 4200,
    }
    if cost_usd is not None:
        payload["cost_usd"] = cost_usd
    if pr_url is not None:
        payload["pr_url"] = pr_url
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _seed_swarm(repo: Path, swarm_id: str, units: dict[str, dict[str, Any]]) -> None:
    swarm_dir = repo / ".onmc" / "swarm" / swarm_id
    swarm_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "swarm_id": swarm_id,
        "mode": "inline",
        "agent": "claude",
        "concurrency": 2,
        "units": units,
    }
    (swarm_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _seed_default(repo: Path, swarm_id: str = "sw-1") -> None:
    """Two verified units (with receipts) + one held (no receipt)."""
    _write_receipt(repo, "run-a.json", diff_sha="aaa111", receipt_hash="hashA0001", cost_usd=0.25)
    _write_receipt(
        repo, "run-b.json", diff_sha="bbb222", receipt_hash="hashB0002", cost_usd=0.75,
        pr_url="https://example.test/pr/2",
    )
    _seed_swarm(
        repo,
        swarm_id,
        {
            "unit-0001": {
                "goal": "add feature A",
                "status": "done",
                "verified": True,
                "receipt_path": ".agent-memory/receipts/run-a.json",
                "cost_usd": 0.25,
            },
            "unit-0002": {
                "goal": "add feature B",
                "status": "done",
                "verified": True,
                "receipt_path": ".agent-memory/receipts/run-b.json",
                "cost_usd": 0.75,
            },
            "unit-0003": {
                "goal": "broken feature C",
                "status": "failed",
                "verified": False,
                "error": "verifier failed",
            },
        },
    )


# ---------------------------------------------------------------------------
# build_card
# ---------------------------------------------------------------------------


def test_build_card_maps_verified_units(tmp_path: Path) -> None:
    _seed_default(tmp_path)
    card = build_card(tmp_path, "sw-1", goal="ship the thing")

    assert card.mission_id == "sw-1"
    assert card.goal == "ship the thing"
    assert card.unit_count == 3
    assert card.verified_count == 2
    assert card.held_count == 1

    by_id = {u.unit_id: u for u in card.units}
    a = by_id["unit-0001"]
    assert a.verified is True
    assert a.held is False
    assert a.cost_usd == 0.25
    assert a.diff_sha == "aaa111"
    assert a.receipt_hash == "hashA0001"

    b = by_id["unit-0002"]
    assert b.verified is True
    assert b.pr_url == "https://example.test/pr/2"


def test_unit_without_receipt_is_held(tmp_path: Path) -> None:
    _seed_default(tmp_path)
    card = build_card(tmp_path, "sw-1")
    held = next(u for u in card.units if u.unit_id == "unit-0003")
    assert held.held is True
    assert held.verified is False
    assert "held, not shipped" in held.detail
    assert held.receipt_hash is None
    assert held.cost_usd is None


def test_manifest_verified_but_missing_receipt_file_is_held(tmp_path: Path) -> None:
    # Manifest claims verified + points at a receipt that does NOT exist on disk.
    _seed_swarm(
        tmp_path,
        "sw-x",
        {
            "unit-0001": {
                "goal": "phantom",
                "status": "done",
                "verified": True,
                "receipt_path": ".agent-memory/receipts/does-not-exist.json",
            }
        },
    )
    card = build_card(tmp_path, "sw-x")
    unit = card.units[0]
    assert unit.held is True
    assert unit.verified is False


def test_total_cost_summed_from_receipts(tmp_path: Path) -> None:
    _seed_default(tmp_path)
    card = build_card(tmp_path, "sw-1")
    assert card.total_cost_usd == 1.0  # 0.25 + 0.75


def test_total_cost_none_when_receipts_have_no_cost(tmp_path: Path) -> None:
    _write_receipt(tmp_path, "run-a.json", cost_usd=None)
    _seed_swarm(
        tmp_path,
        "sw-nc",
        {
            "unit-0001": {
                "goal": "no cost",
                "status": "done",
                "verified": True,
                "receipt_path": ".agent-memory/receipts/run-a.json",
            }
        },
    )
    card = build_card(tmp_path, "sw-nc")
    assert card.total_cost_usd is None
    assert card.units[0].cost_usd is None


def test_missing_swarm_yields_empty_card(tmp_path: Path) -> None:
    card = build_card(tmp_path, "nope")
    assert card.mission_id == "nope"
    assert card.units == []
    assert card.unit_count == 0
    assert card.total_cost_usd is None


def test_build_card_is_deterministic(tmp_path: Path) -> None:
    _seed_default(tmp_path)
    first = build_card(tmp_path, "sw-1", goal="g")
    second = build_card(tmp_path, "sw-1", goal="g")
    assert first == second


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def test_slack_blocks_include_action_ids(tmp_path: Path) -> None:
    _seed_default(tmp_path)
    card = build_card(tmp_path, "sw-1")
    blocks = render_slack_blocks(card)

    action_ids = {
        el["action_id"]
        for b in blocks
        if b["type"] == "actions"
        for el in b["elements"]
    }
    assert ACTION_APPROVE_ALL in action_ids
    assert ACTION_ABORT in action_ids
    assert "mission:approve:unit-0001" in action_ids
    assert "mission:show_diff:unit-0002" in action_ids

    # A header block is always present.
    assert blocks[0]["type"] == "header"


def test_telegram_callback_data_mirrors_slack(tmp_path: Path) -> None:
    _seed_default(tmp_path)
    card = build_card(tmp_path, "sw-1")

    blocks = render_slack_blocks(card)
    slack_ids = {
        el["action_id"]
        for b in blocks
        if b["type"] == "actions"
        for el in b["elements"]
    }

    text, keyboard = render_telegram(card)
    tg_ids = {btn["callback_data"] for row in keyboard for btn in row}

    assert slack_ids == tg_ids
    assert "sw-1" in text


def test_plain_render_lists_units(tmp_path: Path) -> None:
    _seed_default(tmp_path)
    card = build_card(tmp_path, "sw-1")
    out = render_plain(card)
    assert "unit-0001" in out
    assert "unit-0002" in out
    assert "unit-0003" in out
    assert "VERIFIED" in out
    assert "HELD" in out
    # Verified units show a real dollar cost; the held one honestly shows n/a.
    assert "$0.25" in out
    assert "total cost $1.00" in out


def test_plain_render_empty_card(tmp_path: Path) -> None:
    card = build_card(tmp_path, "gone")
    out = render_plain(card)
    assert "no units" in out
    assert "n/a" in out  # total cost unknown
