"""Disposable-repo E2E for the ONMC golden path.

Exercises the full user-facing arc in a throwaway git repo:

    setup (install hooks) → wrap / slash → status → uninstall

plus the safety hardening that must hold at each step:

- a *malformed* ``settings.json`` is preserved (never silently discarded);
- repeated install is idempotent;
- a user-authored ``CLAUDE.md`` is never clobbered (backed up + merged);
- ``onmc status`` clearly reports whether ONMC is active;
- ``uninstall`` removes only onmc entries, leaving user hooks + the backup.

Everything is offline (``no_llm=True`` / direct installer calls) so the suite
is deterministic and fast.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks.installer import (
    hooks_installed,
    install_claude_hooks,
    install_wrap_hooks,
    project_settings_backup_path,
    project_settings_path,
    wrap_hooks_installed,
)


@pytest.fixture(autouse=True)
def _isolate_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Redirect HOME to a throwaway dir for every test in this module.

    The install/uninstall paths clean legacy entries from the user-level
    ``~/.claude/settings.json`` (``Path.home()``); without this the E2E would
    read and rewrite the developer's real Claude config and could bleed into
    other tests that inspect ``~/.claude``.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    return home


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# settings.json safety
# ---------------------------------------------------------------------------


def test_install_over_malformed_settings_preserves_original(sample_repo: Path) -> None:
    settings = project_settings_path(sample_repo)
    settings.parent.mkdir(parents=True, exist_ok=True)
    broken = '{ "hooks": { NOT VALID JSON '
    settings.write_text(broken, encoding="utf-8")

    result = install_claude_hooks(repo_root=sample_repo, register_mcp=False)

    # The malformed original was copied aside, not silently discarded.
    assert result.corrupt_backup_path is not None
    assert result.corrupt_backup_path.exists()
    assert result.corrupt_backup_path.read_text(encoding="utf-8") == broken
    # settings.json is now valid JSON with the onmc hooks installed.
    assert hooks_installed(settings_path=settings)
    _read_json(settings)  # parses without raising


def test_valid_settings_is_not_flagged_corrupt(sample_repo: Path) -> None:
    settings = project_settings_path(sample_repo)
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreCompact": [
                        {"matcher": "", "hooks": [{"type": "command", "command": "my-own-hook"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    result = install_claude_hooks(repo_root=sample_repo, register_mcp=False)
    assert result.corrupt_backup_path is None
    # The user's own hook survives alongside the onmc hooks.
    data = _read_json(settings)
    commands = [
        item["command"]
        for entry in data["hooks"]["PreCompact"]  # type: ignore[index]
        for item in entry["hooks"]
    ]
    assert "my-own-hook" in commands


def test_repeated_install_is_idempotent(sample_repo: Path) -> None:
    first = install_claude_hooks(repo_root=sample_repo, register_mcp=True)
    settings = project_settings_path(sample_repo)
    after_first = settings.read_text(encoding="utf-8")
    assert first.backup_created is True

    second = install_claude_hooks(repo_root=sample_repo, register_mcp=True)
    after_second = settings.read_text(encoding="utf-8")
    assert second.backup_created is False  # pristine backup never overwritten
    assert after_first == after_second  # no duplicate hooks appended


# ---------------------------------------------------------------------------
# CLAUDE.md no-clobber
# ---------------------------------------------------------------------------


def test_setup_claude_md_generates_when_absent(sample_repo: Path) -> None:
    service = OnmcService(sample_repo)
    service.init_project()
    action, backup = service.setup_claude_md(no_llm=True)
    assert action == "generated"
    assert backup is None
    assert (sample_repo / "CLAUDE.md").exists()


def test_setup_claude_md_never_clobbers_user_file(sample_repo: Path) -> None:
    service = OnmcService(sample_repo)
    service.init_project()
    user_content = "# My hand-written CLAUDE.md\n\nSACRED-USER-CONTENT-DO-NOT-LOSE\n"
    (sample_repo / "CLAUDE.md").write_text(user_content, encoding="utf-8")

    action, backup = service.setup_claude_md(no_llm=True)

    # A non-onmc file is merged, and the original is preserved verbatim.
    assert action == "merged"
    assert backup is not None and backup.exists()
    assert backup.read_text(encoding="utf-8") == user_content


# ---------------------------------------------------------------------------
# status active reporting
# ---------------------------------------------------------------------------


def test_status_reports_active_state(sample_repo: Path) -> None:
    service = OnmcService(sample_repo)
    service.init_project()
    assert service.status()["onmc_active"] == "no"

    install_claude_hooks(repo_root=sample_repo, register_mcp=True)
    status = service.status()
    assert status["onmc_active"] == "yes"
    assert status["hooks_installed"] == "yes"
    assert status["mcp_registered"] == "yes"


# ---------------------------------------------------------------------------
# Full golden path: setup → wrap/slash → status → uninstall
# ---------------------------------------------------------------------------


def test_full_golden_path_roundtrip(sample_repo: Path) -> None:
    from oh_no_my_claudecode.slash.generator import GENERATED_MARKER
    from oh_no_my_claudecode.slash.installer import commands_dir, list_installed

    service = OnmcService(sample_repo)
    service.init_project()
    settings = project_settings_path(sample_repo)

    # A pre-existing user hook that uninstall must never touch.
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreCompact": [
                        {
                            "matcher": "",
                            "hooks": [{"type": "command", "command": "user-precompact-hook"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    # setup → install base hooks + wrap layer + slash commands.
    # The slash commands are represented directly by marker/non-marker files so
    # the teardown assertion (remove onmc-generated, keep hand-authored) does
    # not depend on the shared global Typer app used elsewhere in the suite.
    install_claude_hooks(repo_root=sample_repo, register_mcp=True)
    install_wrap_hooks(repo_root=sample_repo, strict=False)
    slash_dir = commands_dir(user=False, repo_root=sample_repo)
    slash_dir.mkdir(parents=True, exist_ok=True)
    (slash_dir / "onmc-why.md").write_text(f"---\n{GENERATED_MARKER}\n---\n", encoding="utf-8")
    (slash_dir / "my-own-command.md").write_text("hand authored, no marker", encoding="utf-8")

    assert hooks_installed(settings_path=settings)
    assert wrap_hooks_installed(settings_path=settings)
    assert list_installed(slash_dir) == ["onmc-why.md"]  # only the generated one
    assert service.status()["onmc_active"] == "yes"
    assert service.status()["wrap_active"] == "yes"

    # uninstall → clean teardown
    summary = service.uninstall_all()
    assert summary["wrap_removed"] is True
    assert summary["slash_removed"]

    # onmc entries gone …
    assert not hooks_installed(settings_path=settings)
    assert not wrap_hooks_installed(settings_path=settings)
    assert list_installed(slash_dir) == []  # generated slash file removed
    assert (slash_dir / "my-own-command.md").exists()  # hand-authored survives
    assert service.status()["onmc_active"] == "no"

    # … but the user's own hook and the pristine backup survive.
    data = _read_json(settings)
    remaining = [
        item["command"]
        for entry in data.get("hooks", {}).get("PreCompact", [])  # type: ignore[union-attr]
        for item in entry["hooks"]
    ]
    assert "user-precompact-hook" in remaining
    assert project_settings_backup_path(sample_repo).exists()
