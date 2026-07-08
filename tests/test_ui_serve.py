"""Tests for onmc ui --serve: bearer-token auth + POST /api/live/ingest.

Covers (≥7 tests):
- _is_authorized: correct token → True; no-token-set → always True; missing header → False;
  wrong token → False; wrong scheme → False.
- No token configured: unauthenticated GET /api/live works (localhost default).
- Token set + missing auth header → 401 on GET.
- Token set + wrong token → 401 on GET.
- Token set + correct token → 200 on GET.
- POST /api/live/ingest single event appends to live_dir (via injectable live_dir).
- POST /api/live/ingest batch (JSON array) appends multiple events.
- POST /api/live/ingest malformed JSON → 400, server does not crash.
- POST /api/live/ingest with token set: missing auth → 401.
- POST /api/live/ingest with token set: correct auth → 200 + event written.
- Existing routes (/api/live, /) still work with correct token auth.
- Ephemeral port-0 bind: one request then clean shutdown — no hang.

NEVER binds 0.0.0.0 in any test.
"""
from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from oh_no_my_claudecode.ui.server import _ingest_events, _is_authorized

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(sample_repo: Path, monkeypatch: object) -> object:
    from oh_no_my_claudecode.core.service import OnmcService
    from oh_no_my_claudecode.models import AttemptKind, AttemptStatus

    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    service.add_attempt(
        service.start_task(title="serve-test task", description="desc", labels=[]).task_id,
        summary="attempt",
        kind=AttemptKind.INVESTIGATION,
        status=AttemptStatus.TRIED,
        reasoning_summary=None,
        evidence_for=None,
        evidence_against=None,
        files_touched=[],
    )
    return service


def _start_server(
    service: object,
    *,
    token: str | None = None,
    live_dir: Path | None = None,
) -> tuple[object, threading.Thread, int]:
    """Spin up an ephemeral server on 127.0.0.1:0; return (server, thread, port)."""
    from oh_no_my_claudecode.ui import create_ui_server

    server = create_ui_server(  # type: ignore[arg-type]
        service, host="127.0.0.1", port=0, token=token, live_dir=live_dir
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    return server, thread, port


def _get(port: int, path: str, *, auth: str | None = None) -> tuple[int, str, str]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers: dict[str, str] = {}
        if auth is not None:
            headers["Authorization"] = auth
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.getheader("Content-Type", ""), resp.read().decode("utf-8")
    finally:
        conn.close()


def _post(
    port: int,
    path: str,
    body: bytes,
    *,
    auth: str | None = None,
    content_type: str = "application/json",
) -> tuple[int, str, str]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers: dict[str, str] = {"Content-Type": content_type}
        if auth is not None:
            headers["Authorization"] = auth
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.getheader("Content-Type", ""), resp.read().decode("utf-8")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Pure logic — _is_authorized (no server, no I/O)
# ---------------------------------------------------------------------------


def test_is_authorized_no_token_always_allows() -> None:
    """When no token is configured every request is authorized regardless of headers."""
    assert _is_authorized(None, None) is True
    assert _is_authorized(None, "") is True
    assert _is_authorized("Bearer something", None) is True


def test_is_authorized_correct_token_returns_true() -> None:
    assert _is_authorized("Bearer secret123", "secret123") is True


def test_is_authorized_missing_header_returns_false() -> None:
    assert _is_authorized(None, "secret123") is False


def test_is_authorized_wrong_token_returns_false() -> None:
    assert _is_authorized("Bearer wrong-token", "secret123") is False


def test_is_authorized_wrong_scheme_returns_false() -> None:
    assert _is_authorized("Basic secret123", "secret123") is False


# ---------------------------------------------------------------------------
# Pure logic — _ingest_events (no server, injectable live_dir)
# ---------------------------------------------------------------------------


def test_ingest_events_single_event_appends(tmp_path: Path) -> None:
    """Single event dict is written as one JSONL line to live_dir."""
    live_dir = tmp_path / ".onmc" / "live"
    payload = json.dumps({"ts": 1000.0, "kind": "unit_queued", "unit": "u1", "agent": "claude"})
    result, status = _ingest_events(payload.encode(), live_dir)

    assert status == 200
    assert result["ok"] is True
    assert result["accepted"] == 1

    lines = (live_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    ev = json.loads(lines[0])
    assert ev["kind"] == "unit_queued"
    assert ev["unit"] == "u1"


def test_ingest_events_batch_appends_multiple(tmp_path: Path) -> None:
    """A JSON array is treated as a batch; each item becomes a separate JSONL line."""
    live_dir = tmp_path / ".onmc" / "live"
    batch = [
        {"ts": 1.0, "kind": "unit_queued", "unit": "u1"},
        {"ts": 2.0, "kind": "tool_call", "unit": "u1", "tool": "Bash"},
        {"ts": 3.0, "kind": "unit_done", "unit": "u1"},
    ]
    result, status = _ingest_events(json.dumps(batch).encode(), live_dir)

    assert status == 200
    assert result["accepted"] == 3

    lines = (live_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_ingest_events_malformed_json_returns_400(tmp_path: Path) -> None:
    """Invalid JSON body → (error dict, 400); live_dir is untouched."""
    live_dir = tmp_path / ".onmc" / "live"
    result, status = _ingest_events(b"not-json{{{", live_dir)

    assert status == 400
    assert result["ok"] is False
    assert not live_dir.exists()


def test_ingest_events_wrong_type_returns_400(tmp_path: Path) -> None:
    """A bare scalar (not dict or list) → (error dict, 400)."""
    live_dir = tmp_path / ".onmc" / "live"
    result, status = _ingest_events(b'"just a string"', live_dir)

    assert status == 400
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# HTTP endpoint tests — all bind 127.0.0.1:0; teardown guarded by join(timeout)
# ---------------------------------------------------------------------------


def test_no_token_unauthenticated_request_allowed(
    sample_repo: Path, monkeypatch: object
) -> None:
    """Server with no token configured allows GET without Authorization header."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service, token=None)
    try:
        status, ct, body = _get(port, "/api/live")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200
    assert ct.startswith("application/json")
    assert "active" in json.loads(body)


def test_token_missing_auth_header_returns_401(
    sample_repo: Path, monkeypatch: object
) -> None:
    """GET without Authorization header returns 401 when token is configured."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service, token="my-secret")  # noqa: S106
    try:
        status, _, _ = _get(port, "/api/live")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 401


def test_token_wrong_bearer_returns_401(
    sample_repo: Path, monkeypatch: object
) -> None:
    """GET with wrong bearer token returns 401."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service, token="my-secret")  # noqa: S106
    try:
        status, _, _ = _get(port, "/api/live", auth="Bearer wrong-token")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 401


def test_token_correct_bearer_returns_200(
    sample_repo: Path, monkeypatch: object
) -> None:
    """GET with correct bearer token returns 200."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service, token="my-secret")  # noqa: S106
    try:
        status, ct, body = _get(port, "/api/live", auth="Bearer my-secret")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200
    assert ct.startswith("application/json")
    assert "active" in json.loads(body)


def test_ingest_endpoint_appends_event_via_http(
    sample_repo: Path, monkeypatch: object, tmp_path: Path
) -> None:
    """POST /api/live/ingest writes a single event to the injected live_dir."""
    service = _make_service(sample_repo, monkeypatch)
    live_dir = tmp_path / "live"
    server, thread, port = _start_server(service, live_dir=live_dir)
    payload = json.dumps({"ts": 42.0, "kind": "unit_queued", "unit": "u1", "agent": "claude"})
    try:
        status, ct, body = _post(port, "/api/live/ingest", payload.encode())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200
    result = json.loads(body)
    assert result["ok"] is True
    assert result["accepted"] == 1

    lines = (live_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["kind"] == "unit_queued"


def test_ingest_endpoint_batch(
    sample_repo: Path, monkeypatch: object, tmp_path: Path
) -> None:
    """POST /api/live/ingest with a JSON array accepts all events."""
    service = _make_service(sample_repo, monkeypatch)
    live_dir = tmp_path / "live"
    server, thread, port = _start_server(service, live_dir=live_dir)
    batch = [
        {"ts": 1.0, "kind": "swarm_planned", "swarm_id": "sw1"},
        {"ts": 2.0, "kind": "unit_queued", "unit": "u1", "swarm_id": "sw1"},
    ]
    try:
        status, _, body = _post(port, "/api/live/ingest", json.dumps(batch).encode())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200
    result = json.loads(body)
    assert result["accepted"] == 2

    lines = (live_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_ingest_endpoint_malformed_json_returns_400(
    sample_repo: Path, monkeypatch: object, tmp_path: Path
) -> None:
    """POST /api/live/ingest with invalid JSON body returns 400, does not crash."""
    service = _make_service(sample_repo, monkeypatch)
    live_dir = tmp_path / "live"
    server, thread, port = _start_server(service, live_dir=live_dir)
    try:
        status, _, _ = _post(port, "/api/live/ingest", b"{{not json")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 400
    # The live_dir should not have been created (no events written)
    assert not live_dir.exists()


def test_ingest_endpoint_auth_missing_returns_401(
    sample_repo: Path, monkeypatch: object, tmp_path: Path
) -> None:
    """POST /api/live/ingest without token when auth required → 401."""
    service = _make_service(sample_repo, monkeypatch)
    live_dir = tmp_path / "live"
    server, thread, port = _start_server(service, token="my-token", live_dir=live_dir)  # noqa: S106
    payload = json.dumps({"ts": 1.0, "kind": "unit_queued", "unit": "u1"})
    try:
        status, _, _ = _post(port, "/api/live/ingest", payload.encode())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 401
    # Nothing should have been written
    assert not live_dir.exists()


def test_ingest_endpoint_auth_correct_token_accepted(
    sample_repo: Path, monkeypatch: object, tmp_path: Path
) -> None:
    """POST /api/live/ingest with correct bearer token → 200 + event written."""
    service = _make_service(sample_repo, monkeypatch)
    live_dir = tmp_path / "live"
    server, thread, port = _start_server(service, token="my-token", live_dir=live_dir)  # noqa: S106
    payload = json.dumps({"ts": 99.0, "kind": "tool_call", "tool": "Write", "unit": "u1"})
    try:
        status, _, body = _post(port, "/api/live/ingest", payload.encode(), auth="Bearer my-token")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert status == 200
    assert json.loads(body)["accepted"] == 1
    lines = (live_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_existing_routes_unaffected_with_token(
    sample_repo: Path, monkeypatch: object
) -> None:
    """Existing /api/live and / still work correctly when token is set."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service, token="tok")  # noqa: S106
    try:
        live_status, live_ct, live_body = _get(port, "/api/live", auth="Bearer tok")
        page_status, _, page_body = _get(port, "/", auth="Bearer tok")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert live_status == 200
    assert live_ct.startswith("application/json")
    data = json.loads(live_body)
    assert "active" in data and "events" in data and "max_ts" in data

    assert page_status == 200
    assert "ONMC" in page_body


@pytest.mark.timeout(30)
def test_ephemeral_port_bind_no_hang(sample_repo: Path, monkeypatch: object) -> None:
    """Server binds on port 0, serves one request, shuts down cleanly without hanging."""
    service = _make_service(sample_repo, monkeypatch)
    server, thread, port = _start_server(service)
    try:
        status, _, _ = _get(port, "/api/live")
        assert status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
    # If we reach here the thread exited within timeout — no hang.
    assert not thread.is_alive()
