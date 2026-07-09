"""Tests for ``onmc pulse`` — the one-shot "is it stuck?" liveness heartbeat.

The verdict builder is a pure function of on-disk swarm state plus an injected
``now_ms``, so every timing scenario is deterministic (no live clock).
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.pulse import (
    VERDICT_EMPTY,
    VERDICT_IDLE,
    VERDICT_STUCK,
    VERDICT_WORKING,
    build_pulse,
    render_pulse_text,
    to_event,
)

# A fixed wall clock and a fixed swarm start so elapsed is fully deterministic.
_START_ISO = "2026-07-04T08:00:00+00:00"
_START_MS = 1_783_152_000_000  # == _START_ISO in epoch ms
_STUCK_AFTER_MS = 300_000  # 5 minutes


def _now_iso() -> str:
    """A fresh ISO timestamp for CLI tests that run against the real wall clock."""
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _make_swarm(repo: Path, swarm_id: str, *, units: dict, started_at: str = _START_ISO) -> None:
    """Seed a fake ``.onmc/swarm/<id>/manifest.json`` (mirrors watch/missioncontrol tests)."""
    swarm_dir = repo / ".onmc" / "swarm" / swarm_id
    swarm_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "swarm_id": swarm_id,
        "mode": "inline",
        "started_at": started_at,
        "agent": "claude-code-subagent",
        "concurrency": 2,
        "units": units,
    }
    (swarm_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_start_iso_matches_start_ms() -> None:
    """Guard: the ISO/epoch-ms constants used across the tests agree."""
    from datetime import datetime

    assert int(datetime.fromisoformat(_START_ISO).timestamp() * 1000) == _START_MS


def test_running_unit_fresh_timestamp_is_working(tmp_path: Path) -> None:
    _make_swarm(
        tmp_path,
        "sw-1",
        units={
            "unit-0000": {"goal": "build A", "status": "running"},
            "unit-0001": {"goal": "build B", "status": "done", "verified": True},
        },
    )
    # now == start + 10s → well under the 5m stuck threshold.
    pulse = build_pulse(
        tmp_path, now_ms=_START_MS + 10_000, stuck_after_ms=_STUCK_AFTER_MS
    )
    assert pulse.overall == VERDICT_WORKING
    assert pulse.swarm_count == 1
    assert pulse.working_count == 1
    s = pulse.swarms[0]
    assert s.verdict == VERDICT_WORKING
    assert s.running == 1
    assert s.stuck_unit_id is None


def test_running_unit_old_timestamp_is_stuck_and_names_unit(tmp_path: Path) -> None:
    _make_swarm(
        tmp_path,
        "sw-stuck",
        units={"unit-0000": {"goal": "wedged goal", "status": "running"}},
    )
    # now == start + 6m → exceeds the 5m stuck threshold with no receipt.
    pulse = build_pulse(
        tmp_path, now_ms=_START_MS + 360_000, stuck_after_ms=_STUCK_AFTER_MS
    )
    assert pulse.overall == VERDICT_STUCK
    assert pulse.stuck_count == 1
    s = pulse.swarms[0]
    assert s.verdict == VERDICT_STUCK
    assert s.stuck_unit_id == "unit-0000"
    assert s.elapsed_ms == 360_000


def test_all_done_manifest_is_idle(tmp_path: Path) -> None:
    _make_swarm(
        tmp_path,
        "sw-done",
        units={
            "unit-0000": {"goal": "A", "status": "done", "verified": True},
            "unit-0001": {"goal": "B", "status": "done", "verified": True},
        },
    )
    pulse = build_pulse(
        tmp_path, now_ms=_START_MS + 999_000, stuck_after_ms=_STUCK_AFTER_MS
    )
    assert pulse.overall == VERDICT_IDLE
    assert pulse.idle_count == 1
    assert pulse.swarms[0].verdict == VERDICT_IDLE
    assert pulse.swarms[0].stuck_unit_id is None


def test_no_swarms_yields_empty_pulse_no_crash(tmp_path: Path) -> None:
    pulse = build_pulse(tmp_path, now_ms=_START_MS, stuck_after_ms=_STUCK_AFTER_MS)
    assert pulse.overall == VERDICT_EMPTY
    assert pulse.is_empty is True
    assert pulse.swarm_count == 0
    assert pulse.swarms == ()
    # Rendering an empty pulse must not crash and must carry a glyph.
    text = render_pulse_text(pulse)
    assert "no active swarms" in text


def test_single_swarm_id_filter(tmp_path: Path) -> None:
    _make_swarm(tmp_path, "sw-a", units={"u0": {"goal": "a", "status": "running"}})
    _make_swarm(tmp_path, "sw-b", units={"u0": {"goal": "b", "status": "done"}})
    pulse = build_pulse(
        tmp_path, swarm_id="sw-b", now_ms=_START_MS + 10_000, stuck_after_ms=_STUCK_AFTER_MS
    )
    assert pulse.swarm_count == 1
    assert pulse.swarms[0].swarm_id == "sw-b"
    assert pulse.swarms[0].verdict == VERDICT_IDLE


def test_stuck_wins_overall_across_swarms(tmp_path: Path) -> None:
    _make_swarm(tmp_path, "sw-ok", units={"u0": {"goal": "ok", "status": "running"}})
    _make_swarm(
        tmp_path,
        "sw-bad",
        units={"u0": {"goal": "bad", "status": "running"}},
        started_at="2026-07-04T07:00:00+00:00",  # an hour before _START_MS
    )
    pulse = build_pulse(
        tmp_path, now_ms=_START_MS + 10_000, stuck_after_ms=_STUCK_AFTER_MS
    )
    # sw-ok is fresh (working); sw-bad started an hour ago (stuck) → overall stuck.
    assert pulse.overall == VERDICT_STUCK
    assert pulse.working_count == 1
    assert pulse.stuck_count == 1


def test_now_ms_none_never_falsely_stuck(tmp_path: Path) -> None:
    """The pure core must not reach for a live clock; None now_ms degrades to working."""
    _make_swarm(
        tmp_path,
        "sw-1",
        units={"u0": {"goal": "g", "status": "running"}},
        started_at="2020-01-01T00:00:00+00:00",  # ancient
    )
    pulse = build_pulse(tmp_path, now_ms=None, stuck_after_ms=_STUCK_AFTER_MS)
    assert pulse.overall == VERDICT_WORKING
    assert pulse.swarms[0].elapsed_ms == 0


def test_render_text_contains_glyph_and_unit(tmp_path: Path) -> None:
    _make_swarm(
        tmp_path,
        "sw-stuck",
        units={"unit-0007": {"goal": "wedged", "status": "running"}},
    )
    pulse = build_pulse(
        tmp_path, now_ms=_START_MS + 360_000, stuck_after_ms=_STUCK_AFTER_MS
    )
    text = render_pulse_text(pulse)
    assert "⚠️" in text
    assert "unit-0007" in text
    assert "sw-stuck" in text


def test_to_event_is_dict_with_expected_keys(tmp_path: Path) -> None:
    _make_swarm(
        tmp_path,
        "sw-stuck",
        units={"unit-0000": {"goal": "g", "status": "running"}},
    )
    pulse = build_pulse(
        tmp_path, now_ms=_START_MS + 360_000, stuck_after_ms=_STUCK_AFTER_MS
    )
    event = to_event(pulse)
    assert isinstance(event, dict)
    assert event["severity"] == "failure"  # stuck → failure severity
    assert event["overall"] == VERDICT_STUCK
    assert "title" in event and "detail" in event
    assert "⚠️" in event["title"]
    # Fully JSON round-trippable (used as a push payload).
    assert json.loads(json.dumps(event))["overall"] == VERDICT_STUCK


def test_deterministic_with_fixed_now_ms(tmp_path: Path) -> None:
    _make_swarm(tmp_path, "sw-1", units={"u0": {"goal": "g", "status": "running"}})
    a = build_pulse(tmp_path, now_ms=_START_MS + 5_000, stuck_after_ms=_STUCK_AFTER_MS)
    b = build_pulse(tmp_path, now_ms=_START_MS + 5_000, stuck_after_ms=_STUCK_AFTER_MS)
    assert a.to_dict() == b.to_dict()


# ---------------------------------------------------------------------------
# CLI surface (flags exercised via CliRunner — never assert Rich --help output)
# ---------------------------------------------------------------------------


def test_cli_pulse_no_swarms_exit_zero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    result = CliRunner().invoke(app, ["pulse"])
    assert result.exit_code == 0
    assert "no active swarms" in result.stdout


def test_cli_pulse_json_working(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _make_swarm(
        tmp_path, "sw-1", units={"u0": {"goal": "g", "status": "running"}}, started_at=_now_iso()
    )
    result = CliRunner().invoke(app, ["pulse", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    # Real clock is injected by the CLI; a just-created manifest is fresh.
    assert payload["overall"] == VERDICT_WORKING
    assert payload["swarm_count"] == 1


def test_cli_pulse_stuck_exit_two(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    # An ancient start + a tiny --stuck-after guarantees a stuck verdict.
    _make_swarm(
        tmp_path,
        "sw-old",
        units={"unit-0000": {"goal": "g", "status": "running"}},
        started_at="2020-01-01T00:00:00+00:00",
    )
    result = CliRunner().invoke(app, ["pulse", "--stuck-after", "1"])
    assert result.exit_code == 2
    assert "⚠️" in result.stdout


def test_cli_pulse_notify_writes_file_sink(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    _make_swarm(
        tmp_path, "sw-1", units={"u0": {"goal": "g", "status": "running"}}, started_at=_now_iso()
    )
    result = CliRunner().invoke(app, ["pulse", "--notify"])
    assert result.exit_code == 0
    # The default FileSink appends a JSONL record under .onmc/notify.log.
    log = tmp_path / ".onmc" / "notify.log"
    assert log.exists()
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert "onmc pulse" in record["title"]


def test_cli_pulse_rejects_non_positive_stuck_after(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    result = CliRunner().invoke(app, ["pulse", "--stuck-after", "0"])
    assert result.exit_code == 1
