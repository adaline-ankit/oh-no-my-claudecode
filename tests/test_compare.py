"""Tests for the ``onmc compare`` side-by-side swarm run comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.compare import (
    build_comparison,
    build_run_metrics,
    render_text,
)
from oh_no_my_claudecode.compare.commands import _most_recent_other_swarm_id
from oh_no_my_claudecode.missioncontrol.dashboard import DashboardModel, build_dashboard


def _make_swarm(
    repo: Path,
    swarm_id: str,
    *,
    units: dict[str, Any],
    receipts: dict[str, Any] | None = None,
) -> Path:
    """Create a fake ``.onmc/swarm/<id>`` manifest (+ optional receipts).

    Mirrors the ``test_postmortem.py`` fixture so both features exercise the
    same on-disk shape.
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
    if receipts:
        rdir = repo / ".agent-memory" / "receipts"
        rdir.mkdir(parents=True, exist_ok=True)
        for name, body in receipts.items():
            (rdir / name).write_text(json.dumps(body), encoding="utf-8")
    return repo / ".onmc" / "swarm"


def _receipt_lookup(mapping: dict[str, dict[str, Any]]) -> Any:
    def _read(unit: Any) -> dict[str, Any] | None:
        return mapping.get(unit.unit_id)

    return _read


def test_missing_swarm_yields_not_exists_metrics() -> None:
    model = DashboardModel(swarm_id="ghost", exists=False)
    metrics = build_run_metrics(model, _receipt_lookup({}))

    assert metrics.exists is False
    assert metrics.total == 0
    assert metrics.models_used == []


def test_build_run_metrics_aggregates_verified_rate_cost_and_iterations(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "task A",
            "status": "done",
            "verified": True,
            "cost_usd": 0.5,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
        "unit-0001": {
            "goal": "task B",
            "status": "failed",
            "verified": False,
            "cost_usd": 0.2,
            "receipt_path": None,
            "error": "boom",
        },
    }
    base = _make_swarm(tmp_path, "swarm-a", units=units)
    model = build_dashboard(base, "swarm-a")

    reader = _receipt_lookup(
        {
            "unit-0000": {
                "verified": True,
                "iterations": 3,
                "wall_seconds": 42.0,
                "model": "claude-opus-4-5",
            }
        }
    )
    metrics = build_run_metrics(model, reader)

    assert metrics.exists is True
    assert metrics.total == 2
    assert metrics.verified_count == 1
    assert metrics.verified_rate == 0.5
    assert metrics.total_wall_seconds == 42.0
    assert metrics.avg_wall_seconds == 42.0
    assert metrics.total_cost_usd == 0.7
    assert metrics.avg_iterations == 3
    assert metrics.models_used == ["claude-opus-4-5"]


def test_build_run_metrics_multiple_models_deduped_and_sorted(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "a",
            "status": "done",
            "verified": True,
            "cost_usd": 0.1,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
        "unit-0001": {
            "goal": "b",
            "status": "done",
            "verified": True,
            "cost_usd": 0.1,
            "receipt_path": ".agent-memory/receipts/run-b.json",
            "error": None,
        },
    }
    base = _make_swarm(tmp_path, "swarm-models", units=units)
    model = build_dashboard(base, "swarm-models")

    reader = _receipt_lookup(
        {
            "unit-0000": {"verified": True, "model": "claude-sonnet-5"},
            "unit-0001": {"verified": True, "model": "claude-opus-4-5"},
        }
    )
    metrics = build_run_metrics(model, reader)

    assert metrics.models_used == ["claude-opus-4-5", "claude-sonnet-5"]


def test_build_run_metrics_malformed_receipt_fields_do_not_crash(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "weird",
            "status": "done",
            "verified": True,
            "cost_usd": 0.0,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
    }
    base = _make_swarm(tmp_path, "swarm-weird", units=units)
    model = build_dashboard(base, "swarm-weird")

    reader = _receipt_lookup(
        {"unit-0000": {"iterations": "not-a-number", "wall_seconds": "n/a", "model": 123}}
    )
    metrics = build_run_metrics(model, reader)

    assert metrics.avg_iterations is None
    assert metrics.avg_wall_seconds is None
    assert metrics.models_used == []


def test_build_run_metrics_empty_swarm_zero_division_safe(tmp_path: Path) -> None:
    base = _make_swarm(tmp_path, "swarm-empty", units={})
    model = build_dashboard(base, "swarm-empty")

    metrics = build_run_metrics(model, _receipt_lookup({}))

    assert metrics.total == 0
    assert metrics.verified_rate == 0.0
    assert metrics.avg_wall_seconds is None
    assert metrics.avg_iterations is None


# ---------------------------------------------------------------------------
# build_comparison + render_text (pure, in-memory RunMetrics)
# ---------------------------------------------------------------------------


def test_winner_higher_is_better_for_verified_rate() -> None:
    a = build_run_metrics(DashboardModel(swarm_id="a", exists=True, units=[]), _receipt_lookup({}))
    # Use to_dict-friendly construction via dataclasses.replace equivalent:
    from dataclasses import replace

    run_a = replace(a, total=10, verified_count=8, verified_rate=0.8)
    run_b = replace(a, swarm_id="b", total=10, verified_count=4, verified_rate=0.4)

    comparison = build_comparison(run_a, run_b)
    row = next(m for m in comparison.metrics if m.field_name == "verified_rate")
    assert row.winner == "a"


def test_winner_lower_is_better_for_cost_and_wall_time() -> None:
    from dataclasses import replace

    empty_model = DashboardModel(swarm_id="x", exists=True, units=[])
    base = build_run_metrics(empty_model, _receipt_lookup({}))
    run_a = replace(base, total=5, total_cost_usd=1.0, total_wall_seconds=100.0)
    run_b = replace(base, swarm_id="y", total=5, total_cost_usd=2.0, total_wall_seconds=50.0)

    comparison = build_comparison(run_a, run_b)
    cost_row = next(m for m in comparison.metrics if m.field_name == "total_cost_usd")
    wall_row = next(m for m in comparison.metrics if m.field_name == "total_wall_seconds")

    assert cost_row.winner == "a"  # lower cost wins
    assert wall_row.winner == "b"  # lower wall time wins


def test_tie_when_values_equal() -> None:
    from dataclasses import replace

    empty_model = DashboardModel(swarm_id="x", exists=True, units=[])
    base = build_run_metrics(empty_model, _receipt_lookup({}))
    run_a = replace(base, total=5, verified_rate=0.5)
    run_b = replace(base, swarm_id="y", total=5, verified_rate=0.5)

    comparison = build_comparison(run_a, run_b)
    row = next(m for m in comparison.metrics if m.field_name == "verified_rate")
    assert row.winner == "tie"


def test_winner_none_when_value_missing() -> None:
    from dataclasses import replace

    empty_model = DashboardModel(swarm_id="x", exists=True, units=[])
    base = build_run_metrics(empty_model, _receipt_lookup({}))
    run_a = replace(base, avg_iterations=None)
    run_b = replace(base, swarm_id="y", avg_iterations=3.0)

    comparison = build_comparison(run_a, run_b)
    row = next(m for m in comparison.metrics if m.field_name == "avg_iterations")
    assert row.winner is None


def test_verdict_declares_overall_winner() -> None:
    from dataclasses import replace

    empty_model = DashboardModel(swarm_id="x", exists=True, units=[])
    base = build_run_metrics(empty_model, _receipt_lookup({}))
    run_a = replace(
        base,
        swarm_id="swarm-good",
        total=10,
        verified_count=9,
        verified_rate=0.9,
        total_cost_usd=1.0,
        total_wall_seconds=50.0,
    )
    run_b = replace(
        base,
        swarm_id="swarm-bad",
        total=10,
        verified_count=2,
        verified_rate=0.2,
        total_cost_usd=5.0,
        total_wall_seconds=500.0,
    )

    comparison = build_comparison(run_a, run_b)
    assert "swarm-good" in comparison.verdict
    assert "did better than" in comparison.verdict


def test_verdict_neutral_when_evenly_matched() -> None:
    from dataclasses import replace

    empty_model = DashboardModel(swarm_id="x", exists=True, units=[])
    base = build_run_metrics(empty_model, _receipt_lookup({}))
    run_a = replace(
        base,
        swarm_id="swarm-a",
        total=10,
        verified_count=9,
        verified_rate=0.9,
        total_cost_usd=5.0,
        total_wall_seconds=500.0,
    )
    run_b = replace(
        base,
        swarm_id="swarm-b",
        total=10,
        verified_count=2,
        verified_rate=0.2,
        total_cost_usd=1.0,
        total_wall_seconds=50.0,
    )

    comparison = build_comparison(run_a, run_b)
    # a wins verified_count + verified_rate; b wins cost + wall time -> tie 2-2.
    assert "evenly matched" in comparison.verdict


def test_verdict_one_sided_missing_swarm() -> None:
    from dataclasses import replace

    missing_model = DashboardModel(swarm_id="ghost", exists=False)
    missing = build_run_metrics(missing_model, _receipt_lookup({}))
    present_model = DashboardModel(swarm_id="real", exists=True, units=[])
    present = build_run_metrics(present_model, _receipt_lookup({}))
    present = replace(present, total=3)

    comparison = build_comparison(missing, present)
    assert "not found" in comparison.verdict
    assert "ghost" in comparison.verdict
    assert "real" in comparison.verdict


def test_verdict_both_missing() -> None:
    a = build_run_metrics(DashboardModel(swarm_id="ghost-a", exists=False), _receipt_lookup({}))
    b = build_run_metrics(DashboardModel(swarm_id="ghost-b", exists=False), _receipt_lookup({}))

    comparison = build_comparison(a, b)
    assert "Neither" in comparison.verdict


def test_verdict_both_empty_no_units() -> None:
    model_a = DashboardModel(swarm_id="empty-a", exists=True, units=[])
    a = build_run_metrics(model_a, _receipt_lookup({}))
    model_b = DashboardModel(swarm_id="empty-b", exists=True, units=[])
    b = build_run_metrics(model_b, _receipt_lookup({}))

    comparison = build_comparison(a, b)
    assert "no units recorded" in comparison.verdict


def test_render_text_missing_run_shows_not_found_line() -> None:
    missing_model = DashboardModel(swarm_id="ghost", exists=False)
    missing = build_run_metrics(missing_model, _receipt_lookup({}))
    present_model = DashboardModel(swarm_id="real", exists=True, units=[])
    present = build_run_metrics(present_model, _receipt_lookup({}))

    comparison = build_comparison(missing, present)
    text = render_text(comparison)

    assert "ghost: not found" in text
    assert "not found" in comparison.verdict


def test_render_text_includes_table_and_verdict(tmp_path: Path) -> None:
    units_a = {
        "unit-0000": {
            "goal": "task A",
            "status": "done",
            "verified": True,
            "cost_usd": 0.5,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
    }
    units_b = {
        "unit-0000": {
            "goal": "task B",
            "status": "failed",
            "verified": False,
            "cost_usd": 0.1,
            "receipt_path": None,
            "error": "boom",
        },
    }
    base_a = _make_swarm(tmp_path / "repo-a", "swarm-x", units=units_a)
    base_b = _make_swarm(tmp_path / "repo-a", "swarm-y", units=units_b)

    model_a = build_dashboard(base_a, "swarm-x")
    model_b = build_dashboard(base_b, "swarm-y")

    reader = _receipt_lookup(
        {
            "unit-0000": {
                "verified": True,
                "iterations": 2,
                "wall_seconds": 10.0,
                "model": "claude-sonnet-5",
            }
        }
    )
    run_a = build_run_metrics(model_a, reader)
    run_b = build_run_metrics(model_b, _receipt_lookup({}))

    comparison = build_comparison(run_a, run_b)
    text = render_text(comparison)

    assert "Compare — swarm-x  vs  swarm-y" in text
    assert "units total" in text
    assert "verified rate" in text
    assert "models A: claude-sonnet-5" in text
    assert comparison.verdict in text


# ---------------------------------------------------------------------------
# commands._most_recent_other_swarm_id (single-id resolution)
# ---------------------------------------------------------------------------


def test_most_recent_other_swarm_id_excludes_given_id(tmp_path: Path) -> None:
    _make_swarm(tmp_path, "swarm-2026-01-01", units={})
    base = _make_swarm(tmp_path, "swarm-2026-02-01", units={})

    resolved = _most_recent_other_swarm_id(base, exclude="swarm-2026-02-01")
    assert resolved == "swarm-2026-01-01"


def test_most_recent_other_swarm_id_none_when_only_self_exists(tmp_path: Path) -> None:
    base = _make_swarm(tmp_path, "swarm-only", units={})

    resolved = _most_recent_other_swarm_id(base, exclude="swarm-only")
    assert resolved is None


def test_most_recent_other_swarm_id_none_when_no_swarms(tmp_path: Path) -> None:
    base = tmp_path / ".onmc" / "swarm"

    resolved = _most_recent_other_swarm_id(base, exclude="anything")
    assert resolved is None


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
    base_a = _make_swarm(tmp_path / "repo-json", "swarm-json-a", units=units)
    model_a = build_dashboard(base_a, "swarm-json-a")
    model_b = build_dashboard(base_a, "swarm-json-a")  # compare against itself for simplicity

    run_a = build_run_metrics(model_a, _receipt_lookup({}))
    run_b = build_run_metrics(model_b, _receipt_lookup({}))

    comparison = build_comparison(run_a, run_b)
    payload = json.dumps(comparison.to_dict())
    parsed = json.loads(payload)

    assert parsed["run_a"]["swarm_id"] == "swarm-json-a"
    assert parsed["run_b"]["swarm_id"] == "swarm-json-a"
    assert "verdict" in parsed
    assert isinstance(parsed["metrics"], list)
