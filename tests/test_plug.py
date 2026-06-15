"""Tests for ``onmc plug`` command and the integrations.plug module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks.installer import (
    hooks_installed,
    mcp_config_path,
    mcp_registered,
    project_settings_path,
)
from oh_no_my_claudecode.integrations.plug import (
    _CODEX_MARKER,
    _CURSOR_MARKER,
    _SENTINEL,
    SUPPORTED_TARGETS,
    PlugResult,
    plug_target,
)


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect Path.home() so install never touches real user settings."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("oh_no_my_claudecode.hooks.installer.Path.home", lambda: home)
    return home


@pytest.fixture
def initialized_repo(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A sample_repo with onmc initialized (needed for CLI commands via _service())."""
    monkeypatch.chdir(sample_repo)
    svc = OnmcService(sample_repo)
    svc.init_project()
    return sample_repo


# ---------------------------------------------------------------------------
# Unit tests for plug_target
# ---------------------------------------------------------------------------


def test_plug_codex_writes_agents_md(sample_repo: Path) -> None:
    """plug_target('codex') adds a stanza to AGENTS.md."""
    result = plug_target("codex", repo_root=sample_repo)

    assert isinstance(result, PlugResult)
    agents_md = sample_repo / "AGENTS.md"
    assert agents_md.exists()
    content = agents_md.read_text(encoding="utf-8")
    assert _CODEX_MARKER in content
    assert _SENTINEL in content
    assert "onmc brief" in content
    assert "onmc guard" in content
    assert str(agents_md) in result.files_written


def test_plug_codex_is_idempotent(sample_repo: Path) -> None:
    """Running plug_target('codex') twice produces exactly one stanza."""
    plug_target("codex", repo_root=sample_repo)
    plug_target("codex", repo_root=sample_repo)

    agents_md = sample_repo / "AGENTS.md"
    content = agents_md.read_text(encoding="utf-8")
    # The start marker must appear exactly once.
    assert content.count(_CODEX_MARKER) == 1


def test_plug_codex_preserves_existing_content(sample_repo: Path) -> None:
    """Existing AGENTS.md content outside the stanza is preserved."""
    agents_md = sample_repo / "AGENTS.md"
    original = "# Existing content\n\nSome notes here.\n"
    agents_md.write_text(original, encoding="utf-8")

    plug_target("codex", repo_root=sample_repo)

    content = agents_md.read_text(encoding="utf-8")
    assert "# Existing content" in content
    assert "Some notes here." in content
    assert _CODEX_MARKER in content


def test_plug_codex_skips_on_second_run_with_no_changes(sample_repo: Path) -> None:
    """Second run with identical stanza is reported as skipped."""
    plug_target("codex", repo_root=sample_repo)
    result2 = plug_target("codex", repo_root=sample_repo)

    agents_md = sample_repo / "AGENTS.md"
    # Second call: no new writes (stanza unchanged), skipped
    assert str(agents_md) in result2.files_skipped
    assert str(agents_md) not in result2.files_written


def test_plug_cursor_writes_rules_file(sample_repo: Path) -> None:
    """plug_target('cursor') writes .cursor/rules/onmc.md."""
    result = plug_target("cursor", repo_root=sample_repo)

    rules_file = sample_repo / ".cursor" / "rules" / "onmc.md"
    assert rules_file.exists()
    content = rules_file.read_text(encoding="utf-8")
    assert _CURSOR_MARKER in content
    assert _SENTINEL in content
    assert "onmc brief" in content
    assert "onmc guard" in content
    assert str(rules_file) in result.files_written


def test_plug_cursor_is_idempotent(sample_repo: Path) -> None:
    """Running plug_target('cursor') twice produces exactly one stanza."""
    plug_target("cursor", repo_root=sample_repo)
    plug_target("cursor", repo_root=sample_repo)

    rules_file = sample_repo / ".cursor" / "rules" / "onmc.md"
    content = rules_file.read_text(encoding="utf-8")
    assert content.count(_CURSOR_MARKER) == 1


def test_plug_cursor_skips_on_second_run(sample_repo: Path) -> None:
    """Second cursor run reports the file as skipped."""
    plug_target("cursor", repo_root=sample_repo)
    result2 = plug_target("cursor", repo_root=sample_repo)

    rules_file = sample_repo / ".cursor" / "rules" / "onmc.md"
    assert str(rules_file) in result2.files_skipped


def test_plug_claude_code_installs_hooks_and_mcp(
    sample_repo: Path, fake_home: Path
) -> None:
    """plug_target('claude-code') installs hooks and .mcp.json."""
    result = plug_target("claude-code", repo_root=sample_repo)

    settings_path = project_settings_path(sample_repo)
    mcp_path = mcp_config_path(sample_repo)

    assert hooks_installed(settings_path=settings_path)
    assert mcp_registered(mcp_path=mcp_path)
    assert isinstance(result, PlugResult)
    assert str(settings_path) in result.files_written
    assert str(mcp_path) in result.files_written


def test_plug_claude_code_is_idempotent(sample_repo: Path, fake_home: Path) -> None:
    """Running plug_target('claude-code') twice leaves settings consistent."""
    plug_target("claude-code", repo_root=sample_repo)
    plug_target("claude-code", repo_root=sample_repo)

    settings_path = project_settings_path(sample_repo)
    assert hooks_installed(settings_path=settings_path)

    # settings.json must be valid JSON after both runs
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "hooks" in payload


def test_plug_omc_writes_doc(sample_repo: Path) -> None:
    """plug_target('omc') writes docs/integrations/omc.md."""
    result = plug_target("omc", repo_root=sample_repo)

    omc_doc = sample_repo / "docs" / "integrations" / "omc.md"
    assert omc_doc.exists()
    content = omc_doc.read_text(encoding="utf-8")
    assert _SENTINEL in content
    assert "onmc brief" in content
    assert "onmc guard" in content
    assert str(omc_doc) in result.files_written


def test_plug_omc_is_idempotent(sample_repo: Path) -> None:
    """Running plug_target('omc') twice skips on second run."""
    plug_target("omc", repo_root=sample_repo)
    result2 = plug_target("omc", repo_root=sample_repo)

    omc_doc = sample_repo / "docs" / "integrations" / "omc.md"
    assert str(omc_doc) in result2.files_skipped


def test_plug_omx_writes_doc(sample_repo: Path) -> None:
    """plug_target('omx') writes docs/integrations/omx.md."""
    result = plug_target("omx", repo_root=sample_repo)

    omx_doc = sample_repo / "docs" / "integrations" / "omx.md"
    assert omx_doc.exists()
    content = omx_doc.read_text(encoding="utf-8")
    assert _SENTINEL in content
    assert str(omx_doc) in result.files_written


def test_plug_all_applies_safe_subset(sample_repo: Path, fake_home: Path) -> None:
    """plug_target('all') applies claude-code + codex + cursor."""
    result = plug_target("all", repo_root=sample_repo)

    # claude-code: settings + mcp
    settings_path = project_settings_path(sample_repo)
    assert hooks_installed(settings_path=settings_path)

    # codex: AGENTS.md
    agents_md = sample_repo / "AGENTS.md"
    assert agents_md.exists()
    assert _CODEX_MARKER in agents_md.read_text(encoding="utf-8")

    # cursor: .cursor/rules/onmc.md
    rules_file = sample_repo / ".cursor" / "rules" / "onmc.md"
    assert rules_file.exists()

    assert result.target == "all"


def test_plug_unknown_target_raises(sample_repo: Path) -> None:
    """plug_target raises ValueError for unknown targets."""
    with pytest.raises(ValueError, match="Unknown target"):
        plug_target("nonexistent-agent", repo_root=sample_repo)


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


def test_cli_plug_codex(initialized_repo: Path) -> None:
    """``onmc plug codex`` via CLI writes AGENTS.md stanza."""
    runner = _cli_runner()
    result = runner.invoke(app, ["plug", "codex"], prog_name="onmc")

    assert result.exit_code == 0, result.output
    agents_md = initialized_repo / "AGENTS.md"
    assert agents_md.exists()
    assert _CODEX_MARKER in agents_md.read_text(encoding="utf-8")


def test_cli_plug_cursor(initialized_repo: Path) -> None:
    """``onmc plug cursor`` via CLI writes .cursor/rules/onmc.md."""
    runner = _cli_runner()
    result = runner.invoke(app, ["plug", "cursor"], prog_name="onmc")

    assert result.exit_code == 0, result.output
    rules_file = initialized_repo / ".cursor" / "rules" / "onmc.md"
    assert rules_file.exists()


def test_cli_plug_claude_code(initialized_repo: Path, fake_home: Path) -> None:
    """``onmc plug claude-code`` via CLI installs hooks and .mcp.json."""
    runner = _cli_runner()
    result = runner.invoke(app, ["plug", "claude-code"], prog_name="onmc")

    assert result.exit_code == 0, result.output
    settings_path = project_settings_path(initialized_repo)
    assert hooks_installed(settings_path=settings_path)
    mcp_path = mcp_config_path(initialized_repo)
    assert mcp_registered(mcp_path=mcp_path)


def test_cli_plug_unknown_target_exits_nonzero(initialized_repo: Path) -> None:
    """``onmc plug badtarget`` exits with code 1 and a helpful message."""
    runner = _cli_runner()
    result = runner.invoke(app, ["plug", "badtarget"], prog_name="onmc")

    assert result.exit_code == 1
    assert "badtarget" in result.output or "Unknown" in result.output


def test_supported_targets_list() -> None:
    """SUPPORTED_TARGETS contains all expected entries."""
    expected = {"claude-code", "codex", "cursor", "omc", "omx", "all"}
    assert set(SUPPORTED_TARGETS) == expected
