"""Tests for the ``onmc share`` gist-publishing feature.

Covers the pure surface:
- ``snapshot_filename`` produces a deterministic, timestamped name per kind
- ``gist_description`` includes the repo name when known
Plus the CLI's ``--dry-run``/``--json`` paths for both content modes (dashboard
and ``--scorecard``), asserting the snapshot file is produced and ``gh`` is
never invoked. Publishing (``gh gist create``) is exercised with a
monkeypatched ``subprocess.run`` so no real network/gh call happens.

No bare-URL-host substring asserts (CodeQL incomplete-url-substring-sanitization
pattern) and no assertions on Rich/Typer ``--help`` text.
"""

from __future__ import annotations

import json
import subprocess as _real_subprocess_module
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.command_registry import detect_duplicate_commands
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.share.share import ShareKind, gist_description, snapshot_filename

runner = CliRunner()

# Captured before any monkeypatching so fakes can delegate non-gh calls (e.g.
# the `git rev-parse` repo-discovery call) to the real subprocess.run without
# recursing into themselves.
_REAL_RUN = _real_subprocess_module.run


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_snapshot_filename_dashboard_uses_html_extension() -> None:
    now = datetime(2026, 7, 6, 12, 30, 45, tzinfo=UTC)
    name = snapshot_filename(ShareKind.DASHBOARD, now=now)
    assert name == "onmc-dashboard-20260706T123045Z.html"


def test_snapshot_filename_scorecard_uses_markdown_extension() -> None:
    now = datetime(2026, 7, 6, 12, 30, 45, tzinfo=UTC)
    name = snapshot_filename(ShareKind.SCORECARD, now=now)
    assert name == "onmc-scorecard-20260706T123045Z.md"


def test_snapshot_filename_is_deterministic_for_same_instant() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert snapshot_filename(ShareKind.DASHBOARD, now=now) == snapshot_filename(
        ShareKind.DASHBOARD, now=now
    )


def test_snapshot_filename_normalizes_non_utc_to_utc() -> None:
    from datetime import timedelta, timezone

    tz = timezone(timedelta(hours=5))
    local = datetime(2026, 7, 6, 17, 30, 45, tzinfo=tz)
    utc = datetime(2026, 7, 6, 12, 30, 45, tzinfo=UTC)
    assert snapshot_filename(ShareKind.DASHBOARD, now=local) == snapshot_filename(
        ShareKind.DASHBOARD, now=utc
    )


def test_gist_description_without_repo_name() -> None:
    desc = gist_description(ShareKind.DASHBOARD)
    assert desc == "onmc dashboard snapshot"


def test_gist_description_with_repo_name() -> None:
    desc = gist_description(ShareKind.SCORECARD, repo_name="acme/widgets")
    assert "acme/widgets" in desc
    assert "scorecard" in desc


def test_gist_description_kinds_differ() -> None:
    dashboard = gist_description(ShareKind.DASHBOARD, repo_name="acme/widgets")
    scorecard = gist_description(ShareKind.SCORECARD, repo_name="acme/widgets")
    assert dashboard != scorecard


# ---------------------------------------------------------------------------
# CLI: no duplicate command registration
# ---------------------------------------------------------------------------


def test_share_command_registered_without_collision() -> None:
    assert detect_duplicate_commands(app) == []


# ---------------------------------------------------------------------------
# CLI: --dry-run / --json never invoke gh
# ---------------------------------------------------------------------------


def _fail_if_gh_called(argv: list[str], **kwargs: Any) -> Any:
    """Fail only on ``gh`` invocations; let ``git`` calls (repo discovery) pass through."""
    if argv and argv[0] == "gh":
        pytest.fail(f"gh must not be invoked, got: {argv}")
    return _REAL_RUN(argv, **kwargs)


def test_share_scorecard_dry_run_writes_file_and_skips_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.share.commands.subprocess.run", _fail_if_gh_called
    )

    result = runner.invoke(app, ["share", "--scorecard", "--dry-run"])

    assert result.exit_code == 0
    assert "Snapshot written" in result.output
    # Extract the printed path and confirm it exists with markdown content.
    written = Path(result.output.split("Snapshot written:")[1].strip().splitlines()[0])
    assert written.exists()
    assert written.suffix == ".md"


def test_share_scorecard_json_implies_dry_run_and_never_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "oh_no_my_claudecode.share.commands.subprocess.run", _fail_if_gh_called
    )

    result = runner.invoke(app, ["share", "--scorecard", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["kind"] == "scorecard"
    assert payload["published"] is False
    assert Path(payload["path"]).exists()


def test_share_dashboard_dry_run_uses_existing_exporter(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default (no --scorecard) path reuses export_dashboard_snapshot."""
    monkeypatch.chdir(sample_repo)
    OnmcService(sample_repo).init_project()
    calls: list[Path] = []

    def fake_export(service: OnmcService, destination: Path) -> Path:
        calls.append(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("<html>snapshot</html>", encoding="utf-8")
        return destination

    monkeypatch.setattr(
        "oh_no_my_claudecode.share.commands.export_dashboard_snapshot", fake_export
    )
    monkeypatch.setattr(
        "oh_no_my_claudecode.share.commands.subprocess.run", _fail_if_gh_called
    )

    result = runner.invoke(app, ["share", "--dry-run"])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0].suffix == ".html"


def test_share_dashboard_without_init_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dashboard mode requires an initialised onmc repo, same as `onmc ui`."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["share", "--dry-run"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# CLI: publishing invokes gh gist create with the right flags
# ---------------------------------------------------------------------------


def _fake_run_factory(gist_stdout: str) -> tuple[list[list[str]], Any]:
    """A ``subprocess.run`` stand-in that fakes ``gh`` calls, real-runs others."""
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> Any:
        if argv and argv[0] == "gh":
            calls.append(argv)

            class _Result:
                returncode = 0
                stdout = gist_stdout
                stderr = ""

            return _Result()
        return _REAL_RUN(argv, **kwargs)

    return calls, fake_run


def test_share_scorecard_publish_invokes_gh_public_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    calls, fake_run = _fake_run_factory("https://gist.example/abc123\n")
    monkeypatch.setattr("oh_no_my_claudecode.share.commands.subprocess.run", fake_run)

    result = runner.invoke(app, ["share", "--scorecard"])

    assert result.exit_code == 0
    gist_calls = [c for c in calls if c[:3] == ["gh", "gist", "create"]]
    assert len(gist_calls) == 1
    argv = gist_calls[0]
    assert "--public" in argv
    assert "--secret" not in argv
    assert "Published public gist" in result.output


def test_share_scorecard_publish_private_uses_secret_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    calls, fake_run = _fake_run_factory("https://gist.example/private123\n")
    monkeypatch.setattr("oh_no_my_claudecode.share.commands.subprocess.run", fake_run)

    result = runner.invoke(app, ["share", "--scorecard", "--private"])

    assert result.exit_code == 0
    gist_calls = [c for c in calls if c[:3] == ["gh", "gist", "create"]]
    argv = gist_calls[0]
    assert "--secret" in argv
    assert "--public" not in argv
    assert "Published secret gist" in result.output


def test_share_publish_failure_reports_gh_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def fake_run(argv: list[str], **kwargs: Any) -> Any:
        if argv and argv[0] == "gh" and argv[1] == "gist":

            class _Result:
                returncode = 1
                stdout = ""
                stderr = "gh: not authenticated"

            return _Result()
        return _REAL_RUN(argv, **kwargs)

    monkeypatch.setattr("oh_no_my_claudecode.share.commands.subprocess.run", fake_run)

    result = runner.invoke(app, ["share", "--scorecard"])

    assert result.exit_code != 0
    assert "not authenticated" in result.output
