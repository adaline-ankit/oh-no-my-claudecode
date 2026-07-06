"""Tests for the ``onmc watch`` live swarm monitor (read-only, pure frame)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.watch import build_frame, render_frame


def _make_swarm(
    repo: Path,
    swarm_id: str,
    *,
    units: dict,
) -> Path:
    """Create a fake ``.onmc/swarm/<id>`` with a manifest.

    Mirrors ``tests/test_missioncontrol.py``'s ``_make_swarm`` helper so the
    two features stay in lock-step.
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
    return repo / ".onmc" / "swarm"


def test_build_frame_counts_active_swarm(tmp_path: Path) -> None:
    base = _make_swarm(
        tmp_path,
        "sw-1",
        units={
            "unit-0000": {"goal": "build feature A", "status": "running"},
            "unit-0001": {"goal": "build feature B", "status": "queued"},
            "unit-0002": {"goal": "build feature C", "status": "done", "verified": True},
        },
    )
    frame = build_frame(base)
    assert len(frame.swarms) == 1
    s = frame.swarms[0]
    assert s.swarm_id == "sw-1"
    assert s.total == 3
    assert s.running == 1
    assert s.queued == 1
    assert s.done == 1
    assert s.verified_count == 1
    assert s.is_active is True
    assert frame.active_count == 1


def test_build_frame_excludes_fully_terminal_swarm_by_default(tmp_path: Path) -> None:
    base = _make_swarm(
        tmp_path,
        "sw-done",
        units={
            "unit-0000": {"goal": "finished work", "status": "done", "verified": True},
            "unit-0001": {"goal": "also finished", "status": "failed"},
        },
    )
    frame = build_frame(base)
    assert frame.swarms == []
    assert frame.active_count == 0


def test_build_frame_all_includes_terminal_swarms(tmp_path: Path) -> None:
    base = _make_swarm(
        tmp_path,
        "sw-done",
        units={"unit-0000": {"goal": "finished work", "status": "done"}},
    )
    frame = build_frame(base, active_only=False)
    assert len(frame.swarms) == 1
    assert frame.swarms[0].is_active is False


def test_build_frame_empty_state_dir_is_graceful(tmp_path: Path) -> None:
    base = tmp_path / ".onmc" / "swarm"
    frame = build_frame(base)
    assert frame.swarms == []
    assert frame.active_count == 0


def test_build_frame_multiple_swarms_sorted(tmp_path: Path) -> None:
    _make_swarm(tmp_path, "sw-b", units={"unit-0000": {"goal": "b", "status": "running"}})
    _make_swarm(tmp_path, "sw-a", units={"unit-0000": {"goal": "a", "status": "queued"}})
    base = tmp_path / ".onmc" / "swarm"
    frame = build_frame(base)
    ids = [s.swarm_id for s in frame.swarms]
    assert ids == ["sw-a", "sw-b"]


def test_recent_goals_prefers_in_flight_units(tmp_path: Path) -> None:
    base = _make_swarm(
        tmp_path,
        "sw-mixed",
        units={
            "unit-0000": {"goal": "completed goal", "status": "done"},
            "unit-0001": {"goal": "active goal one", "status": "running"},
            "unit-0002": {"goal": "active goal two", "status": "queued"},
        },
    )
    frame = build_frame(base)
    s = frame.swarms[0]
    assert "completed goal" not in s.recent_goals
    assert "active goal one" in s.recent_goals
    assert "active goal two" in s.recent_goals


def test_recent_goals_falls_back_to_any_unit_when_all_terminal(tmp_path: Path) -> None:
    base = _make_swarm(
        tmp_path,
        "sw-terminal",
        units={"unit-0000": {"goal": "only goal here", "status": "done"}},
    )
    frame = build_frame(base, active_only=False)
    s = frame.swarms[0]
    assert "only goal here" in s.recent_goals


def test_render_frame_empty_state() -> None:
    frame = build_frame(Path("/does/not/exist"))
    text = render_frame(frame)
    assert "No active swarms" in text


def test_render_frame_contains_expected_strings(tmp_path: Path) -> None:
    base = _make_swarm(
        tmp_path,
        "sw-render",
        units={
            "unit-0000": {"goal": "implement the widget", "status": "running"},
        },
    )
    frame = build_frame(base)
    text = render_frame(frame)
    assert "sw-render" in text
    assert "running=1" in text
    assert "implement the widget" in text


def test_frame_to_dict_json_serialisable(tmp_path: Path) -> None:
    base = _make_swarm(
        tmp_path,
        "sw-json",
        units={"unit-0000": {"goal": "g", "status": "running", "verified": None}},
    )
    frame = build_frame(base)
    payload = frame.to_dict()
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["active_count"] == 1
    assert round_tripped["swarms"][0]["swarm_id"] == "sw-json"


def test_cli_watch_once_no_swarms(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["watch", "--once"])
    assert result.exit_code == 0
    assert "No active swarms" in result.stdout


def test_cli_watch_json_implies_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _make_swarm(
        tmp_path,
        "sw-cli",
        units={"unit-0000": {"goal": "cli goal", "status": "running"}},
    )
    runner = CliRunner()
    result = runner.invoke(app, ["watch", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["active_count"] == 1
    assert payload["swarms"][0]["swarm_id"] == "sw-cli"


def test_cli_watch_rejects_non_positive_interval(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["watch", "--interval", "0"])
    assert result.exit_code == 1
