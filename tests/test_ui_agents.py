"""Tests for the Agents / swarm orchestration view in onmc ui.

Covers:
- Payload builders with seeded swarm-manifest + receipt fixtures.
- verified / diff_sha surfacing.
- Graceful empty-state when no swarms exist.
- /api/agents/action endpoint: abort / land / mission invoke the injected
  runner with exactly the right command and return result JSON.
- Existing GET routes (/api/dashboard, /) still work after POST handler added.
- HTML contains the agents view.
- No test hangs: all server threads are guarded with shutdown() + join(timeout).
"""
from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import AttemptKind, AttemptStatus
from oh_no_my_claudecode.ui import build_agents_payload, create_ui_server
from oh_no_my_claudecode.ui.server import _handle_agents_action

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ready_service(sample_repo: Path, monkeypatch: object) -> OnmcService:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    service.add_attempt(
        service.start_task(
            title="test task",
            description="desc",
            labels=[],
        ).task_id,
        summary="attempt",
        kind=AttemptKind.INVESTIGATION,
        status=AttemptStatus.TRIED,
        reasoning_summary=None,
        evidence_for=None,
        evidence_against=None,
        files_touched=[],
    )
    return service


def _make_manifest(swarm_dir: Path, units: dict[str, object]) -> None:
    swarm_dir.mkdir(parents=True, exist_ok=True)
    (swarm_dir / "manifest.json").write_text(
        json.dumps(
            {
                "swarm_id": swarm_dir.name,
                "mode": "inline",
                "agent": "claude-code-subagent",
                "concurrency": 2,
                "started_at": "2026-07-08T00:00:00",
                "units": units,
            }
        ),
        encoding="utf-8",
    )


def _get(port: int, path: str) -> tuple[int, str, str]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.getheader("Content-Type", ""), resp.read().decode("utf-8")
    finally:
        conn.close()


def _post(port: int, path: str, payload: dict[str, object]) -> tuple[int, str, str]:
    body = json.dumps(payload).encode("utf-8")
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        resp = conn.getresponse()
        return resp.status, resp.getheader("Content-Type", ""), resp.read().decode("utf-8")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Payload builder tests (no socket — pure filesystem)
# ---------------------------------------------------------------------------


def test_agents_payload_from_seeded_manifest(tmp_path: Path) -> None:
    """build_agents_payload returns local swarm summary from a seeded manifest."""
    swarm_dir = tmp_path / ".onmc" / "swarm" / "sw-abc"
    _make_manifest(
        swarm_dir,
        {
            "unit-0000": {
                "goal": "write alpha",
                "status": "done",
                "verified": True,
                "cost_usd": 0.5,
            },
            "unit-0001": {
                "goal": "write beta",
                "status": "running",
                "verified": None,
                "cost_usd": 0.0,
            },
        },
    )

    payload = build_agents_payload(tmp_path)

    local = payload["local"]
    assert local["summary"]["swarms"] == 1
    assert local["summary"]["running_units"] == 1
    assert local["summary"]["verified_units"] == 1
    row = local["swarms"][0]
    assert row["swarm_id"] == "sw-abc"
    assert row["total"] == 2
    assert row["verified_count"] == 1
    assert row["live"] is True


def test_agents_payload_verified_and_diff_sha_surfaced(tmp_path: Path) -> None:
    """Units carry verified + diff_sha from their receipt when present."""
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / "run-x.json"
    receipt_path.write_text(
        json.dumps(
            {
                "verified": True,
                "diff_sha": "abc123def456" * 3,
                "tokens_used": 9000,
                "wall_seconds": 30.0,
                "iterations": 1,
                "verifier_final_exit": 0,
                "receipt_hash": "deadbeef1234",
            }
        ),
        encoding="utf-8",
    )
    swarm_dir = tmp_path / ".onmc" / "swarm" / "sw-xyz"
    _make_manifest(
        swarm_dir,
        {
            "unit-0000": {
                "goal": "build it",
                "status": "done",
                "verified": True,
                "cost_usd": 0.25,
                "receipt_path": str(receipt_path),
            }
        },
    )

    payload = build_agents_payload(tmp_path)

    unit = payload["local"]["swarms"][0]["units"][0]
    assert unit["verified"] is True
    assert unit["diff_sha"] is not None and len(unit["diff_sha"]) > 8
    assert unit["receipt_hash"] == "deadbeef1234"


def test_agents_payload_empty_graceful(tmp_path: Path) -> None:
    """No swarms on disk → safe default with zero counts, no crash."""
    payload = build_agents_payload(tmp_path)

    assert payload["local"]["summary"]["swarms"] == 0
    assert payload["local"]["summary"]["live"] == 0
    assert payload["local"]["swarms"] == []
    assert "global" in payload


# ---------------------------------------------------------------------------
# _handle_agents_action — pure unit tests (no socket)
# ---------------------------------------------------------------------------


def _capturing_runner(captured: list[list[str]]) -> object:
    """Return a runner that records commands and always returns (0, 'ok')."""

    def runner(cmd: list[str]) -> tuple[int, str]:
        captured.append(cmd)
        return 0, "ok"

    return runner


def test_handle_abort_action_calls_runner_with_correct_command() -> None:
    """abort action passes onmc swarm abort <swarm_id> to runner."""
    called: list[list[str]] = []
    result = _handle_agents_action(
        {"action": "abort", "swarm_id": "sw-test123"},
        _capturing_runner(called),  # type: ignore[arg-type]
    )

    assert result["ok"] is True
    assert called == [["onmc", "swarm", "abort", "sw-test123"]]


def test_handle_land_action_calls_runner_with_correct_command() -> None:
    """land action passes gh pr merge <pr_url> --squash to runner."""
    called: list[list[str]] = []
    pr_url = "https://github.com/owner/repo/pull/42"
    result = _handle_agents_action(
        {"action": "land", "pr_url": pr_url},
        _capturing_runner(called),  # type: ignore[arg-type]
    )

    assert result["ok"] is True
    assert called == [["gh", "pr", "merge", pr_url, "--squash"]]


def test_handle_mission_action_calls_runner_with_correct_command() -> None:
    """Legacy mission action previews the canonical onmc run contract."""
    called: list[list[str]] = []
    result = _handle_agents_action(
        {"action": "mission", "goal": "add observability"},
        _capturing_runner(called),  # type: ignore[arg-type]
    )

    assert result["ok"] is True
    assert called == [["onmc", "run", "add observability"]]


def test_handle_run_action_calls_canonical_runtime() -> None:
    called: list[list[str]] = []
    result = _handle_agents_action(
        {"action": "run", "goal": "add observability"},
        _capturing_runner(called),  # type: ignore[arg-type]
    )

    assert result["ok"] is True
    assert called == [["onmc", "run", "add observability"]]


def test_handle_unknown_action_returns_error_without_calling_runner() -> None:
    """Unknown action returns error JSON without calling runner."""
    called: list[list[str]] = []
    result = _handle_agents_action(
        {"action": "explode"},
        _capturing_runner(called),  # type: ignore[arg-type]
    )

    assert result["ok"] is False
    assert called == []
    assert "unknown action" in result["output"]


def test_handle_abort_missing_swarm_id_returns_error() -> None:
    called: list[list[str]] = []
    result = _handle_agents_action(
        {"action": "abort"},
        _capturing_runner(called),  # type: ignore[arg-type]
    )
    assert result["ok"] is False
    assert called == []


def test_handle_runner_failure_propagated() -> None:
    """Non-zero returncode from runner surfaces as ok=False."""

    def failing_runner(cmd: list[str]) -> tuple[int, str]:
        return 1, "git error: not a repo"

    result = _handle_agents_action(
        {"action": "abort", "swarm_id": "sw-fail"},
        failing_runner,
    )

    assert result["ok"] is False
    assert result["returncode"] == 1
    assert "git error" in result["output"]


# ---------------------------------------------------------------------------
# HTTP endpoint tests (ephemeral server, guarded teardown)
# ---------------------------------------------------------------------------


def _start_server(
    service: OnmcService,
    runner_log: list[list[str]],
) -> tuple[object, threading.Thread, int]:
    """Spin up an ephemeral server; return (server, thread, port)."""

    def capturing(cmd: list[str]) -> tuple[int, str]:
        runner_log.append(cmd)
        return 0, "captured"

    server = create_ui_server(service, host="127.0.0.1", port=0, command_runner=capturing)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    return server, thread, port


def test_action_endpoint_abort_invokes_injected_runner(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """POST /api/agents/action abort → injectable runner receives the right cmd."""
    service = _ready_service(sample_repo, monkeypatch)
    log: list[list[str]] = []
    server, thread, port = _start_server(service, log)
    try:
        status, ct, body = _post(
            port, "/api/agents/action", {"action": "abort", "swarm_id": "sw-42"}
        )
        data = json.loads(body)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert status == 200
    assert ct.startswith("application/json")
    assert data["ok"] is True
    assert log == [["onmc", "swarm", "abort", "sw-42"]]


def test_action_endpoint_returns_json_on_bad_json_body(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """POST /api/agents/action with malformed JSON returns 400."""
    service = _ready_service(sample_repo, monkeypatch)
    log: list[list[str]] = []
    server, thread, port = _start_server(service, log)
    try:
        bad = b"not-json{"
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(
                "POST",
                "/api/agents/action",
                body=bad,
                headers={"Content-Length": str(len(bad))},
            )
            resp = conn.getresponse()
            status = resp.status
            resp.read()
        finally:
            conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert status == 400
    assert log == []


def test_existing_get_routes_unaffected(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Adding POST handler must not break /api/dashboard or /."""
    service = _ready_service(sample_repo, monkeypatch)
    log: list[list[str]] = []
    server, thread, port = _start_server(service, log)
    try:
        api_status, api_ct, api_body = _get(port, "/api/dashboard")
        page_status, _, page_body = _get(port, "/")
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
    assert missing_status == 404


def test_agents_view_present_in_html(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Served HTML contains the agents view panel + nav button + JS function."""
    service = _ready_service(sample_repo, monkeypatch)
    log: list[list[str]] = []
    server, thread, port = _start_server(service, log)
    try:
        _, _, html = _get(port, "/")
        _, _, js = _get(port, "/assets/app.js")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert 'id="view-agents"' in html
    assert 'data-view="agents"' in html
    assert 'id="agents-mission-btn"' in html
    assert 'id="agents-land-btn"' in html
    assert "renderAgents" in js
    assert "agentAction" in js
    assert "agents-abort-btn" in js
