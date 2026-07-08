"""Tests for the /api/live endpoint and build_live_payload.

Covers:
- build_live_payload from fixture events → active + events keys correct.
- since filter: only events after watermark are returned; active still correct.
- Empty .onmc/live/ (absent directory) → graceful zeroed response, no error.
- Empty events.jsonl → zeroed response, no error.
- /api/live endpoint (ephemeral port) returns JSON with expected keys.
- Existing agents view HTML and JS are untouched.
- Determinism: same events → same output on repeated calls.
"""
from __future__ import annotations

import dataclasses
import json
import threading
from http.client import HTTPConnection
from pathlib import Path

from oh_no_my_claudecode.telemetry.bus import Event, emit
from oh_no_my_claudecode.ui import build_live_payload

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_events(live_dir: Path, events: list[Event]) -> None:
    """Seed live_dir/events.jsonl with fixture events."""
    live_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(dataclasses.asdict(ev)) + "\n" for ev in events]
    (live_dir / "events.jsonl").write_text("".join(lines), encoding="utf-8")


def _make_service(sample_repo: Path, monkeypatch: object) -> object:
    from oh_no_my_claudecode.core.service import OnmcService
    from oh_no_my_claudecode.models import AttemptKind, AttemptStatus

    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    service.add_attempt(
        service.start_task(title="live test task", description="desc", labels=[]).task_id,
        summary="attempt",
        kind=AttemptKind.INVESTIGATION,
        status=AttemptStatus.TRIED,
        reasoning_summary=None,
        evidence_for=None,
        evidence_against=None,
        files_touched=[],
    )
    return service


def _start_server(service: object) -> tuple[object, threading.Thread, int]:
    """Spin up an ephemeral server; return (server, thread, port)."""
    from oh_no_my_claudecode.ui import create_ui_server

    server = create_ui_server(service, host="127.0.0.1", port=0)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    return server, thread, port


def _get(port: int, path: str) -> tuple[int, str, str]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.getheader("Content-Type", ""), resp.read().decode("utf-8")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Payload builder — pure filesystem tests (no socket)
# ---------------------------------------------------------------------------


def test_build_live_payload_active_and_events_from_fixture(tmp_path: Path) -> None:
    """Fixture events → correct active agents and serialised events."""
    live_dir = tmp_path / ".onmc" / "live"
    events = [
        Event(ts=1000.0, kind="unit_queued", unit="u1", agent="claude", swarm_id="sw1"),
        Event(ts=1001.0, kind="tool_call", unit="u1", agent="claude", tool="Bash"),
        Event(ts=1002.0, kind="unit_queued", unit="u2", agent="sonnet", swarm_id="sw1"),
    ]
    _write_events(live_dir, events)

    payload = build_live_payload(live_dir)

    assert "active" in payload
    assert "events" in payload
    assert "max_ts" in payload

    active = payload["active"]
    assert len(active) == 2  # u1 and u2 both started, neither stopped
    units = {a["unit"] for a in active}
    assert units == {"u1", "u2"}
    assert payload["max_ts"] == 1002.0
    # All 3 events returned when no since filter
    assert len(payload["events"]) == 3


def test_build_live_payload_since_filter_events_only(tmp_path: Path) -> None:
    """since filter limits returned events but active is still fully computed."""
    live_dir = tmp_path / ".onmc" / "live"
    events = [
        Event(ts=100.0, kind="unit_queued", unit="u1", agent="claude", swarm_id="sw1"),
        Event(ts=200.0, kind="tool_call", unit="u1", agent="claude", tool="Read"),
        Event(ts=300.0, kind="unit_done", unit="u1", agent="claude", swarm_id="sw1"),
        Event(ts=400.0, kind="unit_queued", unit="u2", agent="sonnet", swarm_id="sw1"),
    ]
    _write_events(live_dir, events)

    # Request events after ts=200 (so only 300 and 400 in events list)
    payload = build_live_payload(live_dir, since=200.0)

    event_tss = [e["ts"] for e in payload["events"]]
    assert event_tss == [300.0, 400.0]  # ts > 200

    # Active: u1 is done, u2 still running — requires full history
    active_units = {a["unit"] for a in payload["active"]}
    assert active_units == {"u2"}

    assert payload["max_ts"] == 400.0


def test_build_live_payload_empty_live_dir_graceful(tmp_path: Path) -> None:
    """Absent .onmc/live/ returns zeroed payload without raising."""
    live_dir = tmp_path / ".onmc" / "live"  # does not exist

    payload = build_live_payload(live_dir)

    assert payload["active"] == []
    assert payload["events"] == []
    assert payload["max_ts"] == 0.0


def test_build_live_payload_empty_events_file_graceful(tmp_path: Path) -> None:
    """Existing but empty events.jsonl returns zeroed payload."""
    live_dir = tmp_path / ".onmc" / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "events.jsonl").write_text("", encoding="utf-8")

    payload = build_live_payload(live_dir)

    assert payload["active"] == []
    assert payload["events"] == []
    assert payload["max_ts"] == 0.0


def test_build_live_payload_deterministic(tmp_path: Path) -> None:
    """Same events → identical payload on repeated calls."""
    live_dir = tmp_path / ".onmc" / "live"
    events = [
        Event(ts=500.0, kind="unit_queued", unit="u1", swarm_id="sw1"),
        Event(ts=501.0, kind="tool_call", unit="u1", tool="Write"),
    ]
    _write_events(live_dir, events)

    first = build_live_payload(live_dir)
    second = build_live_payload(live_dir)

    assert first["max_ts"] == second["max_ts"]
    assert len(first["events"]) == len(second["events"])
    assert len(first["active"]) == len(second["active"])


def test_build_live_payload_via_emit(tmp_path: Path) -> None:
    """Using telemetry.emit to write events produces a valid payload."""
    live_dir = tmp_path / ".onmc" / "live"
    emit(
        Event(ts=10.0, kind="unit_queued", unit="u1", agent="claude", swarm_id="sw-x"),
        live_dir=live_dir,
    )
    emit(Event(ts=11.0, kind="subagent_stop", unit="u1", agent="claude"), live_dir=live_dir)

    payload = build_live_payload(live_dir)

    # subagent_stop is not a _STOP_KIND so u1 remains active
    assert len(payload["active"]) == 1
    assert payload["active"][0]["unit"] == "u1"
    assert payload["max_ts"] == 11.0


def test_build_live_payload_no_active_when_all_done(tmp_path: Path) -> None:
    """Unit that both starts and stops produces zero active agents."""
    live_dir = tmp_path / ".onmc" / "live"
    events = [
        Event(ts=1.0, kind="unit_queued", unit="u1", swarm_id="sw1"),
        Event(ts=2.0, kind="unit_done", unit="u1", swarm_id="sw1"),
    ]
    _write_events(live_dir, events)

    payload = build_live_payload(live_dir)

    assert payload["active"] == []
    assert len(payload["events"]) == 2


# ---------------------------------------------------------------------------
# HTTP endpoint tests (ephemeral server, guarded teardown)
# ---------------------------------------------------------------------------


def test_api_live_returns_json_with_expected_keys(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """GET /api/live returns 200 JSON with active, events, max_ts keys."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service)
    try:
        status, ct, body = _get(port, "/api/live")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200
    assert ct.startswith("application/json")
    data = json.loads(body)
    assert "active" in data
    assert "events" in data
    assert "max_ts" in data
    assert isinstance(data["active"], list)
    assert isinstance(data["events"], list)
    assert isinstance(data["max_ts"], float)


def test_api_live_since_param_accepted(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """GET /api/live?since=12345.0 returns 200 (param parsed without error)."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service)
    try:
        status, _, body = _get(port, "/api/live?since=12345.0")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200
    data = json.loads(body)
    assert "max_ts" in data


def test_api_live_bad_since_param_still_returns_200(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """GET /api/live?since=notanumber returns 200 (graceful fallback)."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service)
    try:
        status, _, body = _get(port, "/api/live?since=notanumber")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200
    data = json.loads(body)
    assert data["active"] == []


def test_existing_routes_unaffected_by_live_endpoint(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Adding /api/live must not break /api/dashboard, /, or 404 for unknown paths."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service)
    try:
        api_status, api_ct, api_body = _get(port, "/api/dashboard")
        page_status, _, page_body = _get(port, "/")
        live_status, live_ct, _ = _get(port, "/api/live")
        missing_status, _, _ = _get(port, "/no-such-path")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert api_status == 200
    assert api_ct.startswith("application/json")
    assert json.loads(api_body)["repo"]["name"] == "sample-repo"
    assert page_status == 200
    assert "ONMC" in page_body
    assert live_status == 200
    assert live_ct.startswith("application/json")
    assert missing_status == 404


def test_agents_live_panel_present_in_html(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Agents view HTML contains the live activity panel and JS contains pollLiveFeed."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service)
    try:
        _, _, html = _get(port, "/")
        _, _, js = _get(port, "/assets/app.js")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # HTML structure
    assert 'id="agents-active-list"' in html
    assert 'id="agents-live-feed"' in html
    assert 'id="agents-live-title"' in html
    # JS functions
    assert "pollLiveFeed" in js
    assert "renderLiveFeed" in js
    assert "formatElapsed" in js
    assert "/api/live" in js
