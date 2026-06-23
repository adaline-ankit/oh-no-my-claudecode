from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import AttemptKind, AttemptStatus
from oh_no_my_claudecode.ui import (
    build_dashboard_payload,
    create_ui_server,
    export_dashboard_snapshot,
)


def _ready_service(sample_repo: Path, monkeypatch: object) -> OnmcService:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    task = service.start_task(
        title="Fix cache invalidation",
        description="Trace worker refresh behavior.",
        labels=["bug", "cache"],
    )
    service.add_attempt(
        task.task_id,
        summary="Inspect shared cache boundary.",
        kind=AttemptKind.INVESTIGATION,
        status=AttemptStatus.TRIED,
        reasoning_summary=None,
        evidence_for=None,
        evidence_against=None,
        files_touched=["src/cache.py"],
    )
    return service


def test_dashboard_payload_contains_real_repo_state(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    service = _ready_service(sample_repo, monkeypatch)

    payload = build_dashboard_payload(service)

    assert payload["repo"]["name"] == "sample-repo"
    assert payload["summary"]["memories"] > 0
    assert payload["summary"]["tasks"] == 1
    assert payload["summary"]["attempts"] == 1
    assert payload["tasks"][0]["title"] == "Fix cache invalidation"
    assert payload["tasks"][0]["attempt_count"] == 1
    assert any(item["path"] == "src/cache.py" for item in payload["codegraph"]["files"])
    assert payload["health"]["readiness"] in {"ready", "needs_attention"}
    assert "# ONMC Agent Readiness Report" in payload["report"]


def test_ui_server_serves_dashboard_api_and_assets(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])

    try:
        status, content_type, body = _get(port, "/api/dashboard")
        payload = json.loads(body)
        assert status == 200
        assert content_type.startswith("application/json")
        assert payload["repo"]["name"] == "sample-repo"

        status, _, html = _get(port, "/")
        assert status == 200
        assert "ONMC" in html
        assert 'id="codegraph-canvas"' in html

        status, _, javascript = _get(port, "/assets/app.js")
        assert status == 200
        assert "renderDashboard" in javascript

        status, _, _ = _get(port, "/missing")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ui_cli_delegates_to_dashboard_server(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    OnmcService(sample_repo).init_project()
    captured: dict[str, object] = {}

    def fake_serve(
        service: OnmcService,
        *,
        host: str,
        port: int,
        open_browser: bool,
    ) -> None:
        captured.update(
            {"service": service, "host": host, "port": port, "open_browser": open_browser}
        )

    monkeypatch.setattr("oh_no_my_claudecode.cli.serve_dashboard", fake_serve)

    result = runner.invoke(app, ["ui", "--host", "127.0.0.1", "--port", "9001", "--no-open"])

    assert result.exit_code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9001
    assert captured["open_browser"] is False


def test_dashboard_snapshot_is_standalone(
    sample_repo: Path,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    service = _ready_service(sample_repo, monkeypatch)
    output = tmp_path / "brain.html"

    written = export_dashboard_snapshot(service, output)

    html = written.read_text(encoding="utf-8")
    assert written == output.resolve()
    assert '<script id="onmc-dashboard-data" type="application/json">' in html
    assert "<style>" in html
    assert '<script src="/assets/app.js"' not in html
    assert '<link rel="stylesheet" href="/assets/styles.css">' not in html
    assert '"name":"sample-repo"' in html


def test_dashboard_snapshot_escapes_script_termination(
    sample_repo: Path,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    service = _ready_service(sample_repo, monkeypatch)
    dangerous = "</script><script>alert(1)</script>"
    monkeypatch.setattr(
        "oh_no_my_claudecode.ui.server.build_dashboard_payload",
        lambda _: {"repo": {"name": dangerous}},
    )

    output = export_dashboard_snapshot(service, tmp_path / "safe.html")
    html = output.read_text(encoding="utf-8")

    assert dangerous not in html
    assert "\\u003c/script\\u003e" in html


def test_ui_cli_exports_without_starting_server(
    sample_repo: Path,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    OnmcService(sample_repo).init_project()
    output = tmp_path / "brain.html"
    calls: list[Path] = []

    def fake_export(service: OnmcService, destination: Path) -> Path:
        calls.append(destination)
        destination.write_text("snapshot", encoding="utf-8")
        return destination

    def fail_serve(*args: object, **kwargs: object) -> None:
        raise AssertionError("snapshot export must not start dashboard server")

    monkeypatch.setattr("oh_no_my_claudecode.cli.export_dashboard_snapshot", fake_export)
    monkeypatch.setattr("oh_no_my_claudecode.cli.serve_dashboard", fail_serve)

    result = runner.invoke(app, ["ui", "--export", str(output), "--no-open"])

    assert result.exit_code == 0
    assert calls == [output]
    assert output.name in result.output


def test_dashboard_html_contains_welcome_overlay_markup(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The served HTML page must contain the stable welcome overlay identifiers."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])

    try:
        _, _, html = _get(port, "/")
        # Overlay container
        assert 'id="welcome-overlay"' in html
        assert 'class="welcome-overlay"' in html
        # Dismiss controls
        assert 'id="welcome-close"' in html
        assert 'id="welcome-got-it"' in html
        # Re-open affordance in topbar
        assert 'id="welcome-open"' in html
        # Stats placeholder
        assert 'id="welcome-stats"' in html
        # Steps list
        assert 'class="welcome-steps"' in html
        assert "onmc brief" in html
        assert "onmc loop" in html
        # JS constants
        _, _, js = _get(port, "/assets/app.js")
        assert "WELCOME_KEY" in js
        assert "renderWelcome" in js
        assert "dismissWelcome" in js
        assert "openWelcome" in js
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_dashboard_snapshot_contains_welcome_overlay_markup(
    sample_repo: Path,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """The exported standalone snapshot must also contain the welcome overlay."""
    service = _ready_service(sample_repo, monkeypatch)
    output = tmp_path / "brain.html"

    written = export_dashboard_snapshot(service, output)
    html = written.read_text(encoding="utf-8")

    assert 'id="welcome-overlay"' in html
    assert 'id="welcome-close"' in html
    assert 'id="welcome-got-it"' in html
    assert 'id="welcome-open"' in html
    assert 'id="welcome-stats"' in html
    # JS logic is inlined in the snapshot
    assert "WELCOME_KEY" in html
    assert "renderWelcome" in html


def test_welcome_overlay_js_uses_localstorage_key(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """app.js must reference a versioned localStorage key for dismiss persistence."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])

    try:
        _, _, js = _get(port, "/assets/app.js")
        # The dismiss key must be a versioned string constant
        assert "onmc_welcome_dismissed" in js
        # Threshold constant must be present
        assert "WELCOME_FRESH_THRESHOLD" in js
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_existing_dashboard_views_unaffected_by_welcome(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Adding the welcome overlay must not break existing view identifiers."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])

    try:
        _, _, html = _get(port, "/")
        # All existing view panels remain
        view_ids = ("view-overview", "view-memory", "view-tasks", "view-codegraph", "view-health")
        for view_id in view_ids:
            assert f'id="{view_id}"' in html
        # Core interactive elements
        assert 'id="codegraph-canvas"' in html
        assert 'id="memory-search"' in html
        assert 'id="refresh-button"' in html
        assert 'id="metric-grid"' in html
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(port: int, path: str) -> tuple[int, str, str]:
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return (
            response.status,
            response.getheader("Content-Type", ""),
            response.read().decode("utf-8"),
        )
    finally:
        connection.close()
