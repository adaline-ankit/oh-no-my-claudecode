"""Tests for ``onmc release`` — draft CHANGELOG + semver bump from commits.

Coverage
--------
- feat commits -> minor bump; fixes-only -> patch; "!"/BREAKING -> major.
- The rendered CHANGELOG entry groups commits under the repo's section headings
  and matches the repo's heading format (``## [X.Y.Z] — YYYY-MM-DD``).
- ``draft_release`` is pure + deterministic from injected commits (same inputs
  -> identical output).
- ``--dry-run`` (default) writes nothing; ``--write`` edits both pyproject.toml
  and CHANGELOG.md in a tmp repo.
- Everything offline; no Rich --help text is asserted — the CLI is exercised via
  flags and the JSON / file outcomes instead.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.release import draft_release, write_release

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE = "2026-06-27"

_PYPROJECT = textwrap.dedent(
    """
    [project]
    name = "demo"
    version = "1.2.3"
    """
).strip()

_CHANGELOG = textwrap.dedent(
    """
    # Changelog

    All notable changes to this project are documented here.

    ## [Unreleased]

    ## [1.2.3] — 2026-01-01

    ### Added

    - Initial release.
    """
).strip()


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _seed_repo(tmp_path: Path, *, pyproject: str = _PYPROJECT, changelog: str = _CHANGELOG) -> Path:
    (tmp_path / "pyproject.toml").write_text(pyproject + "\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(changelog + "\n", encoding="utf-8")
    return tmp_path


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _seed_git_repo(tmp_path: Path) -> Path:
    """Seed a tmp git repo with pyproject + CHANGELOG and one tagged commit.

    No commits exist after the tag, so the CLI's ``collect_commits`` returns an
    empty log -> a deterministic patch bump.
    """
    repo = _seed_repo(tmp_path)
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: seed")
    _git(repo, "tag", "v1.2.3")
    return repo


# ---------------------------------------------------------------------------
# Pure drafter — bump classification
# ---------------------------------------------------------------------------


def test_feats_bump_minor() -> None:
    draft = draft_release(
        current_version="1.2.3",
        commits=["feat(loop): add resume flag", "fix(cli): typo"],
        date=_DATE,
    )
    assert draft.bump == "minor"
    assert draft.next_version == "1.3.0"


def test_fixes_only_bump_patch() -> None:
    draft = draft_release(
        current_version="1.2.3",
        commits=["fix(cli): typo", "fix: off-by-one", "docs: tidy readme"],
        date=_DATE,
    )
    assert draft.bump == "patch"
    assert draft.next_version == "1.2.4"


def test_bang_bump_major() -> None:
    draft = draft_release(
        current_version="1.2.3",
        commits=["feat!: drop python 3.10", "fix: small"],
        date=_DATE,
    )
    assert draft.bump == "major"
    assert draft.next_version == "2.0.0"


def test_breaking_change_footer_bump_major() -> None:
    draft = draft_release(
        current_version="1.2.3",
        commits=["feat: new api BREAKING CHANGE: removed old endpoint"],
        date=_DATE,
    )
    assert draft.bump == "major"
    assert draft.next_version == "2.0.0"


def test_non_conventional_defaults_to_patch() -> None:
    draft = draft_release(
        current_version="1.2.3",
        commits=["random commit message", "another one"],
        date=_DATE,
    )
    assert draft.bump == "patch"
    assert draft.next_version == "1.2.4"


def test_no_commits_defaults_to_patch() -> None:
    draft = draft_release(current_version="1.2.3", commits=[], date=_DATE)
    assert draft.bump == "patch"
    assert draft.next_version == "1.2.4"


def test_release_chore_commits_are_ignored() -> None:
    draft = draft_release(
        current_version="1.2.3",
        commits=["chore(release): v1.2.3", "fix: real fix"],
        date=_DATE,
    )
    # The release chore must not count as a commit.
    assert sum(len(v) for v in draft.commits_by_type.values()) == 1
    assert draft.bump == "patch"


# ---------------------------------------------------------------------------
# Pure drafter — grouping + format
# ---------------------------------------------------------------------------


def test_changelog_grouped_and_formatted() -> None:
    draft = draft_release(
        current_version="1.2.3",
        commits=[
            "feat(loop): add resume flag",
            "feat: synthetic datasets",
            "fix(cli): typo",
            "perf: faster scan",
        ],
        date=_DATE,
    )
    entry = draft.changelog_entry
    assert entry.startswith("## [1.3.0] — 2026-06-27")
    assert "### Added" in entry
    assert "### Fixed" in entry
    assert "### Changed" in entry  # perf -> Changed
    # Conventional-commit prefixes are stripped in the rendered bullets.
    assert "- add resume flag" in entry
    assert "- synthetic datasets" in entry
    assert "- typo" in entry
    assert "- faster scan" in entry
    # Added section appears before Fixed (repo ordering).
    assert entry.index("### Added") < entry.index("### Fixed")


def test_draft_is_deterministic_from_injected_commits() -> None:
    commits = ["feat: a", "fix: b", "feat!: c"]
    first = draft_release(current_version="0.4.1", commits=commits, date=_DATE)
    second = draft_release(current_version="0.4.1", commits=commits, date=_DATE)
    assert first == second
    assert first.changelog_entry == second.changelog_entry


def test_prerelease_current_version_parses() -> None:
    draft = draft_release(
        current_version="0.5.0rc1",
        commits=["feat: ship it"],
        date=_DATE,
    )
    assert draft.next_version == "0.6.0"


# ---------------------------------------------------------------------------
# write_release — file edits
# ---------------------------------------------------------------------------


def test_write_release_edits_both_files(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    draft = draft_release(
        current_version="1.2.3",
        commits=["feat: shiny new thing"],
        date=_DATE,
    )
    write_release(repo, draft)

    pyproject_text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "1.3.0"' in pyproject_text
    assert 'version = "1.2.3"' not in pyproject_text

    changelog_text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [Unreleased]" in changelog_text
    assert "## [1.3.0] — 2026-06-27" in changelog_text
    assert "- shiny new thing" in changelog_text
    # New entry sits below [Unreleased] and above the prior version.
    assert changelog_text.index("## [Unreleased]") < changelog_text.index("## [1.3.0]")
    assert changelog_text.index("## [1.3.0]") < changelog_text.index("## [1.2.3]")
    # The prior entry is preserved.
    assert "## [1.2.3] — 2026-01-01" in changelog_text


# ---------------------------------------------------------------------------
# CLI — dry-run / write / json
# ---------------------------------------------------------------------------


def test_cli_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _seed_git_repo(tmp_path)
    monkeypatch.chdir(repo)
    pyproject_before = (repo / "pyproject.toml").read_text(encoding="utf-8")
    changelog_before = (repo / "CHANGELOG.md").read_text(encoding="utf-8")

    result = _runner().invoke(app, ["release"], catch_exceptions=False)

    assert result.exit_code == 0
    assert (repo / "pyproject.toml").read_text(encoding="utf-8") == pyproject_before
    assert (repo / "CHANGELOG.md").read_text(encoding="utf-8") == changelog_before


def test_cli_write_edits_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _seed_git_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = _runner().invoke(app, ["release", "--write"], catch_exceptions=False)

    assert result.exit_code == 0
    pyproject_text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    changelog_text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert 'version = "1.2.4"' in pyproject_text  # no commits after tag -> patch
    assert "## [1.2.4]" in changelog_text


def test_cli_json_emits_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _seed_git_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = _runner().invoke(app, ["release", "--json"], catch_exceptions=False)

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["current_version"] == "1.2.3"
    assert payload["bump"] in {"major", "minor", "patch"}
    assert "next_version" in payload
    assert "changelog_entry" in payload
