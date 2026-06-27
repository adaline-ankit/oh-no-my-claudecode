from __future__ import annotations

import json
import os
from pathlib import Path

from pytest import MonkeyPatch
from typer.testing import CliRunner

from oh_no_my_claudecode.claim import ClaimLedger
from oh_no_my_claudecode.cli import app

runner = CliRunner()


def _git_repo(path: Path) -> None:
    (path / ".git").mkdir()


def _claims(path: Path) -> dict[str, object]:
    return json.loads((path / ".onmc" / "claims.json").read_text(encoding="utf-8"))


def test_acquire_writes_claims_atomically_with_ttl(tmp_path: Path) -> None:
    _git_repo(tmp_path)
    ledger = ClaimLedger(tmp_path, clock=lambda: 100.0)

    result = ledger.acquire("agent-a", ["src/app.py"], ttl_seconds=30)

    assert result.ok is True
    assert _claims(tmp_path) == {
        "version": 1,
        "claims": [
            {
                "owner": "agent-a",
                "path": "src/app.py",
                "acquired_at": 100.0,
                "expires_at": 130.0,
            }
        ],
    }


def test_active_conflict_blocks_different_owner(tmp_path: Path) -> None:
    ledger = ClaimLedger(tmp_path, clock=lambda: 100.0)
    ledger.acquire("agent-a", ["src/app.py"], ttl_seconds=30)

    result = ledger.acquire("agent-b", ["src/app.py"], ttl_seconds=30)

    assert result.ok is False
    assert len(result.conflicts) == 1
    assert result.conflicts[0].owner == "agent-a"
    assert result.conflicts[0].path == "src/app.py"


def test_expired_claim_does_not_block_and_is_pruned(tmp_path: Path) -> None:
    now = 100.0
    ledger = ClaimLedger(tmp_path, clock=lambda: now)
    ledger.acquire("agent-a", ["src/app.py"], ttl_seconds=10)

    now = 111.0
    result = ledger.acquire("agent-b", ["src/app.py"], ttl_seconds=10)

    assert result.ok is True
    assert [claim.owner for claim in ledger.status().claims] == ["agent-b"]


def test_release_can_remove_all_owner_claims_or_one_path(tmp_path: Path) -> None:
    ledger = ClaimLedger(tmp_path, clock=lambda: 100.0)
    ledger.acquire("agent-a", ["src/app.py", "tests/test_app.py"], ttl_seconds=60)
    ledger.acquire("agent-b", ["README.md"], ttl_seconds=60)

    one = ledger.release("agent-a", path="src/app.py")
    assert one.released == 1
    assert sorted(claim.path for claim in ledger.status().claims) == [
        "README.md",
        "tests/test_app.py",
    ]

    rest = ledger.release("agent-a")
    assert rest.released == 1
    assert [claim.path for claim in ledger.status().claims] == ["README.md"]


def test_check_reports_conflicts_except_for_same_owner(tmp_path: Path) -> None:
    ledger = ClaimLedger(tmp_path, clock=lambda: 100.0)
    ledger.acquire("agent-a", ["src/app.py"], ttl_seconds=60)

    blocked = ledger.check(["src/app.py"], owner="agent-b")
    allowed = ledger.check(["src/app.py"], owner="agent-a")

    assert blocked.ok is False
    assert blocked.conflicts[0].owner == "agent-a"
    assert allowed.ok is True


def test_claim_lock_is_cleaned_after_write(tmp_path: Path) -> None:
    ledger = ClaimLedger(tmp_path, clock=lambda: 100.0)

    ledger.acquire("agent-a", ["src/app.py"], ttl_seconds=60)

    assert not (tmp_path / ".onmc" / "claims.lock").exists()


def test_stale_claim_lock_is_recovered(tmp_path: Path) -> None:
    lock = tmp_path / ".onmc" / "claims.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("dead\n", encoding="utf-8")
    os.utime(lock, (1, 1))
    ledger = ClaimLedger(tmp_path, clock=lambda: 100.0)

    result = ledger.acquire("agent-a", ["src/app.py"], ttl_seconds=60)

    assert result.ok is True
    assert not lock.exists()


def test_cli_acquire_conflict_exits_nonzero_with_owner_and_path(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["claim", "acquire", "agent-a", "src/app.py"])
    second = runner.invoke(app, ["claim", "acquire", "agent-b", "src/app.py"])

    assert first.exit_code == 0
    assert second.exit_code != 0
    assert "agent-a" in second.output
    assert "src/app.py" in second.output


def test_cli_json_status_and_check(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["claim", "acquire", "agent-a", "src/app.py", "--json"])

    status = runner.invoke(app, ["claim", "status", "--json"])
    check = runner.invoke(
        app,
        ["claim", "check", "src/app.py", "--owner", "agent-b", "--json"],
    )

    status_payload = json.loads(status.output)
    check_payload = json.loads(check.output)
    assert status.exit_code == 0
    assert status_payload["claims"][0]["owner"] == "agent-a"
    assert check.exit_code != 0
    assert check_payload["conflicts"][0]["path"] == "src/app.py"
