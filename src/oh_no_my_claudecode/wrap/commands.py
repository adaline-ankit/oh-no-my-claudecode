"""CLI surface for ``onmc wrap`` / ``onmc unwrap`` — auto-discovered.

Follows the auto-discovery convention: a top-level :func:`register` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. Touches **zero** shared hub files — the hook
entrypoints (``onmc hooks task-intercept`` / ``onmc hooks prompt-router``) live
in the hooks group in ``cli.py``, but the user-facing ``wrap`` / ``unwrap``
verbs register themselves here.

``wrap`` installs the two wrap hooks (reusing the shared installer's backup +
merge), records the strict/soft mode, and injects a CLAUDE.md policy stanza.
``unwrap`` is the perfect inverse: it removes exactly those two hooks, the
state file, and the stanza, leaving everything else byte-for-byte intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.hooks.installer import (
    install_wrap_hooks,
    project_settings_backup_path,
    project_settings_path,
    uninstall_wrap_hooks,
)
from oh_no_my_claudecode.wrap.state import (
    remove_claude_md_stanza,
    remove_wrap_state,
    upsert_claude_md_stanza,
    write_wrap_state,
)


def _echo(message: str) -> None:
    typer.echo(message)


def register(app: typer.Typer) -> None:
    """Register the ``wrap`` and ``unwrap`` commands onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("wrap")
    def wrap_command(
        strict: Annotated[
            bool,
            typer.Option(
                "--strict/--soft",
                help=(
                    "strict: deny native Task spawns and redirect to `onmc "
                    "swarm`. soft: allow them with a nudge. Default: strict."
                ),
            ),
        ] = True,
        global_scope: Annotated[
            bool,
            typer.Option(
                "--global/--project",
                help="Install into the user-level ~/.claude/settings.json (default: project).",
            ),
        ] = False,
    ) -> None:
        """Make onmc the default layer for Claude Code in this repo.

        Installs a Task intercept (PreToolUse matcher ``Task``) that redirects
        native agent-spawning to ``onmc swarm``, plus a prompt router
        (UserPromptSubmit) that nudges toward onmc paths. Backs up
        settings.json before editing. Reverse with ``onmc unwrap``.
        """
        try:
            repo_root = discover_repo_root(Path.cwd())
        except RepoDiscoveryError as exc:
            raise typer.Exit(code=1) from exc

        if global_scope:
            settings_path = Path.home() / ".claude" / "settings.json"
            backup_path = settings_path.with_name(f"{settings_path.name}.onmc-backup")
        else:
            settings_path = project_settings_path(repo_root)
            backup_path = project_settings_backup_path(repo_root)

        result = install_wrap_hooks(
            repo_root=repo_root,
            strict=strict,
            settings_path=settings_path,
            backup_path=backup_path,
        )
        write_wrap_state(repo_root, strict=strict)
        claude_md = upsert_claude_md_stanza(repo_root)

        mode = "strict" if strict else "soft"
        scope = "global" if global_scope else "project"
        _echo(f"onmc wrap active ({mode}, {scope}).")
        _echo("  - Task intercept installed (PreToolUse matcher 'Task').")
        _echo("  - Prompt router installed (UserPromptSubmit).")
        if result.backup_created:
            _echo(f"  - Backup written: {result.backup_path}")
        _echo(f"  - Policy stanza added to: {claude_md}")
        if strict:
            _echo(
                "  Native Task spawns are now DENIED and redirected to "
                "`onmc swarm plan` (set ONMC_ALLOW_TASK=1 to bypass once)."
            )
        else:
            _echo("  Native Task spawns are allowed with a nudge toward `onmc swarm`.")
        _echo(f"  Settings: {result.settings_path}")
        _echo("  Reverse anytime with: onmc unwrap")

    @app.command("unwrap")
    def unwrap_command(
        global_scope: Annotated[
            bool,
            typer.Option(
                "--global/--project",
                help="Remove from the user-level ~/.claude/settings.json (default: project).",
            ),
        ] = False,
    ) -> None:
        """Remove the onmc wrap layer — the perfect inverse of ``onmc wrap``.

        Strips exactly the two wrap hooks, the wrap-state file, and the
        CLAUDE.md policy stanza. Every other hook and all CLAUDE.md content is
        left untouched. The settings.json backup is kept as a safety artifact.
        """
        try:
            repo_root = discover_repo_root(Path.cwd())
        except RepoDiscoveryError as exc:
            raise typer.Exit(code=1) from exc

        if global_scope:
            settings_path = Path.home() / ".claude" / "settings.json"
        else:
            settings_path = project_settings_path(repo_root)

        hooks_removed = uninstall_wrap_hooks(repo_root=repo_root, settings_path=settings_path)
        state_removed = remove_wrap_state(repo_root)
        stanza_removed = remove_claude_md_stanza(repo_root)

        _echo("onmc unwrap complete.")
        _echo(
            f"  - Wrap hooks: {'removed' if hooks_removed else 'none present'} "
            f"({settings_path})"
        )
        _echo(f"  - Wrap state: {'removed' if state_removed else 'none present'}")
        _echo(f"  - CLAUDE.md stanza: {'removed' if stanza_removed else 'none present'}")
        _echo("  Native Task spawning and prompt handling are back to Claude Code defaults.")
