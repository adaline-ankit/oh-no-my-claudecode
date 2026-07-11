"""Offline, deterministic tests for `onmc slash`."""

from __future__ import annotations

from pathlib import Path

import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.slash.generator import (
    GENERATED_MARKER,
    SlashCommand,
    discover_slash_commands,
    render_command_file,
)
from oh_no_my_claudecode.slash.installer import (
    commands_dir,
    install_slash_commands,
    list_installed,
    uninstall_slash_commands,
)


def _mini_app() -> typer.Typer:
    """A tiny app to make discovery deterministic and independent of onmc growth."""
    a = typer.Typer()

    @a.command("why")
    def _why(path: str) -> None:
        """Explain a file."""

    @a.command("ping")
    def _ping() -> None:
        """No-arg command."""

    sub = typer.Typer()

    @sub.command("plan")
    def _plan() -> None:
        """Plan."""

    a.add_typer(sub, name="swarm", help="Swarm things.")
    return a


def test_discovers_top_level_commands() -> None:
    cmds = {c.name: c for c in discover_slash_commands(_mini_app())}
    assert set(cmds) == {"why", "ping", "swarm"}
    assert cmds["why"].takes_args is True  # has a param
    assert cmds["ping"].takes_args is False  # param-less leaf
    assert cmds["swarm"].takes_args is True  # is a group


def test_slash_and_filename_shape() -> None:
    c = SlashCommand(name="why", help="Explain", takes_args=True)
    assert c.slash == "/onmc-why"
    assert c.filename == "onmc-why.md"


def test_render_includes_marker_and_call() -> None:
    c = SlashCommand(name="why", help="Explain a file", takes_args=True)
    text = render_command_file(c)
    assert GENERATED_MARKER in text
    assert "onmc why $ARGUMENTS" in text
    assert "allowed-tools: Bash(onmc why:*)" in text
    assert "argument-hint:" in text


def test_render_no_args_command_omits_arguments() -> None:
    c = SlashCommand(name="ping", help="ping", takes_args=False)
    text = render_command_file(c)
    assert "$ARGUMENTS" not in text
    assert "argument-hint:" not in text


def test_discovery_is_deterministic() -> None:
    a, b = discover_slash_commands(_mini_app()), discover_slash_commands(_mini_app())
    assert [c.name for c in a] == [c.name for c in b]


def test_real_app_discovery_skips_plumbing_and_finds_features() -> None:
    names = {c.name for c in discover_slash_commands(app)}
    assert "serve" not in names and "slash" not in names  # plumbing filtered
    # A few known shipped features should surface as slash commands.
    assert {"why", "swarm", "guard"} <= names


def test_install_writes_files(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "commands"
    res = install_slash_commands(target, root_app=_mini_app())
    assert set(res.written) == {"onmc-why.md", "onmc-ping.md", "onmc-swarm.md"}
    assert (target / "onmc-why.md").exists()
    assert GENERATED_MARKER in (target / "onmc-why.md").read_text()


def test_install_dry_run_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "commands"
    res = install_slash_commands(target, root_app=_mini_app(), dry_run=True)
    assert res.written  # reported
    assert not target.exists()  # but nothing written


def test_install_skips_hand_authored(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "commands"
    target.mkdir(parents=True)
    (target / "onmc-why.md").write_text("my own command, no marker")
    res = install_slash_commands(target, root_app=_mini_app())
    assert "onmc-why.md" in res.skipped
    assert "onmc-why.md" not in res.written
    assert (target / "onmc-why.md").read_text() == "my own command, no marker"  # untouched


def test_install_overwrites_generated(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "commands"
    install_slash_commands(target, root_app=_mini_app())
    (target / "onmc-why.md").write_text(f"stale\n{GENERATED_MARKER}\n")
    res = install_slash_commands(target, root_app=_mini_app())
    assert "onmc-why.md" in res.written  # regenerated, not skipped
    assert "onmc why" in (target / "onmc-why.md").read_text()


def test_list_and_uninstall_only_generated(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "commands"
    install_slash_commands(target, root_app=_mini_app())
    (target / "onmc-mine.md").write_text("hand authored, no marker")
    listed = list_installed(target)
    assert "onmc-mine.md" not in listed
    assert "onmc-why.md" in listed
    res = uninstall_slash_commands(target)
    assert "onmc-why.md" in res.removed
    assert (target / "onmc-mine.md").exists()  # hand-authored survives
    assert not (target / "onmc-why.md").exists()


def test_commands_dir_scopes() -> None:
    assert commands_dir(user=True).parts[-2:] == (".claude", "commands")
    proj = commands_dir(user=False, repo_root=Path("/repo"))
    assert proj == Path("/repo/.claude/commands")


def test_cli_install_dry_run_json(tmp_path: Path) -> None:
    r = CliRunner().invoke(app, ["slash", "install", "--user", "--dry-run", "--json"])
    assert r.exit_code == 0
    assert '"dry_run": true' in r.output


def test_cli_list_json_smoke() -> None:
    r = CliRunner().invoke(app, ["slash", "list", "--user", "--json"])
    assert r.exit_code == 0
    assert "installed" in r.output
