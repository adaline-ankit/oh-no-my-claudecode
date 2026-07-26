"""Tests for the ``onmc missioncontrol`` live swarm dashboard (read-only)."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.durable_runtime import RuntimeStore
from oh_no_my_claudecode.missioncontrol import (
    build_dashboard,
    list_swarm_ids,
    render_dashboard,
    render_swarm_list,
)

runner = CliRunner()


def _console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, force_terminal=False, width=200), buf


def _make_swarm(
    repo: Path,
    swarm_id: str,
    *,
    units: dict,
    aborted: bool = False,
    receipts: dict | None = None,
) -> Path:
    """Create a fake ``.onmc/swarm/<id>`` with a manifest (+ optional receipts).

    ``receipts`` maps a filename to a receipt dict written under
    ``.agent-memory/receipts/``; unit ``receipt_path`` values should point at
    those files (repo-relative).
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
    if aborted:
        (swarm_dir / "ABORT").write_text("abort", encoding="utf-8")
    if receipts:
        rdir = repo / ".agent-memory" / "receipts"
        rdir.mkdir(parents=True, exist_ok=True)
        for name, body in receipts.items():
            (rdir / name).write_text(json.dumps(body), encoding="utf-8")
    return repo / ".onmc" / "swarm"


def test_missioncontrol_cli_defaults_to_canonical_runtime(
    sample_repo: Path, monkeypatch: object
) -> None:
    monkeypatch.chdir(sample_repo)
    store = RuntimeStore(sample_repo / ".onmc" / "harness-runtime")
    store.create_run(
        "run-ui",
        node_ids=("prepare", "execute"),
        repo=sample_repo,
        idempotency_key="create",
    )
    store.start("run-ui", idempotency_key="start")
    store.start_node("run-ui", "prepare", idempotency_key="prepare")

    result = runner.invoke(app, ["missioncontrol", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["runs"] == 1
    assert payload["summary"]["active"] == 1
    assert payload["runs"][0]["run_id"] == "run-ui"
    assert payload["runs"][0]["proof_state"] == "pending"


def test_build_dashboard_reflects_unit_states_and_verified(tmp_path: Path) -> None:
    units = {
        "unit-0000": {
            "goal": "build feature A",
            "status": "done",
            "verified": True,
            "cost_usd": 0.5,
            "receipt_path": ".agent-memory/receipts/run-a.json",
            "error": None,
        },
        "unit-0001": {
            "goal": "build feature B",
            "status": "failed",
            "verified": False,
            "cost_usd": 0.2,
            "receipt_path": None,
            "error": "subagent did not verify",
        },
        "unit-0002": {
            "goal": "build feature C",
            "status": "running",
            "verified": None,
            "cost_usd": 0.0,
            "receipt_path": None,
            "error": None,
        },
    }
    base = _make_swarm(
        tmp_path,
        "abc123",
        units=units,
        receipts={"run-a.json": {"verified": True, "diff_sha": "deadbeefcafe0001"}},
    )

    model = build_dashboard(base, "abc123")

    assert model.exists is True
    assert model.total == 3
    assert model.verified_count == 1
    assert model.aborted is False

    by_id = {u.unit_id: u for u in model.units}
    assert by_id["unit-0000"].state == "done"
    assert by_id["unit-0000"].verified is True
    assert by_id["unit-0000"].has_receipt is True
    assert by_id["unit-0000"].diff_sha == "deadbeefcafe0001"

    assert by_id["unit-0001"].state == "failed"
    assert by_id["unit-0001"].verified is False
    assert by_id["unit-0001"].has_receipt is False
    assert by_id["unit-0001"].error == "subagent did not verify"

    assert by_id["unit-0002"].state == "running"
    assert by_id["unit-0002"].verified is None

    counts = model.state_counts
    assert counts["done"] == 1
    assert counts["failed"] == 1
    assert counts["running"] == 1


def test_build_dashboard_reflects_abort_sentinel(tmp_path: Path) -> None:
    base = _make_swarm(
        tmp_path,
        "aborted1",
        units={
            "unit-0000": {"goal": "g", "status": "aborted", "verified": None},
        },
        aborted=True,
    )
    model = build_dashboard(base, "aborted1")
    assert model.aborted is True
    assert model.units[0].state == "aborted"


def test_missing_receipt_file_marks_has_receipt_false(tmp_path: Path) -> None:
    # Manifest points at a receipt that was never written to disk.
    base = _make_swarm(
        tmp_path,
        "noreceipt",
        units={
            "unit-0000": {
                "goal": "g",
                "status": "done",
                "verified": True,
                "receipt_path": ".agent-memory/receipts/run-missing.json",
            },
        },
    )
    model = build_dashboard(base, "noreceipt")
    assert model.units[0].has_receipt is False
    assert model.units[0].diff_sha is None


def test_build_dashboard_missing_manifest_is_graceful(tmp_path: Path) -> None:
    base = tmp_path / ".onmc" / "swarm"
    base.mkdir(parents=True, exist_ok=True)
    model = build_dashboard(base, "does-not-exist")
    assert model.exists is False
    assert model.units == []

    console, buf = _console()
    render_dashboard(model, console)
    out = buf.getvalue()
    assert "No swarm found" in out
    assert "does-not-exist" in out


def test_render_dashboard_contains_expected_strings(tmp_path: Path) -> None:
    base = _make_swarm(
        tmp_path,
        "render1",
        units={
            "unit-0000": {
                "goal": "implement the widget",
                "status": "done",
                "verified": True,
                "receipt_path": ".agent-memory/receipts/run-r.json",
            },
        },
        aborted=True,
        receipts={"run-r.json": {"verified": True, "diff_sha": "abcdef012345"}},
    )
    model = build_dashboard(base, "render1")
    console, buf = _console()
    render_dashboard(model, console)
    out = buf.getvalue()

    assert "Mission Control" in out
    assert "render1" in out
    assert "unit-0000" in out
    assert "done" in out
    assert "implement the widget" in out
    assert "abcdef012345" in out  # diff_sha (12-char truncation)
    assert "ABORT" in out  # abort sentinel surfaced


def test_list_swarm_ids_and_render(tmp_path: Path) -> None:
    _make_swarm(tmp_path, "sw-b", units={"unit-0000": {"goal": "b", "status": "pending"}})
    _make_swarm(tmp_path, "sw-a", units={"unit-0000": {"goal": "a", "status": "pending"}})
    base = tmp_path / ".onmc" / "swarm"
    # A directory without a manifest must be ignored.
    (base / "not-a-swarm").mkdir(parents=True, exist_ok=True)

    ids = list_swarm_ids(base)
    assert ids == ["sw-a", "sw-b"]  # sorted, manifest-only

    console, buf = _console()
    render_swarm_list(ids, console)
    out = buf.getvalue()
    assert "2 swarm(s)" in out
    assert "sw-a" in out
    assert "sw-b" in out


def test_list_swarm_ids_missing_base(tmp_path: Path) -> None:
    assert list_swarm_ids(tmp_path / ".onmc" / "swarm") == []
    console, buf = _console()
    render_swarm_list([], console)
    assert "No swarms found" in buf.getvalue()


def test_to_dict_is_json_serialisable(tmp_path: Path) -> None:
    base = _make_swarm(
        tmp_path,
        "jsonsw",
        units={"unit-0000": {"goal": "g", "status": "done", "verified": True}},
    )
    model = build_dashboard(base, "jsonsw")
    payload = model.to_dict()
    # Round-trips cleanly.
    assert json.loads(json.dumps(payload))["swarm_id"] == "jsonsw"
    assert payload["verified_count"] == 1
    assert payload["state_counts"]["done"] == 1


def test_non_numeric_cost_usd_does_not_break_build(tmp_path: Path) -> None:
    # A corrupt/future manifest with a non-numeric cost_usd must coerce to 0.0,
    # not raise (Sourcery bug_risk).
    base = _make_swarm(
        tmp_path,
        "badcost",
        units={"unit-0000": {"goal": "g", "status": "done", "cost_usd": "oops"}},
    )
    model = build_dashboard(base, "badcost")
    assert model.units[0].cost_usd == 0.0


def test_summary_surfaces_unknown_states(tmp_path: Path) -> None:
    # An unexpected lifecycle value must still appear in the rendered summary
    # rather than being silently dropped (Sourcery suggestion).
    base = _make_swarm(
        tmp_path,
        "weird",
        units={"unit-0000": {"goal": "g", "status": "quarantined"}},
    )
    model = build_dashboard(base, "weird")
    console, buf = _console()
    render_dashboard(model, console)
    assert "quarantined" in buf.getvalue()
