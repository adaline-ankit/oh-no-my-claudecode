"""CLI surface for ``onmc slash`` — auto-discovered via ``register(app)``.

``onmc slash install`` writes a Claude Code command file per onmc command so
they appear in the ``/`` menu; ``list`` shows what's installed; ``uninstall``
removes only onmc-generated files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.slash.installer import (
    commands_dir,
    install_slash_commands,
    list_installed,
    uninstall_slash_commands,
)


def _project_root() -> Path:
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo(
            "Not inside an onmc repository. Use --user to install globally, or run from a repo.",
            err=True,
        )
        raise typer.Exit(code=1) from None


def register(app: typer.Typer) -> None:
    """Register the ``slash`` command group onto the root ``app``."""
    slash = typer.Typer(
        help="Expose onmc's commands as Claude Code slash commands (/onmc-*).",
        no_args_is_help=True,
    )

    @slash.command("install")
    def install_command(
        user: Annotated[
            bool,
            typer.Option("--user/--project", help="Install to ~/.claude or ./.claude."),
        ] = True,
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", help="Show what would be written without writing."),
        ] = False,
        as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    ) -> None:
        """Generate /onmc-* Claude Code command files (one per onmc command)."""
        target = commands_dir(user=user, repo_root=None if user else _project_root())
        result = install_slash_commands(target, dry_run=dry_run)
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "target_dir": str(result.target_dir),
                        "written": result.written,
                        "skipped": result.skipped,
                        "dry_run": dry_run,
                    }
                )
            )
            return
        verb = "Would write" if dry_run else "Wrote"
        typer.echo(f"{verb} {len(result.written)} slash command(s) to {result.target_dir}")
        if result.written:
            preview = ", ".join(f"/{f[:-3]}" for f in result.written[:8])
            typer.echo("  " + preview + (" …" if len(result.written) > 8 else ""))
        if result.skipped:
            joined = ", ".join(result.skipped)
            typer.echo(f"Skipped {len(result.skipped)} hand-authored file(s): {joined}", err=True)
        if not dry_run:
            typer.echo("Reload Claude Code (or reopen the desktop app) to see them in the / menu.")

    @slash.command("list")
    def list_command(
        user: Annotated[bool, typer.Option("--user/--project")] = True,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """List onmc-generated slash command files."""
        target = commands_dir(user=user, repo_root=None if user else _project_root())
        installed = list_installed(target)
        if as_json:
            typer.echo(json.dumps({"target_dir": str(target), "installed": installed}))
            return
        if not installed:
            typer.echo(f"No onmc slash commands installed in {target}")
            return
        typer.echo(f"{len(installed)} onmc slash command(s) in {target}:")
        for name in installed:
            typer.echo(f"  /{name[:-3]}")

    @slash.command("uninstall")
    def uninstall_command(
        user: Annotated[bool, typer.Option("--user/--project")] = True,
        dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Remove onmc-generated slash command files (leaves hand-authored ones)."""
        target = commands_dir(user=user, repo_root=None if user else _project_root())
        result = uninstall_slash_commands(target, dry_run=dry_run)
        if as_json:
            payload = {"target_dir": str(target), "removed": result.removed, "dry_run": dry_run}
            typer.echo(json.dumps(payload))
            return
        verb = "Would remove" if dry_run else "Removed"
        typer.echo(f"{verb} {len(result.removed)} onmc slash command(s) from {target}")

    app.add_typer(slash, name="slash")
