from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.fleet import fleet_doctor, fleet_status

runner = CliRunner()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_fleet_status_summarizes_swarms_claims_and_receipts(tmp_path: Path) -> None:
    _write_json(
        tmp_path / ".onmc" / "swarm" / "abc123" / "manifest.json",
        {
            "swarm_id": "abc123",
            "agent": "codex",
            "started_at": "2026-06-27T00:00:00+00:00",
            "stop_reason": "complete",
            "units": {
                "unit-0000": {"status": "done"},
                "unit-0001": {"status": "failed"},
            },
        },
    )
    _write_json(
        tmp_path / ".onmc" / "claims.json",
        {
            "claims": [
                {
                    "owner": "agent-a",
                    "path": "src/a.py",
                    "acquired_at": 10.0,
                    "expires_at": 9_999_999_999.0,
                }
            ]
        },
    )
    _write_json(
        tmp_path / ".agent-memory" / "receipts" / "run-one.json",
        {
            "agent": "codex",
            "model": "gpt",
            "verified": True,
            "cost_usd": 0.25,
            "wall_seconds": 5.0,
            "ended_at": "2026-06-27T00:01:00+00:00",
        },
    )

    status = fleet_status(tmp_path)

    assert len(status.swarms) == 1
    assert status.swarms[0].counts.done == 1
    assert status.swarms[0].counts.failed == 1
    assert status.active_claims == 1
    assert status.receipt_count == 1
    assert status.ledger is not None
    assert status.ledger.cost_label == "$0.2500"


def test_fleet_doctor_flags_stale_claim(tmp_path: Path) -> None:
    _write_json(
        tmp_path / ".onmc" / "claims.json",
        {
            "claims": [
                {
                    "owner": "agent-a",
                    "path": "src/a.py",
                    "acquired_at": 0.0,
                    "expires_at": 30_000.0,
                }
            ]
        },
    )

    report = fleet_doctor(tmp_path, now=20_000.0, stale_claim_seconds=10)

    assert report.ok is False
    assert report.issues[0].title == "stale active claim"


def test_fleet_cli_json(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    _write_json(
        tmp_path / ".onmc" / "swarm" / "abc123" / "manifest.json",
        {"swarm_id": "abc123", "agent": "codex", "units": {"u": {"status": "done"}}},
    )

    result = runner.invoke(app, ["fleet", "status", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["swarms"][0]["swarm_id"] == "abc123"


def test_fleet_doctor_cli_exits_nonzero_on_issue(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    _write_json(
        tmp_path / ".onmc" / "claims.json",
        {
            "claims": [
                {
                    "owner": "a",
                    "path": "x",
                    "acquired_at": 0.0,
                    "expires_at": 9_999_999_999.0,
                }
            ]
        },
    )

    result = runner.invoke(app, ["fleet", "doctor"])

    assert result.exit_code == 1
