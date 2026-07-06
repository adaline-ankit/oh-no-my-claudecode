"""Tests for the ``onmc prbadge`` verified-work PR-comment badge feature.

Covers the pure surface:
- zero-state (no receipts) renders an honest "no data" / "no verified
  receipts yet" badge — never a fabricated percentage
- verified-rate math (verified_count / run_count) and colour thresholds
- render_markdown cites the run count, verified percentage, and onmc version
- the CLI ``--dry-run`` and ``--json`` paths build/print the badge without
  ever invoking ``gh``
- the shields.io URL uses a ``/badge/`` path segment (never asserted via a
  bare host substring, to avoid the incomplete-URL-substring-sanitization
  CodeQL pattern)

Never invokes ``gh`` — only ``--dry-run``/``--json`` paths are exercised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.command_registry import detect_duplicate_commands
from oh_no_my_claudecode.ledger.accounting import summarize_receipts
from oh_no_my_claudecode.prbadge.prbadge import (
    build_badge,
    build_badge_from_receipts,
    render_markdown,
)

runner = CliRunner()

_VERSION = "0.86.0"


def _receipt(*, verified: bool) -> dict[str, Any]:
    """A minimal receipt dict matching the real RunReceipt key names."""
    return {"schema_version": "2", "verified": verified, "wall_seconds": 12.0}


def _write_receipt(dir_path: Path, name: str, receipt: dict[str, Any]) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / name
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# build_badge / build_badge_from_receipts — pure
# ---------------------------------------------------------------------------


def test_zero_state_has_no_fabricated_percentage() -> None:
    content = build_badge_from_receipts([], onmc_version=_VERSION)
    assert content.run_count == 0
    assert content.verified_count == 0
    assert content.verified_pct is None
    assert content.onmc_version == _VERSION


def test_all_verified_gives_100_percent() -> None:
    receipts = [_receipt(verified=True), _receipt(verified=True)]
    content = build_badge_from_receipts(receipts, onmc_version=_VERSION)
    assert content.run_count == 2
    assert content.verified_count == 2
    assert content.verified_pct == 100.0


def test_mixed_verified_computes_correct_percentage() -> None:
    receipts = [_receipt(verified=True), _receipt(verified=False), _receipt(verified=False)]
    content = build_badge_from_receipts(receipts, onmc_version=_VERSION)
    assert content.run_count == 3
    assert content.verified_count == 1
    assert content.verified_pct == pytest.approx(33.3, abs=0.1)


def test_build_badge_from_summary_matches_receipts_path() -> None:
    receipts = [_receipt(verified=True), _receipt(verified=False)]
    summary = summarize_receipts(receipts, scope="project")
    via_summary = build_badge(summary, onmc_version=_VERSION)
    via_receipts = build_badge_from_receipts(receipts, onmc_version=_VERSION)
    assert via_summary == via_receipts


def test_shields_url_uses_badge_path_segment_not_bare_host() -> None:
    content = build_badge_from_receipts([_receipt(verified=True)], onmc_version=_VERSION)
    # Assert on the /badge/ path segment, not a bare "img.shields.io" host
    # substring (that pattern trips CodeQL's incomplete-url-substring check).
    assert "/badge/" in content.shields_url
    assert content.shields_url.startswith("https://img.shields.io/badge/")


def test_low_verified_rate_uses_red_high_uses_brightgreen() -> None:
    low = build_badge_from_receipts(
        [_receipt(verified=False) for _ in range(5)], onmc_version=_VERSION
    )
    high = build_badge_from_receipts(
        [_receipt(verified=True) for _ in range(5)], onmc_version=_VERSION
    )
    assert "red" in low.shields_url
    assert "brightgreen" in high.shields_url


# ---------------------------------------------------------------------------
# render_markdown — pure
# ---------------------------------------------------------------------------


def test_render_markdown_zero_state_is_honest() -> None:
    content = build_badge_from_receipts([], onmc_version=_VERSION)
    md = render_markdown(content)
    assert "no verified receipts yet" in md.lower() or "no onmc-verified" in md.lower()
    # No fabricated verified-percentage anywhere in the headline text.
    assert "% verified" not in md
    assert _VERSION in md


def test_render_markdown_cites_counts_and_version() -> None:
    receipts = [_receipt(verified=True), _receipt(verified=True), _receipt(verified=False)]
    content = build_badge_from_receipts(receipts, onmc_version=_VERSION)
    md = render_markdown(content)
    assert "3" in md
    assert "2/3" in md
    assert _VERSION in md
    assert md.startswith("![")


# ---------------------------------------------------------------------------
# CLI wiring — dry-run / json only, never invokes gh
# ---------------------------------------------------------------------------


def test_prbadge_registered_and_no_duplicates() -> None:
    assert detect_duplicate_commands(app) == []
    result = runner.invoke(app, ["prbadge", "--help"])
    assert result.exit_code == 0


def test_prbadge_dry_run_zero_state(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["prbadge", "1", "--dry-run"])
    assert result.exit_code == 0
    out = result.stdout.lower()
    assert "no verified receipts yet" in out or "no onmc-verified" in out


def test_prbadge_dry_run_with_receipts(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-0.json", _receipt(verified=True))
    _write_receipt(receipts_dir, "run-1.json", _receipt(verified=True))

    result = runner.invoke(app, ["prbadge", "1", "--dry-run"])
    assert result.exit_code == 0
    assert "2" in result.stdout
    assert "100" in result.stdout


def test_prbadge_json_implies_dry_run_and_never_posts(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "oh_no_my_claudecode.prbadge.commands.subprocess.run",
        lambda argv, **kw: calls.append(argv) or pytest.fail("gh must not be invoked with --json"),
    )
    result = runner.invoke(app, ["prbadge", "42", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["run_count"] == 0
    assert payload["verified_pct"] is None
    assert calls == []


def test_prbadge_json_structure(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    receipts_dir = tmp_path / ".agent-memory" / "receipts"
    _write_receipt(receipts_dir, "run-0.json", _receipt(verified=True))

    result = runner.invoke(app, ["prbadge", "7", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "run_count": 1,
        "verified_count": 1,
        "verified_pct": 100.0,
        "onmc_version": payload["onmc_version"],
        "shields_url": payload["shields_url"],
        "note": payload["note"],
    }
    assert "/badge/" in payload["shields_url"]


def test_prbadge_dry_run_never_invokes_gh(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    def _fail_if_called(argv: list[str], **kwargs: Any) -> None:
        pytest.fail(f"gh must not be invoked in --dry-run mode, got: {argv}")

    monkeypatch.setattr(
        "oh_no_my_claudecode.prbadge.commands.subprocess.run", _fail_if_called
    )
    result = runner.invoke(app, ["prbadge", "9", "--dry-run"])
    assert result.exit_code == 0
