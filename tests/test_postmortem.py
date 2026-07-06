"""Tests for the ``onmc postmortem`` LLM-free swarm narrative recap."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.missioncontrol.dashboard import build_dashboard
from oh_no_my_claudecode.postmortem import (
    HIGH_ITERATION_THRESHOLD,
    build_postmortem,
    render_text,
)


def _make_swarm(
    repo: Path,
    swarm_id: str,
    *,
    units: dict[str, Any],
    aborted: bool = False,
    receipts: dict[str, Any] | None = None,
) -> Path:
    """Create a fake ``.onmc/swarm/<id>`` manifest (+ optional receipts).

    Mirrors the ``test_missioncontrol.py`` fixture so both features exercise
    the same on-disk shape. ``receipts`` maps a filename to a receipt dict
    written under ``.agent-memory/receipts/``; unit ``receipt_path`` values
    should point at those files (repo-relative).
    """
    swarm_dir = repo / ".onmc" / "swarm" / swarm_id
    swarm_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "swarm_id": swarm_id,
        "mode": "inline",
        "started_at": "2026-07-04T08:00:00+00:00",
        "agent": "claude-code-subagent",
        "concurrency": 2,
        "swarm_max_cost_usd": None,
        "units": units,
    }
    (swarm_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if aborted:
        (swarm_dir / "ABORT").write_text("abort", encoding="utf-8")
    if receipts:
        rdir = repo / ".agent-memory" / "receipts"
        rdir.mkdir(parents=True, exist_ok=True)
        for name, body in receipts.items():
            (rdir / name).write_text(json.dumps(body), encoding="utf-8")
    return repo / ".onmc" / "swarm"


def _receipt_lookup(mapping: dict[str, dict[str, Any]]) -> Any:
    """Build an in-memory receipt reader keyed by unit_id for pure-core tests."""

    def _read(unit: Any) -> dict[str, Any] | None:
        return mapping.get(unit.unit_id)

    return _read


# ---------------------------------------------------------------------------
# Pure core: build_postmortem + render_text against an in-memory model
# ---------------------------------------------------------------------------


def test_missing_swarm_returns_not_exists_and_graceful_text() -> None:
    from oh_no_my_claudecode.missioncontrol.dashboard import DashboardModel

    model = DashboardModel(swarm_id="ghost", exists=False)
    pm = build_postmortem(model, _receipt_lookup({}))

    assert pm.exists is False
    assert pm.total == 0
    text = render_text(pm)
    assert "No swarm found with id ghost" in text
    assert "missioncontrol --all" in text


def test_build_postmortem_overview_counts(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "build feature A",
            "status": "done",
            "verified": True,
            "cost_usd": 0.5,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
        "unit-0001": {
            "goal": "build feature B",
            "status": "failed",
            "verified": False,
            "cost_usd": 0.2,
            "receipt_path": None,
            "error": "subagent did not verify",
        },
    }
    base = _make_swarm(
        tmp_path,
        "swarm-1",
        units=units,
        receipts={
            "run-a.json": {
                "verified": True,
                "iterations": 3,
                "wall_seconds": 42.0,
                "stop_reason": "converged",
                "git_tree_sha": "deadbeef",
            }
        },
    )
    model = build_dashboard(base, "swarm-1")

    def _real_reader(unit: Any) -> dict[str, Any] | None:
        if unit.unit_id == "unit-0000":
            return {
                "verified": True,
                "iterations": 3,
                "wall_seconds": 42.0,
                "stop_reason": "converged",
                "git_tree_sha": "deadbeef",
            }
        return None

    pm = build_postmortem(model, _real_reader)

    assert pm.exists is True
    assert pm.total == 2
    assert pm.verified_count == 1
    assert pm.failed_count == 1
    assert pm.total_wall_seconds == 42.0


def test_unit_narrative_line_for_verified_unit_with_receipt(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "add retry logic",
            "status": "done",
            "verified": True,
            "cost_usd": 0.1,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
    }
    base = _make_swarm(tmp_path, "swarm-2", units=units)
    model = build_dashboard(base, "swarm-2")

    reader = _receipt_lookup(
        {
            "unit-0000": {
                "verified": True,
                "iterations": 4,
                "wall_seconds": 65.0,
                "stop_reason": "converged",
                "git_tree_sha": "abc123",
            }
        }
    )
    pm = build_postmortem(model, reader)
    unit = pm.units[0]

    assert unit.verified is True
    assert unit.iterations == 4
    assert unit.wall_seconds == 65.0
    assert unit.stop_reason == "converged"
    assert "verified in 4 iteration(s) over 1m05s" in unit.line
    assert "stopped: converged" in unit.line


def test_unit_narrative_no_receipt_recorded(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "flaky task",
            "status": "failed",
            "verified": False,
            "cost_usd": 0.0,
            "receipt_path": None,
            "error": "subagent crashed",
        },
    }
    base = _make_swarm(tmp_path, "swarm-3", units=units)
    model = build_dashboard(base, "swarm-3")

    pm = build_postmortem(model, _receipt_lookup({}))
    unit = pm.units[0]

    assert unit.has_receipt is False
    assert unit.iterations is None
    assert unit.wall_seconds is None
    assert "no receipt recorded" in unit.line
    assert "subagent crashed" in unit.line


def test_needs_attention_flags_failed_units(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "task A",
            "status": "failed",
            "verified": False,
            "cost_usd": 0.0,
            "receipt_path": None,
            "error": "boom",
        },
        "unit-0001": {
            "goal": "task B",
            "status": "done",
            "verified": True,
            "cost_usd": 0.1,
            "receipt_path": ".agent-memory/receipts/run-b.json",
            "error": None,
        },
    }
    base = _make_swarm(tmp_path, "swarm-4", units=units)
    model = build_dashboard(base, "swarm-4")

    def _reader(unit: Any) -> dict[str, Any] | None:
        if unit.unit_id == "unit-0001":
            return {"verified": True, "iterations": 2, "wall_seconds": 10.0}
        return None

    pm = build_postmortem(model, _reader)

    assert any("did not verify" in note for note in pm.needs_attention)
    assert any("unit-0000" in note for note in pm.needs_attention)


def test_needs_attention_flags_high_iteration_units(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "hard task",
            "status": "done",
            "verified": True,
            "cost_usd": 1.0,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
    }
    base = _make_swarm(tmp_path, "swarm-5", units=units)
    model = build_dashboard(base, "swarm-5")

    reader = _receipt_lookup(
        {
            "unit-0000": {
                "verified": True,
                "iterations": HIGH_ITERATION_THRESHOLD,
                "wall_seconds": 300.0,
            }
        }
    )
    pm = build_postmortem(model, reader)

    assert any("needed >=" in note for note in pm.needs_attention)
    assert any("unit-0000" in note for note in pm.needs_attention)
    # A high-iteration-but-verified unit should NOT also appear in went_well's
    # "under threshold" bucket.
    assert not any("under" in note and "iterations" in note for note in pm.went_well)


def test_needs_attention_flags_missing_receipts(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "no receipt task",
            "status": "done",
            "verified": True,
            "cost_usd": 0.0,
            "receipt_path": None,
            "error": None,
        },
    }
    base = _make_swarm(tmp_path, "swarm-6", units=units)
    model = build_dashboard(base, "swarm-6")

    pm = build_postmortem(model, _receipt_lookup({}))

    assert any("no receipt recorded" in note for note in pm.needs_attention)


def test_went_well_reports_low_iteration_verified_units(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "easy task",
            "status": "done",
            "verified": True,
            "cost_usd": 0.05,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
    }
    base = _make_swarm(tmp_path, "swarm-7", units=units)
    model = build_dashboard(base, "swarm-7")

    reader = _receipt_lookup(
        {"unit-0000": {"verified": True, "iterations": 1, "wall_seconds": 5.0}}
    )
    pm = build_postmortem(model, reader)

    assert any("1/1 unit(s) verified" in note for note in pm.went_well)
    assert any("average wall time" in note for note in pm.went_well)


def test_empty_swarm_has_no_units_message(tmp_path: Path) -> None:
    base = _make_swarm(tmp_path, "swarm-empty", units={})
    model = build_dashboard(base, "swarm-empty")

    pm = build_postmortem(model, _receipt_lookup({}))

    assert pm.total == 0
    text = render_text(pm)
    assert "No units recorded" in text


def test_render_text_includes_overview_and_per_unit_and_summary(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "task A",
            "status": "done",
            "verified": True,
            "cost_usd": 0.1,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
        "unit-0001": {
            "goal": "task B",
            "status": "failed",
            "verified": False,
            "cost_usd": 0.0,
            "receipt_path": None,
            "error": "crashed",
        },
    }
    base = _make_swarm(tmp_path, "swarm-8", units=units)
    model = build_dashboard(base, "swarm-8")

    def _reader(unit: Any) -> dict[str, Any] | None:
        if unit.unit_id == "unit-0000":
            return {"verified": True, "iterations": 2, "wall_seconds": 30.0}
        return None

    pm = build_postmortem(model, _reader)
    text = render_text(pm)

    assert "Postmortem — swarm swarm-8" in text
    assert "2 unit(s)" in text
    assert "1 verified" in text
    assert "1 failed" in text
    assert "unit-0000: task A" in text
    assert "unit-0001: task B" in text
    assert "What went well:" in text
    assert "What needs attention:" in text


def test_to_dict_round_trips_json_serialisable(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "task A",
            "status": "done",
            "verified": True,
            "cost_usd": 0.1,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
    }
    base = _make_swarm(tmp_path, "swarm-9", units=units)
    model = build_dashboard(base, "swarm-9")
    reader = _receipt_lookup(
        {"unit-0000": {"verified": True, "iterations": 1, "wall_seconds": 1.0}}
    )
    pm = build_postmortem(model, reader)

    payload = json.dumps(pm.to_dict())
    parsed = json.loads(payload)
    assert parsed["swarm_id"] == "swarm-9"
    assert parsed["total"] == 1
    assert parsed["units"][0]["unit_id"] == "unit-0000"


def test_malformed_receipt_fields_do_not_crash(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "weird receipt",
            "status": "done",
            "verified": True,
            "cost_usd": 0.1,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
    }
    base = _make_swarm(tmp_path, "swarm-10", units=units)
    model = build_dashboard(base, "swarm-10")

    # iterations/wall_seconds are the wrong type -- should degrade to None, not crash.
    reader = _receipt_lookup(
        {"unit-0000": {"verified": True, "iterations": "not-a-number", "wall_seconds": "n/a"}}
    )
    pm = build_postmortem(model, reader)
    unit = pm.units[0]

    assert unit.iterations is None
    assert unit.wall_seconds is None
    assert "unknown number of iterations" in unit.line
    assert "unknown time" in unit.line
