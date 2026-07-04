"""Tests for the ``onmc badge`` proof-of-work badge feature.

Covers the pure surface:
- verified receipt → Markdown badge says "verified" and is green (brightgreen)
- verified endpoint payload → schemaVersion 1, message "verified", color brightgreen
- unverified receipt → "unverified" + red across badge and endpoint
- comment_body cites the goal, diff_sha, and receipt_hash and leads with the badge
- load_receipt resolves an explicit path, resolves via a swarm manifest (with and
  without --unit), and returns None on every missing/malformed input
- the command exits 1 on a missing receipt and no-flag output includes the badge

Never invokes ``gh`` — the ``--post`` path is not exercised; only ``comment_body``
strings are asserted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from oh_no_my_claudecode.badge.badge import (
    comment_body,
    endpoint_payload,
    load_receipt,
    render_markdown_badge,
)
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.command_registry import detect_duplicate_commands

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_GOAL = "Build onmc badge feature"
_TREE = "6c4449d07b06bbca12f0c3f1b98702cb9e1ffd21"
_DIFF = "db42d68b79991a9c946d1b47b58320edbf3755b71139d6f5a67ada6176ddab9a"
_HASH = "7697db6512adb8c7186a68dc7c25d34efb4d773389ebd4f0aac63dbf349583bc"


def _receipt(*, verified: bool) -> dict[str, Any]:
    """A minimal receipt dict matching the real RunReceipt key names."""
    return {
        "schema_version": "2",
        "goal": _GOAL,
        "verified": verified,
        "git_tree_sha": _TREE,
        "diff_sha": _DIFF,
        "receipt_hash": _HASH,
    }


def _write_receipt(dir_path: Path, name: str, receipt: dict[str, Any]) -> Path:
    """Write *receipt* as JSON under *dir_path* and return its path."""
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / name
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# render_markdown_badge
# ---------------------------------------------------------------------------


def test_verified_markdown_badge_is_green() -> None:
    md = render_markdown_badge(_receipt(verified=True))
    assert "verified" in md
    assert "unverified" not in md
    assert "brightgreen" in md
    assert md.startswith("![")


def test_unverified_markdown_badge_is_red() -> None:
    md = render_markdown_badge(_receipt(verified=False))
    assert "unverified" in md
    assert "brightgreen" not in md
    assert "-red" in md or "red" in md


def test_markdown_badge_missing_verified_treated_unverified() -> None:
    # A receipt with no `verified` key must not crash and must read as unverified.
    md = render_markdown_badge({"goal": _GOAL})
    assert "unverified" in md


# ---------------------------------------------------------------------------
# endpoint_payload
# ---------------------------------------------------------------------------


def test_verified_endpoint_payload() -> None:
    payload = endpoint_payload(_receipt(verified=True))
    assert payload == {
        "schemaVersion": 1,
        "label": "onmc",
        "message": "verified",
        "color": "brightgreen",
    }


def test_unverified_endpoint_payload() -> None:
    payload = endpoint_payload(_receipt(verified=False))
    assert payload["message"] == "unverified"
    assert payload["color"] == "red"
    assert payload["schemaVersion"] == 1


# ---------------------------------------------------------------------------
# comment_body
# ---------------------------------------------------------------------------


def test_comment_body_cites_hashes_and_goal_verified() -> None:
    body = comment_body(_receipt(verified=True))
    # leads with the badge
    assert body.startswith("![")
    assert "brightgreen" in body
    # cites goal + short hashes
    assert _GOAL in body
    assert _DIFF[:12] in body
    assert _HASH[:12] in body
    assert _TREE[:12] in body
    # tamper-evidence-forward wording
    assert "verified" in body.lower()
    assert "tamper" in body.lower()


def test_comment_body_unverified_language() -> None:
    body = comment_body(_receipt(verified=False))
    assert "not verified" in body.lower()
    assert "red" in body  # badge color present


def test_comment_body_missing_fields_are_graceful() -> None:
    body = comment_body({"verified": True})
    assert "unknown" in body  # missing hashes surfaced, not crashed
    assert "(no goal recorded)" in body


# ---------------------------------------------------------------------------
# load_receipt
# ---------------------------------------------------------------------------


def test_load_receipt_by_explicit_path(tmp_path: Path) -> None:
    path = _write_receipt(tmp_path, "run-abc.json", _receipt(verified=True))
    loaded = load_receipt(str(path))
    assert loaded is not None
    assert loaded["goal"] == _GOAL
    assert loaded["verified"] is True


def test_load_receipt_by_swarm_id_first_unit(tmp_path: Path) -> None:
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    rp = _write_receipt(receipts_dir, "run-x.json", _receipt(verified=True))
    swarm_dir = tmp_path / ".onmc" / "swarm" / "swarm123"
    swarm_dir.mkdir(parents=True)
    manifest = {
        "swarm_id": "swarm123",
        "units": {
            "unit-0000": {"receipt_path": str(rp), "verified": True},
        },
    }
    (swarm_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    loaded = load_receipt("swarm123", repo_root=tmp_path)
    assert loaded is not None
    assert loaded["git_tree_sha"] == _TREE


def test_load_receipt_by_swarm_id_specific_unit(tmp_path: Path) -> None:
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    rp0 = _write_receipt(receipts_dir, "run-0.json", _receipt(verified=False))
    rp1 = _write_receipt(receipts_dir, "run-1.json", _receipt(verified=True))
    swarm_dir = tmp_path / ".onmc" / "swarm" / "s"
    swarm_dir.mkdir(parents=True)
    manifest = {
        "units": {
            "unit-0000": {"receipt_path": str(rp0)},
            "unit-0001": {"receipt_path": str(rp1)},
        },
    }
    (swarm_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    loaded = load_receipt("s", unit_id="unit-0001", repo_root=tmp_path)
    assert loaded is not None
    assert loaded["verified"] is True


def test_load_receipt_missing_path_returns_none(tmp_path: Path) -> None:
    assert load_receipt(str(tmp_path / "nope.json")) is None


def test_load_receipt_missing_swarm_returns_none(tmp_path: Path) -> None:
    assert load_receipt("does-not-exist", repo_root=tmp_path) is None


def test_load_receipt_unknown_unit_returns_none(tmp_path: Path) -> None:
    swarm_dir = tmp_path / ".onmc" / "swarm" / "s"
    swarm_dir.mkdir(parents=True)
    (swarm_dir / "manifest.json").write_text(
        json.dumps({"units": {"unit-0000": {"receipt_path": "/x.json"}}}),
        encoding="utf-8",
    )
    assert load_receipt("s", unit_id="unit-9999", repo_root=tmp_path) is None


def test_load_receipt_malformed_json_returns_none(tmp_path: Path) -> None:
    bad = tmp_path / "run-bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_receipt(str(bad)) is None


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------


def test_badge_registered_and_no_duplicates() -> None:
    assert detect_duplicate_commands(app) == []
    result = runner.invoke(app, ["badge", "--help"])
    assert result.exit_code == 0
    assert "badge" in result.stdout.lower()


def test_badge_command_missing_receipt_exits_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["badge", str(tmp_path / "missing.json")])
    assert result.exit_code == 1


def test_badge_command_prints_badge_and_body(tmp_path: Path) -> None:
    path = _write_receipt(tmp_path, "run-ok.json", _receipt(verified=True))
    result = runner.invoke(app, ["badge", str(path)])
    assert result.exit_code == 0
    assert "![" in result.stdout
    assert _GOAL in result.stdout


def test_badge_command_json_emits_endpoint_payload(tmp_path: Path) -> None:
    path = _write_receipt(tmp_path, "run-ok.json", _receipt(verified=True))
    result = runner.invoke(app, ["badge", str(path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schemaVersion"] == 1
    assert payload["message"] == "verified"


def test_badge_command_resolves_swarm_id_and_unit(tmp_path: Path, monkeypatch: Any) -> None:
    # End-to-end CLI: `onmc badge <swarm_id> --unit <unit>` resolves the receipt
    # via the manifest from cwd (Sourcery testing suggestion).
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    rp0 = _write_receipt(receipts_dir, "run-0.json", _receipt(verified=False))
    rp1 = _write_receipt(receipts_dir, "run-1.json", _receipt(verified=True))
    swarm_dir = tmp_path / ".onmc" / "swarm" / "swarmZ"
    swarm_dir.mkdir(parents=True)
    manifest = {
        "units": {
            "unit-0000": {"receipt_path": str(rp0)},
            "unit-0001": {"receipt_path": str(rp1)},
        },
    }
    (swarm_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["badge", "swarmZ", "--unit", "unit-0001", "--json"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["message"] == "verified"
