"""Tests for the telemetry live event bus, hook capture, and onmc live CLI.

Coverage requirements (≥ 9 tests):
1.  emit appends one JSONL line.
2.  Multiple emits append multiple lines.
3.  read_events filters by since_ts.
4.  read_events filters by kinds.
5.  read_events returns [] when file absent.
6.  active_agents folds start+stop correctly (stopped unit not returned).
7.  active_agents returns open units when no stop event.
8.  post_tool_use hook emits tool_call event from a fake payload.
9.  hook exits 0 (no exception raised) on malformed payload.
10. hook no-ops gracefully when .onmc/ is absent.
11. installer registers PostToolUse hook without breaking existing hooks.
12. swarm emit on plan_inline_swarm writes swarm_planned + unit_queued events.
13. swarm emit on record_inline_unit writes unit_done/unit_failed events.
14. onmc live snapshot command (text output).
15. onmc live tail bounded output (--limit).
16. onmc live --json produces valid JSON.
17. onmc live tail --json produces JSONL.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.hooks.installer import (
    POST_TOOL_USE_COMMAND,
    SUBAGENT_STOP_COMMAND,
    hooks_installed,
    install_claude_hooks,
)
from oh_no_my_claudecode.telemetry.bus import Event, active_agents, emit, read_events

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _live_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".onmc" / "live"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. emit appends one JSONL line
# ---------------------------------------------------------------------------

def test_emit_appends_single_jsonl_line(tmp_path: Path) -> None:
    live = _live_dir(tmp_path)
    ev = Event(ts=1_000.0, kind="tool_call", tool="Bash", detail="command=ls")
    emit(ev, live_dir=live)

    lines = (live / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    d = json.loads(lines[0])
    assert d["kind"] == "tool_call"
    assert d["tool"] == "Bash"
    assert d["ts"] == pytest.approx(1_000.0)


# ---------------------------------------------------------------------------
# 2. Multiple emits append multiple lines
# ---------------------------------------------------------------------------

def test_emit_multiple_appends_multiple_lines(tmp_path: Path) -> None:
    live = _live_dir(tmp_path)
    for i in range(5):
        emit(Event(ts=float(i), kind="tool_call"), live_dir=live)

    lines = (live / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    tss = [json.loads(ln)["ts"] for ln in lines]
    assert tss == [0.0, 1.0, 2.0, 3.0, 4.0]


# ---------------------------------------------------------------------------
# 3. read_events filters by since_ts
# ---------------------------------------------------------------------------

def test_read_events_filters_by_since_ts(tmp_path: Path) -> None:
    live = _live_dir(tmp_path)
    for i in range(10):
        emit(Event(ts=float(i), kind="tool_call"), live_dir=live)

    events = read_events(live, since_ts=5.0)
    assert len(events) == 4  # ts 6, 7, 8, 9
    assert all(e.ts > 5.0 for e in events)


# ---------------------------------------------------------------------------
# 4. read_events filters by kinds
# ---------------------------------------------------------------------------

def test_read_events_filters_by_kinds(tmp_path: Path) -> None:
    live = _live_dir(tmp_path)
    emit(Event(ts=1.0, kind="tool_call"), live_dir=live)
    emit(Event(ts=2.0, kind="swarm_planned"), live_dir=live)
    emit(Event(ts=3.0, kind="unit_queued"), live_dir=live)
    emit(Event(ts=4.0, kind="tool_call"), live_dir=live)

    events = read_events(live, kinds=["tool_call"])
    assert len(events) == 2
    assert all(e.kind == "tool_call" for e in events)


# ---------------------------------------------------------------------------
# 5. read_events returns [] when file absent
# ---------------------------------------------------------------------------

def test_read_events_returns_empty_when_no_file(tmp_path: Path) -> None:
    live = tmp_path / ".onmc" / "live"
    live.mkdir(parents=True, exist_ok=True)
    # No events.jsonl written
    assert read_events(live) == []


# ---------------------------------------------------------------------------
# 6. active_agents folds start+stop correctly
# ---------------------------------------------------------------------------

def test_active_agents_removes_stopped_units(tmp_path: Path) -> None:
    live = _live_dir(tmp_path)
    emit(Event(ts=1.0, kind="unit_queued", swarm_id="sw1", unit="unit-0000"), live_dir=live)
    emit(Event(ts=2.0, kind="unit_queued", swarm_id="sw1", unit="unit-0001"), live_dir=live)
    emit(Event(ts=3.0, kind="unit_done", swarm_id="sw1", unit="unit-0000"), live_dir=live)

    agents = active_agents(read_events(live))
    assert len(agents) == 1
    assert agents[0]["unit"] == "unit-0001"


# ---------------------------------------------------------------------------
# 7. active_agents returns open units when no stop event
# ---------------------------------------------------------------------------

def test_active_agents_returns_all_open_units(tmp_path: Path) -> None:
    live = _live_dir(tmp_path)
    emit(
        Event(ts=1.0, kind="unit_queued", swarm_id="sw2", unit="unit-0000", agent="ai"),
        live_dir=live,
    )
    emit(
        Event(ts=2.0, kind="unit_queued", swarm_id="sw2", unit="unit-0001", agent="ai"),
        live_dir=live,
    )

    agents = active_agents(read_events(live))
    assert len(agents) == 2
    units = {a["unit"] for a in agents}
    assert units == {"unit-0000", "unit-0001"}
    # Sorted by since_ts
    assert agents[0]["since_ts"] <= agents[1]["since_ts"]


# ---------------------------------------------------------------------------
# 8. post_tool_use hook emits tool_call event from a fake payload
# ---------------------------------------------------------------------------

def test_post_tool_use_emits_tool_call_event(tmp_path: Path) -> None:
    # Create .onmc/ so the hook doesn't no-op
    onmc_dir = tmp_path / ".onmc"
    onmc_dir.mkdir(parents=True, exist_ok=True)

    from oh_no_my_claudecode.hooks.post_tool_use import handle_post_tool_use

    fake_payload: dict[str, object] = {
        "session_id": "sess-abc",
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
        "cwd": str(tmp_path),
    }
    handle_post_tool_use(payload=fake_payload)

    live_dir = tmp_path / ".onmc" / "live"
    events = read_events(live_dir)
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "tool_call"
    assert ev.tool == "Bash"
    assert ev.session_id == "sess-abc"
    assert ev.detail is not None and "command=ls -la" in ev.detail


# ---------------------------------------------------------------------------
# 9. hook exits 0 / no exception on malformed payload
# ---------------------------------------------------------------------------

def test_post_tool_use_noop_on_malformed_payload(tmp_path: Path) -> None:
    onmc_dir = tmp_path / ".onmc"
    onmc_dir.mkdir(parents=True, exist_ok=True)

    from oh_no_my_claudecode.hooks.post_tool_use import handle_post_tool_use

    # Malformed: tool_name is not a string, tool_input is not a dict
    malformed: dict[str, object] = {
        "session_id": 12345,
        "tool_name": None,
        "tool_input": "not-a-dict",
        "cwd": str(tmp_path),
    }
    # Must not raise
    handle_post_tool_use(payload=malformed)
    # An event is still written (with tool=None)
    live_dir = tmp_path / ".onmc" / "live"
    events = read_events(live_dir)
    assert len(events) == 1
    assert events[0].kind == "tool_call"
    assert events[0].tool is None


# ---------------------------------------------------------------------------
# 10. hook no-ops when .onmc/ is absent
# ---------------------------------------------------------------------------

def test_post_tool_use_noop_when_onmc_absent(tmp_path: Path) -> None:
    from oh_no_my_claudecode.hooks.post_tool_use import handle_post_tool_use

    # .onmc/ does NOT exist
    fake_payload: dict[str, object] = {
        "session_id": "sess-xyz",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hello"},
        "cwd": str(tmp_path),
    }
    # Must not raise and must not create any files
    handle_post_tool_use(payload=fake_payload)

    assert not (tmp_path / ".onmc").exists()


# ---------------------------------------------------------------------------
# 11. installer registers PostToolUse without breaking existing hooks
# ---------------------------------------------------------------------------

def test_installer_registers_post_tool_use_hook(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    payload = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    hooks = payload["hooks"]

    assert "PostToolUse" in hooks
    post_tool_use_cmds = [
        item["command"]
        for entry in hooks["PostToolUse"]
        for item in entry.get("hooks", [])
        if isinstance(item, dict)
    ]
    assert POST_TOOL_USE_COMMAND in post_tool_use_cmds

    assert "SubagentStop" in hooks
    subagent_stop_cmds = [
        item["command"]
        for entry in hooks["SubagentStop"]
        for item in entry.get("hooks", [])
        if isinstance(item, dict)
    ]
    assert SUBAGENT_STOP_COMMAND in subagent_stop_cmds

    # Existing hooks still present
    assert "PreCompact" in hooks
    assert "SessionStart" in hooks
    # hooks_installed() still returns True
    assert hooks_installed(settings_path=tmp_path / ".claude" / "settings.json")


# ---------------------------------------------------------------------------
# 12. swarm emit on plan_inline_swarm
# ---------------------------------------------------------------------------

def test_swarm_plan_emits_planned_and_queued_events(tmp_path: Path) -> None:
    from oh_no_my_claudecode.swarm.inline import plan_inline_swarm

    fixed_now = datetime(2024, 1, 1, tzinfo=UTC)
    plan_inline_swarm(
        tmp_path,
        ["goal A", "goal B"],
        concurrency=2,
        swarm_id="testsw01",
        now=fixed_now,
    )

    live_dir = tmp_path / ".onmc" / "live"
    events = read_events(live_dir)
    kinds = [e.kind for e in events]
    assert "swarm_planned" in kinds
    queued = [e for e in events if e.kind == "unit_queued"]
    assert len(queued) == 2
    assert all(e.swarm_id == "testsw01" for e in events)


# ---------------------------------------------------------------------------
# 13. swarm emit on record_inline_unit
# ---------------------------------------------------------------------------

_FIXED_NOW_2 = datetime(2024, 1, 2, tzinfo=UTC)


def _fake_git_runner(cmd: list[str], cwd: str, timeout: int) -> tuple[int, str]:
    return 0, "abc1234567890abc1234567890abc1234567890ab"


def test_swarm_record_emits_unit_done(tmp_path: Path) -> None:
    from oh_no_my_claudecode.swarm.inline import plan_inline_swarm, record_inline_unit

    plan_inline_swarm(tmp_path, ["do X"], concurrency=1, swarm_id="recsw1", now=_FIXED_NOW_2)
    record_inline_unit(
        tmp_path,
        "recsw1",
        "unit-0000",
        goal="do X",
        summary="done",
        verified=True,
        now=_FIXED_NOW_2,
        git_runner=_fake_git_runner,
    )

    live_dir = tmp_path / ".onmc" / "live"
    events = read_events(live_dir, kinds=["unit_done"])
    assert len(events) == 1
    assert events[0].swarm_id == "recsw1"
    assert events[0].unit == "unit-0000"


def test_swarm_record_emits_unit_failed(tmp_path: Path) -> None:
    from oh_no_my_claudecode.swarm.inline import plan_inline_swarm, record_inline_unit

    plan_inline_swarm(tmp_path, ["do Y"], concurrency=1, swarm_id="recsw2", now=_FIXED_NOW_2)
    record_inline_unit(
        tmp_path,
        "recsw2",
        "unit-0000",
        goal="do Y",
        summary="could not do it",
        verified=False,
        now=_FIXED_NOW_2,
        git_runner=_fake_git_runner,
    )

    live_dir = tmp_path / ".onmc" / "live"
    events = read_events(live_dir, kinds=["unit_failed"])
    assert len(events) == 1
    assert events[0].unit == "unit-0000"


# ---------------------------------------------------------------------------
# 14. onmc live snapshot command (text output) — requires git repo
# ---------------------------------------------------------------------------

def _make_git_repo(path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )


def test_live_snapshot_text_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    live_dir = tmp_path / ".onmc" / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    emit(Event(ts=1.0, kind="tool_call", tool="Bash"), live_dir=live_dir)

    runner = _cli_runner()
    result = runner.invoke(app, ["live"])
    assert result.exit_code == 0
    assert "active agents" in result.output
    assert "recent events" in result.output


# ---------------------------------------------------------------------------
# 15. onmc live tail bounded output
# ---------------------------------------------------------------------------

def test_live_tail_bounded_by_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    live_dir = tmp_path / ".onmc" / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    for i in range(20):
        emit(Event(ts=float(i), kind="tool_call"), live_dir=live_dir)

    runner = _cli_runner()
    result = runner.invoke(app, ["live", "tail", "--limit", "5"])
    assert result.exit_code == 0
    # 5 lines (each event = 1 line)
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) == 5


# ---------------------------------------------------------------------------
# 16. onmc live --json produces valid JSON
# ---------------------------------------------------------------------------

def test_live_snapshot_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    live_dir = tmp_path / ".onmc" / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    emit(Event(ts=42.0, kind="swarm_planned", swarm_id="sw99"), live_dir=live_dir)

    runner = _cli_runner()
    result = runner.invoke(app, ["live", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "active_agents" in payload
    assert "recent_events" in payload
    assert "total_events" in payload
    assert payload["total_events"] == 1


# ---------------------------------------------------------------------------
# 17. onmc live tail --json produces JSONL
# ---------------------------------------------------------------------------

def test_live_tail_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    live_dir = tmp_path / ".onmc" / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    emit(Event(ts=1.0, kind="tool_call", tool="Read"), live_dir=live_dir)
    emit(Event(ts=2.0, kind="unit_done", unit="unit-0000"), live_dir=live_dir)

    runner = _cli_runner()
    result = runner.invoke(app, ["live", "tail", "--json"])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert "kind" in obj
        assert "ts" in obj


# ---------------------------------------------------------------------------
# 18. read_events skips malformed lines gracefully
# ---------------------------------------------------------------------------

def test_read_events_skips_malformed_lines(tmp_path: Path) -> None:
    live = _live_dir(tmp_path)
    events_file = live / "events.jsonl"
    events_file.write_text(
        '{"ts": 1.0, "kind": "tool_call"}\n'
        'NOT VALID JSON\n'
        '{"ts": 2.0, "kind": "unit_done"}\n',
        encoding="utf-8",
    )
    events = read_events(live)
    assert len(events) == 2
    assert [e.kind for e in events] == ["tool_call", "unit_done"]


# ---------------------------------------------------------------------------
# 19. active_agents determinism — empty input
# ---------------------------------------------------------------------------

def test_active_agents_empty_input() -> None:
    result = active_agents([])
    assert result == []


# ---------------------------------------------------------------------------
# 20. Event dataclass round-trips through JSON
# ---------------------------------------------------------------------------

def test_event_json_roundtrip() -> None:
    import dataclasses as _dc

    ev = Event(
        ts=123.456,
        kind="swarm_planned",
        swarm_id="abc123",
        unit="unit-0000",
        agent="my-agent",
        tool=None,
        detail="3 units",
        session_id="sess-42",
    )
    d = _dc.asdict(ev)
    ev2 = Event(
        ts=d["ts"],
        kind=d["kind"],
        swarm_id=d["swarm_id"],
        unit=d["unit"],
        agent=d["agent"],
        tool=d["tool"],
        detail=d["detail"],
        session_id=d["session_id"],
    )
    assert ev2 == ev
