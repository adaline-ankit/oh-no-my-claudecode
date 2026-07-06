"""Tests for the ``onmc swarmreplay`` swarm-run timeline reconstruction (read-only)."""

from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.swarmreplay import (
    Replay,
    build_replay,
    render_step_text,
    render_text,
)


def _make_swarm(
    repo: Path,
    swarm_id: str,
    *,
    units: dict,
    receipts: dict | None = None,
) -> Path:
    """Create a fake ``.onmc/swarm/<id>`` with a manifest (+ optional receipts).

    ``receipts`` maps a filename to a receipt dict written under
    ``.agent-memory/receipts/``; unit ``receipt_path`` values should point at
    those files (repo-relative), mirroring the missioncontrol test fixture.
    """
    swarm_dir = repo / ".onmc" / "swarm" / swarm_id
    swarm_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "swarm_id": swarm_id,
        "mode": "inline",
        "started_at": "2026-07-04T08:00:00+00:00",
        "agent": "claude-code-subagent",
        "concurrency": 2,
        "units": units,
    }
    (swarm_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if receipts:
        rdir = repo / ".agent-memory" / "receipts"
        rdir.mkdir(parents=True, exist_ok=True)
        for name, body in receipts.items():
            (rdir / name).write_text(json.dumps(body), encoding="utf-8")
    return repo / ".onmc" / "swarm"


def test_build_replay_orders_units_by_started_at(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "build feature A",
            "receipt_path": ".agent-memory/receipts/run-a.json",
        },
        "unit-0001": {
            "goal": "build feature B",
            "receipt_path": ".agent-memory/receipts/run-b.json",
        },
    }
    receipts = {
        # unit-0001 started BEFORE unit-0000 despite sorting after by id.
        "run-a.json": {
            "started_at": "2026-07-04T09:00:00+00:00",
            "ended_at": "2026-07-04T09:05:00+00:00",
            "verified": True,
            "wall_seconds": 300.0,
            "iteration_hashes": ["hashA1", "hashA2"],
        },
        "run-b.json": {
            "started_at": "2026-07-04T08:00:00+00:00",
            "ended_at": "2026-07-04T08:02:00+00:00",
            "verified": False,
            "wall_seconds": 120.0,
            "iteration_hashes": ["hashB1"],
        },
    }
    base = _make_swarm(tmp_path, "sw1", units=units, receipts=receipts)

    replay = build_replay(base, "sw1")

    assert replay.exists is True
    assert replay.total == 3
    # unit-0001 (started earlier) comes first, in full, before unit-0000.
    assert [s.unit_id for s in replay.steps] == ["unit-0001", "unit-0000", "unit-0000"]
    # Global index is contiguous and 0-based.
    assert [s.index for s in replay.steps] == [0, 1, 2]


def test_step_ordering_within_unit_matches_iteration_hashes(tmp_path: Path) -> None:
    units = {
        "unit-0000": {"goal": "g", "receipt_path": ".agent-memory/receipts/run-a.json"},
    }
    receipts = {
        "run-a.json": {
            "started_at": "2026-07-04T08:00:00+00:00",
            "verified": True,
            "wall_seconds": 42.0,
            "iteration_hashes": ["h1", "h2", "h3"],
        },
    }
    base = _make_swarm(tmp_path, "sw2", units=units, receipts=receipts)

    replay = build_replay(base, "sw2")

    assert [s.iteration for s in replay.steps] == [1, 2, 3]
    assert [s.iteration_hash for s in replay.steps] == ["h1", "h2", "h3"]
    # verified + wall_seconds are the receipt-level (final) values, repeated per step.
    assert all(s.verified is True for s in replay.steps)
    assert all(s.wall_seconds == 42.0 for s in replay.steps)


def test_step_count_matches_total_iterations_across_units(tmp_path: Path) -> None:
    units = {
        "unit-0000": {"goal": "a", "receipt_path": ".agent-memory/receipts/run-a.json"},
        "unit-0001": {"goal": "b", "receipt_path": ".agent-memory/receipts/run-b.json"},
    }
    receipts = {
        "run-a.json": {
            "started_at": "2026-07-04T08:00:00+00:00",
            "iteration_hashes": ["a1", "a2"],
        },
        "run-b.json": {
            "started_at": "2026-07-04T08:01:00+00:00",
            "iteration_hashes": ["b1", "b2", "b3"],
        },
    }
    base = _make_swarm(tmp_path, "sw3", units=units, receipts=receipts)

    replay = build_replay(base, "sw3")

    assert replay.total == 5


def test_step_at_lookup_returns_correct_step(tmp_path: Path) -> None:
    units = {
        "unit-0000": {"goal": "first unit", "receipt_path": ".agent-memory/receipts/run-a.json"},
    }
    receipts = {
        "run-a.json": {
            "started_at": "2026-07-04T08:00:00+00:00",
            "iteration_hashes": ["h1", "h2"],
        },
    }
    base = _make_swarm(tmp_path, "sw4", units=units, receipts=receipts)

    replay = build_replay(base, "sw4")

    step1 = replay.step_at(1)
    assert step1 is not None
    assert step1.iteration == 2
    assert step1.iteration_hash == "h2"
    assert step1.unit_goal == "first unit"

    assert replay.step_at(99) is None
    assert replay.step_at(-1) is None


def test_missing_manifest_is_graceful(tmp_path: Path) -> None:
    base = tmp_path / ".onmc" / "swarm"
    base.mkdir(parents=True, exist_ok=True)

    replay = build_replay(base, "does-not-exist")

    assert replay.exists is False
    assert replay.steps == []
    text = render_text(replay)
    assert "No swarm found" in text
    assert "does-not-exist" in text


def test_unit_with_no_receipt_yields_no_steps_but_a_note(tmp_path: Path) -> None:
    units = {
        "unit-0000": {"goal": "no receipt yet", "receipt_path": None},
    }
    base = _make_swarm(tmp_path, "sw5", units=units)

    replay = build_replay(base, "sw5")

    assert replay.exists is True
    assert replay.total == 0
    assert any("no iterations recorded" in note for note in replay.notes)
    text = render_text(replay)
    assert "no iterations recorded" in text


def test_unit_with_empty_iteration_hashes_yields_no_steps(tmp_path: Path) -> None:
    units = {
        "unit-0000": {"goal": "g", "receipt_path": ".agent-memory/receipts/run-empty.json"},
    }
    receipts = {
        "run-empty.json": {"started_at": "2026-07-04T08:00:00+00:00", "iteration_hashes": []},
    }
    base = _make_swarm(tmp_path, "sw6", units=units, receipts=receipts)

    replay = build_replay(base, "sw6")

    assert replay.total == 0
    assert any("no iteration_hashes" in note for note in replay.notes)


def test_render_text_contains_expected_fields(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "implement the widget",
            "receipt_path": ".agent-memory/receipts/run-a.json",
        },
    }
    receipts = {
        "run-a.json": {
            "started_at": "2026-07-04T08:00:00+00:00",
            "verified": True,
            "wall_seconds": 12.5,
            "iteration_hashes": ["abcdef012345"],
        },
    }
    base = _make_swarm(tmp_path, "sw7", units=units, receipts=receipts)

    replay = build_replay(base, "sw7")
    text = render_text(replay)

    assert "sw7" in text
    assert "unit-0000" in text
    assert "implement the widget" in text
    assert "abcdef012345"[:12] in text
    assert "1 step(s)" in text


def test_render_step_text_reports_out_of_range(tmp_path: Path) -> None:
    units = {
        "unit-0000": {"goal": "g", "receipt_path": ".agent-memory/receipts/run-a.json"},
    }
    receipts = {
        "run-a.json": {"started_at": "2026-07-04T08:00:00+00:00", "iteration_hashes": ["h1"]},
    }
    base = _make_swarm(tmp_path, "sw8", units=units, receipts=receipts)

    replay = build_replay(base, "sw8")
    out_of_range = render_step_text(replay, 5)

    assert "not found" in out_of_range
    assert "sw8" in out_of_range

    in_range = render_step_text(replay, 0)
    assert "iteration_hash: h1" in in_range


def test_to_dict_is_json_serialisable_and_stable_shape(tmp_path: Path) -> None:
    units = {
        "unit-0000": {"goal": "g", "receipt_path": ".agent-memory/receipts/run-a.json"},
    }
    receipts = {
        "run-a.json": {
            "started_at": "2026-07-04T08:00:00+00:00",
            "ended_at": "2026-07-04T08:01:00+00:00",
            "verified": True,
            "wall_seconds": 5.0,
            "iteration_hashes": ["h1"],
        },
    }
    base = _make_swarm(tmp_path, "sw9", units=units, receipts=receipts)

    replay = build_replay(base, "sw9")
    payload = replay.to_dict()
    round_tripped = json.loads(json.dumps(payload))

    assert round_tripped["swarm_id"] == "sw9"
    assert round_tripped["exists"] is True
    assert round_tripped["total"] == 1
    step = round_tripped["steps"][0]
    assert set(step.keys()) == {
        "index",
        "unit_id",
        "unit_goal",
        "iteration",
        "iteration_hash",
        "verified",
        "wall_seconds",
        "ended_at",
    }
    assert step["ended_at"] == "2026-07-04T08:01:00+00:00"


def test_replay_dataclass_default_construction() -> None:
    # A bare Replay() with no steps behaves sanely (defaults exercised directly,
    # not just via build_replay) — guards against future dataclass-field drift.
    replay = Replay(swarm_id="empty", exists=True)
    assert replay.total == 0
    assert replay.step_at(0) is None
    assert replay.to_dict()["steps"] == []
