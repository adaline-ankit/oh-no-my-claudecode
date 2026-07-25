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
from oh_no_my_claudecode.release import (
    draft_release,
    git_cliff_available,
    write_release,
)

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


# ---------------------------------------------------------------------------
# Optional git-cliff changelog generation
# ---------------------------------------------------------------------------
#
# git-cliff is an external binary, not a pip package. These tests inject a fake
# cliff-runner (a plain callable) so they are fully offline and deterministic —
# no real binary is ever shelled. The single real-binary test is skipif-guarded.


def _builtin_entry(commits: list[str]) -> str:
    """The changelog entry the built-in renderer produces (no cliff-runner)."""
    return draft_release(current_version="1.2.3", commits=commits, date=_DATE).changelog_entry


def test_injected_cliff_runner_supplies_changelog() -> None:
    """When a cliff-runner returns text, it becomes the changelog entry."""
    seen: dict[str, object] = {}

    def fake_cliff(repo_root: Path, next_version: str) -> str:
        seen["repo_root"] = repo_root
        seen["next_version"] = next_version
        return f"## cliff-rendered {next_version}\n\n- generated by git-cliff\n"

    commits = ["feat: shiny thing", "fix: a bug"]
    draft = draft_release(
        current_version="1.2.3",
        commits=commits,
        date=_DATE,
        cliff_runner=fake_cliff,
        repo_root=Path("/srv/repo"),
    )

    # The cliff output replaces the built-in changelog rendering...
    assert draft.changelog_entry == "## cliff-rendered 1.3.0\n\n- generated by git-cliff\n"
    assert draft.changelog_entry != _builtin_entry(commits)
    # ...but the runner was handed the computed next_version + repo_root.
    assert seen["next_version"] == "1.3.0"
    assert seen["repo_root"] == Path("/srv/repo")


def test_cliff_runner_does_not_change_bump_or_grouping() -> None:
    """git-cliff only renders the entry — bump + commits_by_type are unchanged."""
    commits = ["feat: a", "fix: b", "feat!: c"]

    def fake_cliff(repo_root: Path, next_version: str) -> str:
        return "## totally custom\n"

    with_cliff = draft_release(
        current_version="1.2.3", commits=commits, date=_DATE, cliff_runner=fake_cliff
    )
    without_cliff = draft_release(current_version="1.2.3", commits=commits, date=_DATE)

    assert with_cliff.bump == without_cliff.bump == "major"
    assert with_cliff.next_version == without_cliff.next_version == "2.0.0"
    assert with_cliff.commits_by_type == without_cliff.commits_by_type


def test_absent_cliff_runner_uses_builtin_fallback() -> None:
    """No cliff-runner -> the built-in conventional-commit draft is unchanged."""
    commits = ["feat: shiny thing", "fix: a bug"]
    draft = draft_release(current_version="1.2.3", commits=commits, date=_DATE)
    assert draft.changelog_entry == _builtin_entry(commits)
    assert draft.changelog_entry.startswith("## [1.3.0] — 2026-06-27")


def test_cliff_runner_returning_empty_falls_back_to_builtin() -> None:
    """A runner that yields nothing must not blank the changelog."""
    commits = ["feat: shiny thing"]

    for empty in ("", "   \n  "):

        def fake_cliff(repo_root: Path, next_version: str, _empty: str = empty) -> str:
            return _empty

        draft = draft_release(
            current_version="1.2.3", commits=commits, date=_DATE, cliff_runner=fake_cliff
        )
        assert draft.changelog_entry == _builtin_entry(commits)


def test_cliff_runner_returning_none_falls_back_to_builtin() -> None:
    commits = ["feat: shiny thing"]

    def fake_cliff(repo_root: Path, next_version: str) -> None:
        return None

    draft = draft_release(
        current_version="1.2.3", commits=commits, date=_DATE, cliff_runner=fake_cliff
    )
    assert draft.changelog_entry == _builtin_entry(commits)


def test_cliff_runner_raising_falls_back_to_builtin() -> None:
    """A crashing runner must never break the draft — fall back cleanly."""
    commits = ["feat: shiny thing"]

    def boom(repo_root: Path, next_version: str) -> str:
        raise RuntimeError("git-cliff blew up")

    draft = draft_release(current_version="1.2.3", commits=commits, date=_DATE, cliff_runner=boom)
    assert draft.changelog_entry == _builtin_entry(commits)


def test_cliff_output_gets_trailing_newline() -> None:
    """Cliff output missing a trailing newline is normalised to end with one."""

    def fake_cliff(repo_root: Path, next_version: str) -> str:
        return "## no trailing newline"

    draft = draft_release(
        current_version="1.2.3", commits=["feat: x"], date=_DATE, cliff_runner=fake_cliff
    )
    assert draft.changelog_entry == "## no trailing newline\n"


def test_git_cliff_available_reflects_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """git_cliff_available() is a pure PATH lookup (shutil.which)."""
    import oh_no_my_claudecode.release.drafter as drafter

    monkeypatch.setattr(drafter.shutil, "which", lambda _name: "/usr/bin/git-cliff")
    assert git_cliff_available() is True

    monkeypatch.setattr(drafter.shutil, "which", lambda _name: None)
    assert git_cliff_available() is False


def test_default_cliff_runner_none_when_binary_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    import oh_no_my_claudecode.release.drafter as drafter

    monkeypatch.setattr(drafter.shutil, "which", lambda _name: None)
    assert drafter.default_cliff_runner() is None


def test_cli_no_git_cliff_flag_uses_builtin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--no-git-cliff forces the deterministic built-in renderer."""
    repo = _seed_git_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = _runner().invoke(app, ["release", "--no-git-cliff", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    # Built-in renderer: no commits after the tag -> patch bump, standard heading.
    assert payload["next_version"] == "1.2.4"
    assert payload["changelog_entry"].startswith("## [1.2.4]")


@pytest.mark.skipif(not git_cliff_available(), reason="git-cliff binary not on PATH")
def test_real_git_cliff_binary_renders_entry(tmp_path: Path) -> None:
    """Smoke test against the real git-cliff binary when it is installed.

    Skipped entirely in offline/CI environments without the binary.
    """
    from oh_no_my_claudecode.release import default_cliff_runner

    repo = _seed_git_repo(tmp_path)
    # git-cliff needs a config; the repo has none, so the runner may legitimately
    # return None (non-zero exit) -> that is a valid fallback, not a failure.
    runner = default_cliff_runner()
    assert runner is not None
    rendered = runner(repo, "1.3.0")
    assert rendered is None or isinstance(rendered, str)


# ---------------------------------------------------------------------------
# Release-contract validation (onmc release --check)
# ---------------------------------------------------------------------------

from oh_no_my_claudecode.release import (  # noqa: E402
    changelog_has_version,
    evaluate_release_readiness,
    validate_release,
)

_CHANGELOG_130 = textwrap.dedent(
    """
    # Changelog

    ## [Unreleased]

    ## [1.3.0] — 2026-07-01

    ### Added

    - A feature.

    ## [1.2.3] — 2026-01-01

    ### Added

    - Initial release.
    """
).strip()


def test_changelog_has_version_detects_heading() -> None:
    assert changelog_has_version(_CHANGELOG_130, "1.3.0") is True
    assert changelog_has_version(_CHANGELOG_130, "9.9.9") is False


def test_evaluate_ready_to_tag() -> None:
    v = evaluate_release_readiness(
        current_version="1.3.0",
        existing_tags=["v1.2.3"],
        changelog_text=_CHANGELOG_130,
        last_tag="v1.2.3",
    )
    assert v.status == "ready-to-tag"
    assert v.ready is True
    assert not v.issues
    assert any("git tag v1.3.0" in note for note in v.notes)


def test_evaluate_already_released() -> None:
    v = evaluate_release_readiness(
        current_version="1.2.3",
        existing_tags=["v1.2.3"],
        changelog_text=_CHANGELOG_130,
        last_tag="v1.2.3",
    )
    assert v.status == "already-released"
    assert v.ready is False
    assert v.issues


def test_evaluate_no_changelog_entry() -> None:
    v = evaluate_release_readiness(
        current_version="1.3.0",
        existing_tags=["v1.2.3"],
        changelog_text="# Changelog\n\n## [Unreleased]\n",
        last_tag="v1.2.3",
    )
    assert v.status == "no-changelog-entry"
    assert v.ready is False


def test_evaluate_regression() -> None:
    v = evaluate_release_readiness(
        current_version="1.1.0",
        existing_tags=["v1.2.3"],
        changelog_text="## [1.1.0]\n",
        last_tag="v1.2.3",
    )
    assert v.status == "regression"
    assert v.ready is False


def test_validate_release_already_released_on_seed_repo(tmp_path: Path) -> None:
    # _seed_git_repo tags v1.2.3 and pyproject stays at 1.2.3.
    repo = _seed_git_repo(tmp_path)
    v = validate_release(repo)
    assert v.current_version == "1.2.3"
    assert v.version_tag_exists is True
    assert v.status == "already-released"
    assert v.ready is False


def test_cli_release_check_ready_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _seed_repo(
        tmp_path,
        pyproject=_PYPROJECT.replace("1.2.3", "1.3.0"),
        changelog=_CHANGELOG_130,
    )
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@e.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: seed")
    _git(repo, "tag", "v1.2.3")
    monkeypatch.chdir(repo)
    result = _runner().invoke(app, ["release", "--check"], catch_exceptions=False)
    assert result.exit_code == 0, result.output


def test_cli_release_check_already_released_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _seed_git_repo(tmp_path)  # pyproject 1.2.3, tag v1.2.3
    monkeypatch.chdir(repo)
    result = _runner().invoke(app, ["release", "--check"], catch_exceptions=False)
    assert result.exit_code == 1, result.output


def test_cli_release_check_rejects_write_combo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _seed_git_repo(tmp_path)
    monkeypatch.chdir(repo)
    result = _runner().invoke(app, ["release", "--check", "--write"])
    assert result.exit_code == 1, result.output
