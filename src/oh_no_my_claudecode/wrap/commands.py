"""CLI surface for ``onmc wrap`` / ``onmc unwrap`` — auto-discovered.

Follows the auto-discovery convention: a top-level :func:`register` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.

The ``wrap`` group has two layers:

**Callback (install layer)**
  ``onmc wrap [--strict/--soft] [--global/--project] [--default-active]``
  installs the Task intercept + prompt router hooks into settings.json,
  writes the wrap-state file, injects the CLAUDE.md policy stanza, and
  drops the ``/onmc`` Claude Code slash command.

  ``onmc wrap --managed [--managed-path PATH]``
  installs the same hooks into the OS-level managed-settings.json so users
  cannot override or disable them.  Requires admin/root for the default system
  path; when the path is not writable, prints the exact JSON to install manually
  (no sudo attempted).

**Session sub-commands (switch layer)**
  ``onmc wrap on`` / ``off`` / ``toggle`` / ``status [--json]``
  control whether the deep-wrap lifecycle hooks engage for the current session
  without touching settings.json.  ``/onmc`` in Claude Code calls
  ``onmc wrap toggle`` so the user can flip the switch from within the editor.

``unwrap`` is the perfect inverse of the install: it removes exactly what
``wrap`` added (hooks, state file, CLAUDE.md stanza, ``/onmc`` command),
leaving every other hook byte-for-byte intact.
``onmc unwrap --managed`` removes only the onmc entries from managed-settings
without touching the project-level install.
"""

from __future__ import annotations

import json
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
from oh_no_my_claudecode.wrap.managed import (
    default_managed_path,
    load_managed_settings,
    managed_hooks_present,
    manual_install_json,
    merge_managed_hooks,
    strip_managed_hooks,
    write_managed_settings,
)
from oh_no_my_claudecode.wrap.session import is_active, read_default_active, set_active
from oh_no_my_claudecode.wrap.state import (
    remove_claude_md_stanza,
    remove_wrap_state,
    upsert_claude_md_stanza,
    write_wrap_state,
)

# ---------------------------------------------------------------------------
# /onmc slash command
# ---------------------------------------------------------------------------

_SLASH_COMMAND_NAME = "onmc.md"

# The body written to .claude/commands/onmc.md — mirrors the shape of the
# existing onmc-why.md / onmc-brief.md commands in .claude-plugin/commands/.
_SLASH_COMMAND_BODY = """\
---
description: Toggle the onmc deep-wrap session control plane on/off
allowed-tools: Bash(onmc wrap *)
---

<!-- onmc:deep-wrap:slash-command — managed by onmc wrap, removed by onmc unwrap -->

Toggle the onmc deep-wrap control plane on or off for this Claude Code session.

**ON**: all lifecycle hooks engage — memory-grounded prompts (`onmc recall`), \
Task intercept toward `onmc swarm`, live telemetry, pre-compact snapshot.

**OFF**: hooks are silent — Claude Code runs as if onmc was not installed.

## Action

!`onmc wrap toggle 2>&1 || echo "onmc not installed — run: pip install oh-no-my-claudecode"`

## Status

!`onmc wrap status 2>&1`

## Task

Report to the user: is deep-wrap now **ON** or **OFF**? One sentence on what
that means for this session. Remind them they can type /onmc again to toggle.
"""


def _slash_command_path(repo_root: Path) -> Path:
    """Return the project-scoped /onmc slash-command file path."""
    return repo_root / ".claude" / "commands" / _SLASH_COMMAND_NAME


def _write_slash_command(repo_root: Path) -> Path:
    """Write the /onmc Claude Code slash command file. Returns its path."""
    path = _slash_command_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_SLASH_COMMAND_BODY, encoding="utf-8")
    return path


def _remove_slash_command(repo_root: Path) -> bool:
    """Remove the /onmc slash command file if present. Returns whether removed."""
    path = _slash_command_path(repo_root)
    try:
        if path.is_file():
            path.unlink()
            return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _echo(message: str, *, err: bool = False) -> None:
    typer.echo(message, err=err)


def _discover_root() -> Path:
    """Discover the repo root from the current directory, raising Exit(1) on failure."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError as exc:
        typer.echo(f"onmc: not a git repository: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ---------------------------------------------------------------------------
# Managed-settings install / uninstall helpers
# ---------------------------------------------------------------------------


def _do_managed_install(*, managed_path: Path | None) -> None:
    """Write onmc wrap hooks to the managed-settings.json.

    Gracefully handles a non-writable path by printing the exact JSON to
    install manually — never attempts sudo.
    """
    mp = managed_path or default_managed_path()
    existing = load_managed_settings(mp)
    merged = merge_managed_hooks(existing)
    try:
        write_managed_settings(mp, merged)
    except PermissionError:
        _echo(
            f"onmc: cannot write to {mp} (Permission denied).",
            err=True,
        )
        _echo(
            "  Managed-settings requires admin/root for the system path.",
            err=True,
        )
        _echo("  Install manually (run as admin/root):", err=True)
        _echo(f"    sudo mkdir -p {mp.parent}", err=True)
        _echo(
            f"  Then create/merge {mp} with the following content:",
            err=True,
        )
        typer.echo(manual_install_json())
        raise typer.Exit(code=1) from None
    _echo(f"onmc managed enforcement installed: {mp}")
    _echo("  - Task intercept (PreToolUse/Task) added to managed-settings.")
    _echo("  - Prompt router (UserPromptSubmit) added to managed-settings.")
    _echo("  Users cannot override or disable these hooks.")
    _echo("  Remove anytime with: onmc unwrap --managed")


def _do_managed_uninstall(*, managed_path: Path | None) -> None:
    """Remove onmc wrap hooks from the managed-settings.json.

    Gracefully handles a non-writable path by printing instructions —
    never attempts sudo.
    """
    mp = managed_path or default_managed_path()
    existing = load_managed_settings(mp)
    stripped = strip_managed_hooks(existing)
    try:
        write_managed_settings(mp, stripped)
    except PermissionError:
        _echo(
            f"onmc: cannot write to {mp} (Permission denied).",
            err=True,
        )
        _echo("  Remove manually (run as admin/root):", err=True)
        _echo(
            f"  Edit {mp} and remove the onmc PreToolUse/Task "
            "and UserPromptSubmit hook entries.",
            err=True,
        )
        raise typer.Exit(code=1) from None
    _echo(f"onmc managed enforcement removed: {mp}")
    _echo("  - onmc hooks removed from managed-settings.")
    _echo("  Project-level install (if any) is unchanged.")


# ---------------------------------------------------------------------------
# Auto-discovery entry point
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register ``wrap`` (sub-app) and ``unwrap`` onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    wrap_app = typer.Typer(
        name="wrap",
        help=(
            "Make onmc the default layer for Claude Code; manage the session switch.\n\n"
            "Called without a sub-command: installs hooks + /onmc slash command.\n"
            "Sub-commands: on / off / toggle / status"
        ),
        invoke_without_command=True,
        no_args_is_help=False,
    )

    # ------------------------------------------------------------------ #
    # Callback — the install operation (onmc wrap [--strict] [...])       #
    # ------------------------------------------------------------------ #

    @wrap_app.callback()
    def wrap_callback(
        ctx: typer.Context,
        strict: Annotated[
            bool,
            typer.Option(
                "--strict/--soft",
                help=(
                    "strict: deny native Task spawns and redirect to `onmc swarm`. "
                    "soft: allow them with a nudge toward `onmc swarm`. Default: strict."
                ),
            ),
        ] = True,
        global_scope: Annotated[
            bool,
            typer.Option(
                "--global/--project",
                help=(
                    "Install into the user-level ~/.claude/settings.json. "
                    "Default: project-scoped .claude/settings.json."
                ),
            ),
        ] = False,
        default_active: Annotated[
            bool,
            typer.Option(
                "--default-active/--no-default-active",
                help=(
                    "Auto-activate the session switch on every SessionStart so hooks "
                    "engage immediately without an explicit `onmc wrap on` or /onmc. "
                    "Default: off (explicit toggle required)."
                ),
            ),
        ] = False,
        managed: Annotated[
            bool,
            typer.Option(
                "--managed/--no-managed",
                help=(
                    "Install hooks into the OS-level Claude Code managed-settings.json "
                    "so users cannot override or disable them (org hard-lock). "
                    "Requires admin/root for the default system path. "
                    "When the path is not writable, prints the exact JSON to install "
                    "manually — no sudo is attempted."
                ),
            ),
        ] = False,
        managed_path: Annotated[
            Path | None,
            typer.Option(
                "--managed-path",
                help=(
                    "Override the managed-settings.json path used by --managed. "
                    "Defaults to the OS-appropriate system path."
                ),
                metavar="PATH",
            ),
        ] = None,
    ) -> None:
        """Make onmc the default layer for Claude Code in this repo.

        Installs a Task intercept (PreToolUse matcher ``Task``) that redirects
        native agent-spawning to ``onmc swarm``, plus a prompt router
        (UserPromptSubmit) that nudges toward onmc paths.  Also writes the
        ``/onmc`` Claude Code slash command that toggles the deep-wrap session
        switch without leaving the editor.

        Use ``--managed`` to write the same hooks into the OS-level
        managed-settings.json for org-wide hard-lock enforcement (users cannot
        override).  Requires admin/root; if the path is not writable, the exact
        JSON to install manually is printed instead.

        Use the session sub-commands to activate/deactivate hooks:

            onmc wrap on        # activate for this session
            onmc wrap off       # deactivate for this session
            onmc wrap toggle    # flip (also called by /onmc)
            onmc wrap status    # show current state

        Reverse the install at any time with ``onmc unwrap``.
        ``onmc unwrap --managed`` removes only the managed-settings entries.
        """
        if ctx.invoked_subcommand is not None:
            # A sub-command (on/off/toggle/status) was invoked; the callback
            # must not run the install logic — return immediately.
            return

        if managed:
            _do_managed_install(managed_path=managed_path)
            return

        repo_root = _discover_root()

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
        write_wrap_state(repo_root, strict=strict, default_active=default_active)
        claude_md = upsert_claude_md_stanza(repo_root)
        slash_cmd = _write_slash_command(repo_root)

        mode = "strict" if strict else "soft"
        scope = "global" if global_scope else "project"
        _echo(f"onmc wrap active ({mode}, {scope}).")
        _echo("  - Task intercept installed (PreToolUse matcher 'Task').")
        _echo("  - Prompt router installed (UserPromptSubmit).")
        if result.backup_created:
            _echo(f"  - Backup written: {result.backup_path}")
        _echo(f"  - Policy stanza added to: {claude_md}")
        _echo(f"  - /onmc slash command: {slash_cmd}")
        if default_active:
            _echo(
                "  - default_active: ON — hooks engage automatically on every SessionStart."
            )
        else:
            _echo(
                "  - Session switch: OFF — run `onmc wrap on` or type /onmc in Claude Code."
            )
        if strict:
            _echo(
                "  Native Task spawns are now DENIED and redirected to "
                "`onmc swarm plan` (set ONMC_ALLOW_TASK=1 to bypass once)."
            )
        else:
            _echo("  Native Task spawns are allowed with a nudge toward `onmc swarm`.")
        _echo(f"  Settings: {result.settings_path}")
        _echo("  Reverse anytime with: onmc unwrap")

    # ------------------------------------------------------------------ #
    # Sub-commands — the session switch                                   #
    # ------------------------------------------------------------------ #

    @wrap_app.command("on")
    def wrap_on() -> None:
        """Activate the onmc deep-wrap session switch.

        All lifecycle hooks engage immediately: memory-grounded prompts,
        Task intercept, live telemetry, pre-compact snapshot.
        """
        repo_root = _discover_root()
        set_active(repo_root, on=True)
        _echo("onmc deep-wrap: ON")
        _echo("  All lifecycle hooks are now active for this session.")
        _echo("  Run `onmc wrap off` or type /onmc to deactivate.")

    @wrap_app.command("off")
    def wrap_off() -> None:
        """Deactivate the onmc deep-wrap session switch.

        All lifecycle hooks become silent.  Claude Code behaves as if the
        wrap layer was not installed.
        """
        repo_root = _discover_root()
        set_active(repo_root, on=False)
        _echo("onmc deep-wrap: OFF")
        _echo("  Lifecycle hooks are now silent for this session.")
        _echo("  Run `onmc wrap on` or type /onmc to reactivate.")

    @wrap_app.command("toggle")
    def wrap_toggle() -> None:
        """Toggle the onmc deep-wrap session switch.

        Activates when currently inactive; deactivates when currently active.
        This is the command invoked by the ``/onmc`` Claude Code slash command.
        """
        repo_root = _discover_root()
        current = is_active(repo_root)
        new_state = not current
        set_active(repo_root, on=new_state)
        state_label = "ON" if new_state else "OFF"
        _echo(f"onmc deep-wrap: {state_label}")
        if new_state:
            _echo("  All lifecycle hooks are now active for this session.")
        else:
            _echo("  Lifecycle hooks are now silent for this session.")
        _echo("  Type /onmc again to toggle back.")

    @wrap_app.command("status")
    def wrap_status(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Output status as JSON."),
        ] = False,
        managed_path: Annotated[
            Path | None,
            typer.Option(
                "--managed-path",
                help="Override the managed-settings.json path to check.",
                metavar="PATH",
            ),
        ] = None,
    ) -> None:
        """Show the current onmc wrap installation and session status."""
        from oh_no_my_claudecode.hooks.installer import (
            hooks_installed,
            wrap_hooks_installed,
        )
        from oh_no_my_claudecode.wrap.state import read_wrap_strict, wrap_state_path

        try:
            repo_root = discover_repo_root(Path.cwd())
        except RepoDiscoveryError:
            repo_root = Path.cwd()

        sp = project_settings_path(repo_root)
        wrap_installed = wrap_state_path(repo_root).is_file()
        wrap_hooks = wrap_hooks_installed(settings_path=sp) if sp.exists() else False
        base_hooks = hooks_installed(settings_path=sp) if sp.exists() else False
        active = is_active(repo_root)
        default_on = read_default_active(repo_root)
        mode = "strict" if read_wrap_strict(repo_root) else "soft"
        slash_cmd = _slash_command_path(repo_root).is_file()

        # Managed-settings check.
        mp = managed_path or default_managed_path()
        managed_settings = load_managed_settings(mp)
        m_present = managed_hooks_present(managed_settings)

        if as_json:
            data = {
                "wrap_installed": wrap_installed,
                "wrap_hooks": wrap_hooks,
                "base_hooks_installed": base_hooks,
                "session_active": active,
                "default_active": default_on,
                "mode": mode,
                "slash_command": slash_cmd,
                "managed_enforcement": m_present,
                "managed_path": str(mp),
            }
            _echo(json.dumps(data, indent=2))
            return

        _echo(f"onmc wrap status ({Path.cwd()}):")
        _echo(f"  wrap installed:    {'yes' if wrap_installed else 'no'}")
        _echo(f"  wrap hooks:        {'yes' if wrap_hooks else 'no'}")
        _echo(f"  base hooks:        {'yes' if base_hooks else 'no'}")
        _echo(f"  session active:    {'YES' if active else 'no'}")
        _echo(f"  default active:    {'yes' if default_on else 'no'}")
        _echo(f"  mode:              {mode}")
        _echo(f"  /onmc command:     {'installed' if slash_cmd else 'not installed'}")
        managed_label = f"YES — {mp}" if m_present else f"no  ({mp})"
        _echo(f"  managed lock:      {managed_label}")

    # ------------------------------------------------------------------ #
    # Register the sub-app and the unwrap command on the root app         #
    # ------------------------------------------------------------------ #

    app.add_typer(wrap_app, name="wrap")

    @app.command("unwrap")
    def unwrap_command(
        global_scope: Annotated[
            bool,
            typer.Option(
                "--global/--project",
                help=(
                    "Remove from the user-level ~/.claude/settings.json. "
                    "Default: project-scoped .claude/settings.json."
                ),
            ),
        ] = False,
        managed: Annotated[
            bool,
            typer.Option(
                "--managed/--no-managed",
                help=(
                    "Remove onmc entries from the OS-level managed-settings.json only, "
                    "leaving the project-level install untouched. "
                    "Requires admin/root for the default system path."
                ),
            ),
        ] = False,
        managed_path: Annotated[
            Path | None,
            typer.Option(
                "--managed-path",
                help="Override the managed-settings.json path used by --managed.",
                metavar="PATH",
            ),
        ] = None,
    ) -> None:
        """Remove the onmc wrap layer — the perfect inverse of ``onmc wrap``.

        Strips exactly the two wrap hooks, the wrap-state file, the CLAUDE.md
        policy stanza, and the ``/onmc`` slash command.  Every other hook and
        all CLAUDE.md content is left untouched.  The settings.json backup is
        kept as a safety artifact.

        Use ``--managed`` to remove only the onmc entries from the OS-level
        managed-settings.json (requires admin/root for the default system path).
        The project-level install is not touched.
        """
        if managed:
            _do_managed_uninstall(managed_path=managed_path)
            return

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
        slash_removed = _remove_slash_command(repo_root)

        _echo("onmc unwrap complete.")
        _echo(
            f"  - Wrap hooks: {'removed' if hooks_removed else 'none present'} "
            f"({settings_path})"
        )
        _echo(f"  - Wrap state: {'removed' if state_removed else 'none present'}")
        _echo(f"  - CLAUDE.md stanza: {'removed' if stanza_removed else 'none present'}")
        _echo(f"  - /onmc command: {'removed' if slash_removed else 'none present'}")
        _echo("  Native Task spawning and prompt handling are back to Claude Code defaults.")
