"""Tests for the accountable agent gateway.

Covers all three layers, offline (no socket bound):

- :func:`oh_no_my_claudecode.gateway.pipeline.handle_inbound` — the deterministic
  deny / action / ignore / accept decision tree over the mission-bridge brain.
- :func:`oh_no_my_claudecode.gateway.server.route` — the socket-free HTTP router
  (``GET /health``, ``POST /webhook`` happy + malformed) and the default dry
  dispatcher.
- the ``onmc gateway`` CLI group via ``CliRunner`` (flags/JSON/exit codes only —
  never Rich ``--help`` output).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.gateway.pipeline import (
    STATUS_ACCEPTED,
    STATUS_ACTION,
    STATUS_DENIED,
    STATUS_IGNORED,
    handle_inbound,
)
from oh_no_my_claudecode.gateway.server import dry_dispatcher, make_handler, route
from oh_no_my_claudecode.missionbridge.auth import add_identity
from oh_no_my_claudecode.missionbridge.models import ApproveKind, IntakeTask


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:  # older click without mix_stderr
        return CliRunner()


def _allow(repo_root: Path, identity: str) -> None:
    """Add *identity* to the repo's mission allowlist."""
    add_identity(repo_root, identity)


def _git_repo(tmp_path: Path) -> Path:
    """Initialize a git repo at *tmp_path* so ``discover_repo_root`` resolves it.

    Returns the resolved root (git resolves symlinks such as ``/tmp`` →
    ``/private/tmp`` on macOS), which is what the CLI writes/reads under.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path.resolve()


# ---------------------------------------------------------------------------
# pipeline.handle_inbound
# ---------------------------------------------------------------------------


def test_denied_identity_returns_denied(tmp_path: Path) -> None:
    # Empty allowlist → deny-by-default.
    result = handle_inbound(tmp_path, channel="slack", user_id="U404", text="@onmc do it")
    assert result.status == STATUS_DENIED
    assert result.reason
    assert result.task is None and result.action is None


def test_valid_identity_and_goal_is_accepted(tmp_path: Path) -> None:
    _allow(tmp_path, "slack:U1")
    result = handle_inbound(
        tmp_path,
        channel="slack",
        user_id="U1",
        text="@onmc add OAuth to auth with 4 agents",
    )
    assert result.status == STATUS_ACCEPTED
    assert result.action is None
    assert result.task == IntakeTask(goal="add OAuth to auth", concurrency=4, budget_usd=None)
    assert result.task is not None
    assert result.task.goal == "add OAuth to auth"


def test_approve_message_is_an_action(tmp_path: Path) -> None:
    _allow(tmp_path, "slack:U1")
    result = handle_inbound(tmp_path, channel="slack", user_id="U1", text="approve all")
    assert result.status == STATUS_ACTION
    assert result.action is not None
    assert result.action.kind is ApproveKind.APPROVE_ALL
    assert result.task is None


def test_button_callback_is_an_action(tmp_path: Path) -> None:
    _allow(tmp_path, "telegram:42")
    result = handle_inbound(
        tmp_path,
        channel="telegram",
        user_id="42",
        text="mission:approve:unit-0001",
    )
    assert result.status == STATUS_ACTION
    assert result.action is not None
    assert result.action.kind is ApproveKind.APPROVE_UNIT
    assert result.action.unit_id == "unit-0001"


def test_mention_only_is_ignored(tmp_path: Path) -> None:
    _allow(tmp_path, "slack:U1")
    result = handle_inbound(tmp_path, channel="slack", user_id="U1", text="@onmc")
    assert result.status == STATUS_IGNORED
    assert result.task is None and result.action is None


def test_channel_scoping_denies_same_id_on_other_channel(tmp_path: Path) -> None:
    _allow(tmp_path, "slack:U1")
    denied = handle_inbound(tmp_path, channel="telegram", user_id="U1", text="@onmc go build")
    assert denied.status == STATUS_DENIED


# ---------------------------------------------------------------------------
# server.route — socket-free
# ---------------------------------------------------------------------------


def test_route_health_returns_200_ok(tmp_path: Path) -> None:
    status, payload = route("GET", "/health", None, repo_root=tmp_path)
    assert status == 200
    assert payload["ok"] is True
    assert "version" in payload


def test_route_webhook_happy_path_accepts_and_dry_dispatches(tmp_path: Path) -> None:
    _allow(tmp_path, "slack:U1")
    body = json.dumps({"channel": "slack", "user_id": "U1", "text": "@onmc ship the docs"})
    status, payload = route("POST", "/webhook", body, repo_root=tmp_path)
    assert status == 200
    assert payload["status"] == STATUS_ACCEPTED
    assert payload["task"]["goal"] == "ship the docs"
    # Default dispatcher is the dry one — decides but never spawns.
    assert payload["dispatch"] == {"dispatched": False, "note": "dry"}


def test_route_webhook_denied_has_no_dispatch(tmp_path: Path) -> None:
    body = json.dumps({"channel": "slack", "user_id": "nope", "text": "@onmc do it"})
    status, payload = route("POST", "/webhook", body, repo_root=tmp_path)
    assert status == 200
    assert payload["status"] == STATUS_DENIED
    assert "dispatch" not in payload


def test_route_webhook_malformed_json_is_400(tmp_path: Path) -> None:
    status, payload = route("POST", "/webhook", "{not json", repo_root=tmp_path)
    assert status == 400
    assert "error" in payload


def test_route_webhook_missing_fields_is_400(tmp_path: Path) -> None:
    body = json.dumps({"channel": "slack"})  # no user_id / text
    status, payload = route("POST", "/webhook", body, repo_root=tmp_path)
    assert status == 400


def test_route_unknown_endpoint_is_404(tmp_path: Path) -> None:
    status, _payload = route("GET", "/nope", None, repo_root=tmp_path)
    assert status == 404


def test_route_bytes_body_is_decoded(tmp_path: Path) -> None:
    _allow(tmp_path, "slack:U1")
    body = json.dumps({"channel": "slack", "user_id": "U1", "text": "@onmc go"}).encode("utf-8")
    status, payload = route("POST", "/webhook", body, repo_root=tmp_path)
    assert status == 200
    assert payload["status"] == STATUS_ACCEPTED


def test_injected_dispatcher_is_invoked_for_accepted(tmp_path: Path) -> None:
    _allow(tmp_path, "slack:U1")
    seen: list[str] = []

    def spy(repo_root: Path, task: IntakeTask) -> dict[str, object]:  # noqa: ARG001
        seen.append(task.goal)
        return {"dispatched": True, "swarm_id": "sw_test"}

    body = json.dumps({"channel": "slack", "user_id": "U1", "text": "@onmc fix flaky test"})
    status, payload = route("POST", "/webhook", body, repo_root=tmp_path, dispatcher=spy)
    assert status == 200
    assert seen == ["fix flaky test"]
    assert payload["dispatch"] == {"dispatched": True, "swarm_id": "sw_test"}


def test_dry_dispatcher_default_returns_dry(tmp_path: Path) -> None:
    assert dry_dispatcher(tmp_path, IntakeTask(goal="x")) == {"dispatched": False, "note": "dry"}


def test_make_handler_returns_handler_class(tmp_path: Path) -> None:
    import http.server

    handler = make_handler(tmp_path)
    assert issubclass(handler, http.server.BaseHTTPRequestHandler)


# ---------------------------------------------------------------------------
# CLI — CliRunner (no --help assertions)
# ---------------------------------------------------------------------------


def test_cli_simulate_accepts_goal(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _git_repo(tmp_path)
    _allow(root, "slack:U1")
    monkeypatch.chdir(root)
    runner = _cli_runner()
    result = runner.invoke(app, ["gateway", "simulate", "slack", "U1", "@onmc build the dashboard"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == STATUS_ACCEPTED
    assert payload["task"]["goal"] == "build the dashboard"


def test_cli_simulate_denied_exits_1(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _git_repo(tmp_path)
    monkeypatch.chdir(root)
    runner = _cli_runner()
    result = runner.invoke(app, ["gateway", "simulate", "slack", "nobody", "@onmc do it"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == STATUS_DENIED


def test_cli_health_prints_ok(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _git_repo(tmp_path)
    monkeypatch.chdir(root)
    runner = _cli_runner()
    result = runner.invoke(app, ["gateway", "health"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert "version" in payload
