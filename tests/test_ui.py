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


def test_dashboard_payload_includes_loops_section_exception_safe(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The loops section is always present and never crashes with no receipts."""
    service = _ready_service(sample_repo, monkeypatch)

    payload = build_dashboard_payload(service)

    assert "loops" in payload
    loops = payload["loops"]
    assert "evolution" in loops
    assert "recent_runs" in loops
    # No receipts written yet → empty run history, no crash.
    assert loops["recent_runs"] == []


def test_dashboard_payload_loops_reads_receipts(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """recent_runs surfaces receipts written under .agent-memory/receipts/."""
    service = _ready_service(sample_repo, monkeypatch)
    receipts_dir = sample_repo / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema_version": "1",
        "goal": "make pytest green",
        "agent": "claude",
        "verified": True,
        "stop_reason": "converged",
        "iterations": 3,
        "tokens_used": 24000,
        "cost_usd": 1.42,
        "wall_seconds": 180.0,
        "verifier_command": "pytest",
        "verifier_final_exit": 0,
        "git_tree_sha": "abc",
        "diff_sha": "def",
        "loop_spec_sha": "s1",
        "output_digest": "o",
        "onmc_version": "0.38.0",
        "started_at": "2026-06-24T10:00:00",
        "ended_at": "2026-06-24T10:03:00",
        "iteration_hashes": ["h"],
        "receipt_hash": "deadbeefcafe",
    }
    (receipts_dir / "run-1.json").write_text(json.dumps(receipt), encoding="utf-8")

    loops = build_dashboard_payload(service)["loops"]

    assert len(loops["recent_runs"]) == 1
    assert loops["recent_runs"][0]["goal"] == "make pytest green"


def test_dashboard_payload_includes_integration_section(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """integration reports whether onmc is the Claude Code default layer."""
    it = build_dashboard_payload(_ready_service(sample_repo, monkeypatch))["integration"]
    assert "level" in it
    assert it["level"] in {"none", "partial", "full"}
    assert "next_steps" in it


def test_dashboard_html_contains_integration_view(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The dashboard ships an Integration view (Claude Code wiring status)."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        _, _, html = _get(port, "/")
        _, _, js = _get(port, "/assets/app.js")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert 'id="view-integration"' in html
    assert "renderIntegration" in js


def test_global_swarms_payload_aggregates_repos(tmp_path: Path) -> None:
    """The global payload folds swarms from every registered repo, tagged by repo."""
    from oh_no_my_claudecode.home import register_repo
    from oh_no_my_claudecode.ui.server import _global_swarms_payload

    home = tmp_path / "home"
    repo = tmp_path / "proj-x"
    swarm_dir = repo / ".onmc" / "swarm" / "sw1"
    swarm_dir.mkdir(parents=True)
    (swarm_dir / "manifest.json").write_text(
        json.dumps(
            {
                "swarm_id": "sw1",
                "units": {"unit-0000": {"goal": "g", "status": "running", "verified": None}},
            }
        ),
        encoding="utf-8",
    )
    register_repo(repo, home=home)

    payload = _global_swarms_payload(home=home)

    assert payload["summary"]["repos"] == 1
    assert payload["summary"]["swarms"] == 1
    assert payload["summary"]["running_units"] == 1
    assert payload["swarms"][0]["repo"] == "proj-x"


def test_dashboard_payload_includes_timeline_section(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """timeline groups memories into JSON-safe periods (via onmc timeline)."""
    service = _ready_service(sample_repo, monkeypatch)
    tl = build_dashboard_payload(service)["timeline"]
    assert "periods" in tl
    assert "total" in tl
    assert "notes" in tl
    # Any entry timestamps are ISO strings (JSON-safe), never datetime objects.
    for period in tl["periods"]:
        for entry in period["entries"]:
            assert entry["ts"] is None or isinstance(entry["ts"], str)


def test_dashboard_payload_includes_scorecard_section(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """scorecard surfaces the readiness/trust card + shareable markdown."""
    service = _ready_service(sample_repo, monkeypatch)
    sc = build_dashboard_payload(service)["scorecard"]
    assert "readiness" in sc
    assert "notes" in sc
    assert "markdown" in sc
    # readiness is an int (0-100) or None; never crashes on a fresh repo.
    assert sc["readiness"] is None or isinstance(sc["readiness"], int)


def test_dashboard_payload_includes_performance_section(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """performance surfaces flywheel model stats + ledger totals from receipts."""
    service = _ready_service(sample_repo, monkeypatch)
    receipts_dir = sample_repo / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    for i, verified in enumerate([True, True, False]):
        (receipts_dir / f"run-{i}.json").write_text(
            json.dumps(
                {
                    "goal": "make tests green",
                    "model": "opus",
                    "verified": verified,
                    "cost_usd": 0.5,
                    "wall_seconds": 60.0,
                    "tokens_used": 1000,
                    "started_at": "2026-07-05T10:00:00",
                    "ended_at": "2026-07-05T10:01:00",
                }
            ),
            encoding="utf-8",
        )

    perf = build_dashboard_payload(service)["performance"]

    assert perf["flywheel"]["total"] == 3
    assert perf["flywheel"]["verified_total"] == 2
    assert perf["ledger"]["run_count"] == 3
    assert any(m["model"] == "opus" for m in perf["flywheel"]["by_model"])


def test_dashboard_payload_performance_exception_safe(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """performance is present and empty-safe when there are no receipts."""
    service = _ready_service(sample_repo, monkeypatch)
    perf = build_dashboard_payload(service)["performance"]
    assert "flywheel" in perf
    assert "ledger" in perf


def test_dashboard_payload_includes_swarms_section_exception_safe(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The swarms section is always present and empty-safe with no swarm state."""
    service = _ready_service(sample_repo, monkeypatch)

    payload = build_dashboard_payload(service)

    assert "swarms" in payload
    swarms = payload["swarms"]
    assert swarms["swarms"] == []
    assert swarms["summary"]["live"] == 0
    assert swarms["summary"]["swarms"] == 0


def test_dashboard_payload_swarms_reads_manifest(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """swarms surfaces live units + verified counts from a swarm manifest."""
    service = _ready_service(sample_repo, monkeypatch)
    swarm_dir = sample_repo / ".onmc" / "swarm" / "sw1"
    swarm_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "swarm_id": "sw1",
        "mode": "inline",
        "agent": "claude-code-subagent",
        "concurrency": 2,
        "started_at": "2026-07-05T00:00:00",
        "units": {
            "unit-0000": {
                "goal": "build alpha",
                "status": "running",
                "verified": None,
                "cost_usd": 0.0,
            },
            "unit-0001": {
                "goal": "build beta",
                "status": "done",
                "verified": True,
                "cost_usd": 0.5,
            },
        },
    }
    (swarm_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    swarms = build_dashboard_payload(service)["swarms"]

    assert swarms["summary"]["swarms"] == 1
    assert swarms["summary"]["live"] == 1  # one unit still running
    assert swarms["summary"]["running_units"] == 1
    assert swarms["summary"]["verified_units"] == 1
    row = swarms["swarms"][0]
    assert row["swarm_id"] == "sw1"
    assert row["live"] is True
    assert row["label"] == "build alpha"
    assert row["verified_count"] == 1


def test_swarm_units_enriched_with_receipt_detail(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Units carry compact receipt detail (tokens/wall/exit) for the drilldown."""
    service = _ready_service(sample_repo, monkeypatch)
    receipts_dir = sample_repo / ".agent-memory" / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipts_dir / "run-x.json"
    receipt_path.write_text(
        json.dumps(
            {
                "verified": True,
                "diff_sha": "d" * 40,
                "tokens_used": 12345,
                "wall_seconds": 42.5,
                "iterations": 2,
                "verifier_final_exit": 0,
                "receipt_hash": "abc123def456",
                "git_tree_sha": "tree9876",
            }
        ),
        encoding="utf-8",
    )
    swarm_dir = sample_repo / ".onmc" / "swarm" / "sw1"
    swarm_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "swarm_id": "sw1",
        "units": {
            "unit-0000": {
                "goal": "build alpha",
                "status": "done",
                "verified": True,
                "cost_usd": 0.5,
                "receipt_path": str(receipt_path),
            }
        },
    }
    (swarm_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    swarms = build_dashboard_payload(service)["swarms"]
    unit = swarms["swarms"][0]["units"][0]
    assert unit["tokens"] == 12345
    assert unit["wall_seconds"] == 42.5
    assert unit["verifier_exit"] == 0
    assert unit["receipt_hash"] == "abc123def456"


def test_dashboard_html_contains_agent_wall(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The dashboard ships the fullscreen Agent Wall monitor mode."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        _, _, html = _get(port, "/")
        _, _, js = _get(port, "/assets/app.js")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert 'id="wall"' in html
    assert 'id="wall-open"' in html
    assert "renderWall" in js


def test_dashboard_html_contains_command_palette(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The dashboard ships a command palette (cmdk) for fuzzy navigation."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        _, _, html = _get(port, "/")
        _, _, js = _get(port, "/assets/app.js")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert 'id="cmdk-input"' in html
    assert "openCmdk" in js
    assert "commandItems" in js


def test_dashboard_ships_verify_celebration(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """A newly-verified agent triggers a celebration toast + flash."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        _, _, js = _get(port, "/assets/app.js")
        _, _, css = _get(port, "/assets/styles.css")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert "celebrateVerifications" in js
    assert "seenVerified" in js
    assert "body.celebrate" in css


def test_dashboard_html_contains_activity_feed(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Overview ships a live activity feed of agent events."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        _, _, html = _get(port, "/")
        _, _, js = _get(port, "/assets/app.js")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert 'id="activity-feed"' in html
    assert "renderActivity" in js
    assert "timeAgo" in js


def test_dashboard_html_contains_overview_live_home(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """Overview surfaces a live-agents home strip that jumps to Swarms."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        _, _, html = _get(port, "/")
        _, _, js = _get(port, "/assets/app.js")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert 'id="live-home-panel"' in html
    assert "renderHomeLive" in js


def test_dashboard_html_contains_theme_toggle_and_shortcuts(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The dashboard ships dark-mode toggle + keyboard shortcuts."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        _, _, html = _get(port, "/")
        _, _, js = _get(port, "/assets/app.js")
        _, _, css = _get(port, "/assets/styles.css")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert 'id="theme-toggle"' in html
    assert "applyTheme" in js
    assert "SHORTCUT_VIEWS" in js
    assert "body.theme-dark" in css


def test_dashboard_html_contains_agent_drilldown_and_live_controls(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The dashboard ships the unit drawer, live toggle, and swarm filter."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        _, _, html = _get(port, "/")
        _, _, js = _get(port, "/assets/app.js")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert 'id="unit-drawer"' in html
    assert 'id="autorefresh-toggle"' in html
    assert 'data-swarm-filter="live"' in html
    assert "openUnitDrawer" in js
    assert "renderLiveStatus" in js


def test_dashboard_html_contains_swarms_view(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The dashboard exposes the Swarms (live agents) view + auto-refresh."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        _, _, html = _get(port, "/")
        _, _, js = _get(port, "/assets/app.js")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert 'id="view-swarms"' in html
    assert 'data-view="swarms"' in html
    assert "refreshSilently" in js


def test_dashboard_html_contains_mission_control_view(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    """The dashboard exposes the Mission Control view + the KNOW/ACT/PROVE/LEARN loop."""
    service = _ready_service(sample_repo, monkeypatch)
    server = create_ui_server(service, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    try:
        _, _, html = _get(port, "/")
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert 'id="view-mission"' in html
    for label in ("KNOW", "ACT", "PROVE", "LEARN"):
        assert label in html


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
