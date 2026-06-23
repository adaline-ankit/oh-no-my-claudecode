"""Tests for ``onmc gh-aw init`` command and the integrations.gh_aw module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.integrations.gh_aw import (
    _SENTINEL,
    GhAwInitResult,
    run_gh_aw_init,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKFLOW_NAMES = [
    ".github/workflows/onmc-issue-context.yml",
    ".github/workflows/onmc-pr-preflight.yml",
    ".github/workflows/onmc-pr-learn.yml",
    ".github/workflows/onmc-weekly-audit.yml",
]


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A bare directory that acts as the target repo (no git init needed)."""
    repo = tmp_path / "target-repo"
    repo.mkdir()
    return repo


# ---------------------------------------------------------------------------
# Unit tests for run_gh_aw_init
# ---------------------------------------------------------------------------


def test_init_writes_four_workflows(tmp_repo: Path) -> None:
    """run_gh_aw_init writes all four workflow files."""
    result = run_gh_aw_init(tmp_repo)

    assert isinstance(result, GhAwInitResult)
    assert not result.dry_run
    assert len(result.written) == 4
    assert result.skipped == []

    for rel_path in WORKFLOW_NAMES:
        dest = tmp_repo / rel_path
        assert dest.exists(), f"Expected {rel_path} to exist"


def test_workflows_contain_required_keys(tmp_repo: Path) -> None:
    """Each generated workflow has 'on:', 'jobs:', 'permissions:' and onmc commands."""
    run_gh_aw_init(tmp_repo)

    for rel_path in WORKFLOW_NAMES:
        content = (tmp_repo / rel_path).read_text(encoding="utf-8")
        assert "on:" in content, f"{rel_path}: missing 'on:'"
        assert "jobs:" in content, f"{rel_path}: missing 'jobs:'"
        assert "permissions:" in content, f"{rel_path}: missing 'permissions:'"
        assert "name:" in content, f"{rel_path}: missing 'name:'"
        assert "onmc" in content, f"{rel_path}: no onmc command reference"
        assert _SENTINEL in content, f"{rel_path}: missing sentinel"


def test_workflows_have_minimal_permissions(tmp_repo: Path) -> None:
    """All workflows specify read-only or narrowly-scoped permissions."""
    run_gh_aw_init(tmp_repo)

    for rel_path in WORKFLOW_NAMES:
        content = (tmp_repo / rel_path).read_text(encoding="utf-8")
        assert "contents: read" in content, f"{rel_path}: must have 'contents: read'"


def test_no_pull_request_target(tmp_repo: Path) -> None:
    """None of the workflows use pull_request_target (security posture)."""
    run_gh_aw_init(tmp_repo)

    for rel_path in WORKFLOW_NAMES:
        content = (tmp_repo / rel_path).read_text(encoding="utf-8")
        assert "pull_request_target" not in content, (
            f"{rel_path}: must NOT use pull_request_target"
        )


def test_no_curl_bash(tmp_repo: Path) -> None:
    """None of the workflows use curl|bash patterns."""
    run_gh_aw_init(tmp_repo)

    for rel_path in WORKFLOW_NAMES:
        content = (tmp_repo / rel_path).read_text(encoding="utf-8")
        assert "curl|bash" not in content, f"{rel_path}: must not use curl|bash"
        assert "curl | bash" not in content, f"{rel_path}: must not use curl | bash"


def test_reinit_skips_existing(tmp_repo: Path) -> None:
    """Re-running init skips already-managed files (idempotent)."""
    # First run
    first = run_gh_aw_init(tmp_repo)
    assert len(first.written) == 4
    assert first.skipped == []

    # Second run — all files exist and contain the sentinel
    second = run_gh_aw_init(tmp_repo)
    assert second.written == []
    assert len(second.skipped) == 4


def test_force_overwrites_existing(tmp_repo: Path) -> None:
    """--force overwrites already-managed files."""
    run_gh_aw_init(tmp_repo)  # first run writes

    result = run_gh_aw_init(tmp_repo, force=True)
    assert len(result.written) == 4
    assert result.skipped == []


def test_dry_run_writes_nothing(tmp_repo: Path) -> None:
    """--dry-run reports what would be written but creates no files."""
    result = run_gh_aw_init(tmp_repo, dry_run=True)

    assert result.dry_run is True
    assert len(result.written) == 4  # reports as 'would write'
    assert result.skipped == []

    # No files actually created
    workflows_dir = tmp_repo / ".github" / "workflows"
    assert not workflows_dir.exists(), "dry_run must not create any directories or files"


def test_dry_run_with_existing_skips(tmp_repo: Path) -> None:
    """--dry-run skips already-existing managed files (no force)."""
    # First real run to create the files
    run_gh_aw_init(tmp_repo)

    # Now dry-run — should report skipped, not written
    result = run_gh_aw_init(tmp_repo, dry_run=True)
    assert result.dry_run is True
    assert result.written == []
    assert len(result.skipped) == 4


def test_workflow_yaml_structural_markers(tmp_repo: Path) -> None:
    """Generated YAML has structural correctness markers (no PyYAML dependency)."""
    run_gh_aw_init(tmp_repo)

    for rel_path in WORKFLOW_NAMES:
        content = (tmp_repo / rel_path).read_text(encoding="utf-8")

        # Must have a workflow-level name (may be indented in raw template)
        lines = content.splitlines()
        name_lines = [ln for ln in lines if ln.strip().startswith("name:")]
        assert name_lines, f"{rel_path}: no top-level 'name:' field"

        # Must have at least one job step
        assert "- name:" in content, f"{rel_path}: no step 'name:' found"

        # Must reference python setup (consistent with repo's own CI)
        assert "setup-python" in content, f"{rel_path}: missing python setup"

        # Must install onmc
        assert "pip install" in content, f"{rel_path}: missing pip install step"


# ---------------------------------------------------------------------------
# Tests for specific workflow triggers
# ---------------------------------------------------------------------------


def test_issue_context_triggers_on_issues(tmp_repo: Path) -> None:
    """onmc-issue-context.yml triggers on issues: opened."""
    run_gh_aw_init(tmp_repo)
    content = (tmp_repo / ".github/workflows/onmc-issue-context.yml").read_text(
        encoding="utf-8"
    )
    assert "issues:" in content
    assert "opened" in content


def test_pr_preflight_triggers_on_pull_request(tmp_repo: Path) -> None:
    """onmc-pr-preflight.yml triggers on pull_request."""
    run_gh_aw_init(tmp_repo)
    content = (tmp_repo / ".github/workflows/onmc-pr-preflight.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request:" in content
    assert "opened" in content


def test_pr_learn_triggers_on_pr_closed(tmp_repo: Path) -> None:
    """onmc-pr-learn.yml triggers on pull_request: closed."""
    run_gh_aw_init(tmp_repo)
    content = (tmp_repo / ".github/workflows/onmc-pr-learn.yml").read_text(
        encoding="utf-8"
    )
    assert "closed" in content
    # Must gate on merged==true to avoid firing on rejected PRs
    assert "merged" in content


def test_weekly_audit_has_schedule(tmp_repo: Path) -> None:
    """onmc-weekly-audit.yml has a schedule trigger."""
    run_gh_aw_init(tmp_repo)
    content = (tmp_repo / ".github/workflows/onmc-weekly-audit.yml").read_text(
        encoding="utf-8"
    )
    assert "schedule:" in content
    assert "cron:" in content
    assert "workflow_dispatch:" in content


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_gh_aw_init_writes_files(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc gh-aw init PATH`` writes the four workflow files."""
    monkeypatch.chdir(tmp_repo)
    runner = _cli_runner()

    result = runner.invoke(app, ["gh-aw", "init", str(tmp_repo)])

    assert result.exit_code == 0, result.output
    assert "wrote:" in result.output

    for rel_path in WORKFLOW_NAMES:
        assert (tmp_repo / rel_path).exists()


def test_cli_gh_aw_init_dry_run(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc gh-aw init --dry-run`` prints but writes nothing."""
    monkeypatch.chdir(tmp_repo)
    runner = _cli_runner()

    result = runner.invoke(app, ["gh-aw", "init", str(tmp_repo), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Dry-run" in result.output

    workflows_dir = tmp_repo / ".github" / "workflows"
    assert not workflows_dir.exists()


def test_cli_gh_aw_init_json(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc gh-aw init --json`` outputs valid JSON with written/skipped/dry_run."""
    monkeypatch.chdir(tmp_repo)
    runner = _cli_runner()

    result = runner.invoke(app, ["gh-aw", "init", str(tmp_repo), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "written" in data
    assert "skipped" in data
    assert "dry_run" in data
    assert isinstance(data["written"], list)
    assert isinstance(data["skipped"], list)
    assert data["dry_run"] is False
    assert len(data["written"]) == 4


def test_cli_gh_aw_init_force(tmp_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc gh-aw init --force`` rewrites existing files."""
    monkeypatch.chdir(tmp_repo)
    runner = _cli_runner()

    # First run
    runner.invoke(app, ["gh-aw", "init", str(tmp_repo)])

    # Second run with --force — should re-write all four
    result = runner.invoke(app, ["gh-aw", "init", str(tmp_repo), "--force"])

    assert result.exit_code == 0, result.output
    assert "wrote:" in result.output
    assert "skipped" not in result.output


def test_cli_gh_aw_help(monkeypatch: pytest.MonkeyPatch, tmp_repo: Path) -> None:
    """``onmc gh-aw --help`` prints help text."""
    monkeypatch.chdir(tmp_repo)
    runner = _cli_runner()

    result = runner.invoke(app, ["gh-aw", "--help"])
    assert result.exit_code == 0
    assert "init" in result.output


def test_cli_gh_aw_init_help(monkeypatch: pytest.MonkeyPatch, tmp_repo: Path) -> None:
    """``onmc gh-aw init`` accepts --dry-run / --force / --json.

    Exercises the flags directly rather than scraping Rich-rendered ``--help``
    text: that output is ANSI-laden and wraps/truncates at CI's 80-col terminal,
    which made substring assertions flaky.
    """
    monkeypatch.chdir(tmp_repo)
    runner = _cli_runner()

    assert runner.invoke(app, ["gh-aw", "init", "--dry-run"]).exit_code == 0
    assert runner.invoke(app, ["gh-aw", "init", "--dry-run", "--json"]).exit_code == 0
    assert runner.invoke(app, ["gh-aw", "init", "--force", "--dry-run"]).exit_code == 0
