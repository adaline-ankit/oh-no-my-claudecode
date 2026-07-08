"""CLI surface for ``onmc commands`` — help tiering by category.

Auto-discovered via :mod:`oh_no_my_claudecode.command_registry`: this module
exposes a top-level ``register(app)`` that the registry invokes at CLI build
time, so ``onmc commands`` ships with **zero edits** to ``cli.py`` or any
other shared hub.

``onmc commands`` groups all 100+ onmc commands into human categories so
newcomers know where to start.  Default output shows Core commands and a
one-line summary per category; ``--all`` expands every category; ``--category``
filters to a single category; ``--json`` emits a machine-readable envelope.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from oh_no_my_claudecode.commands_help.core import (
    CATEGORY_MAP as _CATEGORY_MAP,
)
from oh_no_my_claudecode.commands_help.core import (
    CATEGORY_ORDER,
    group_commands,
)

# Re-export for callers that need just the map (e.g. tests).
CATEGORY_MAP = _CATEGORY_MAP

_CATEGORY_SET = frozenset(CATEGORY_ORDER)


def register(app: typer.Typer) -> None:
    """Register ``onmc commands`` onto the root Typer app.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("commands")
    def commands_command(
        all_commands: Annotated[
            bool,
            typer.Option(
                "--all",
                help="List every command under each category (not just Core).",
            ),
        ] = False,
        category: Annotated[
            str | None,
            typer.Option(
                "--category",
                help=(
                    "Show only commands in CATEGORY "
                    f"(one of: {', '.join(CATEGORY_ORDER)})."
                ),
                metavar="NAME",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help="Output as a JSON envelope for pipeline composition.",
            ),
        ] = False,
    ) -> None:
        """Browse all onmc commands grouped by category.

        Default shows Core commands and a one-line summary per category.
        Use [bold]--all[/bold] to expand every category,
        [bold]--category NAME[/bold] to filter to one, or
        [bold]--json[/bold] for machine-readable output.

        Examples:

            onmc commands

            onmc commands --all

            onmc commands --category Memory

            onmc commands --json
        """
        # Import lazily to avoid circular imports at module-init time.
        # cli.py → command_registry → this module (import time)
        # This function body only runs after cli.py is fully initialised.
        from oh_no_my_claudecode.cli import app as root_app
        from oh_no_my_claudecode.command_registry import _registered_names

        live_names = sorted(set(_registered_names(root_app)))
        grouped = group_commands(live_names)

        # ── JSON output ──────────────────────────────────────────────────
        if as_json:
            payload = {
                "total": len(live_names),
                "core": grouped.get("Core", []),
                "groups": {cat: grouped.get(cat, []) for cat in CATEGORY_ORDER},
            }
            typer.echo(json.dumps(payload, indent=2))
            return

        # ── Validate --category ──────────────────────────────────────────
        if category is not None:
            # Case-insensitive lookup for convenience.
            matched = next(
                (c for c in CATEGORY_ORDER if c.lower() == category.lower()),
                None,
            )
            if matched is None:
                typer.echo(
                    f"error: unknown category {category!r}. "
                    f"Available: {', '.join(CATEGORY_ORDER)}",
                    err=True,
                )
                raise typer.Exit(code=1)
            category = matched

        # ── Rich terminal output ─────────────────────────────────────────
        from rich.console import Console
        from rich.text import Text

        con = Console()

        categories_to_show = [category] if category else CATEGORY_ORDER
        expand = all_commands or category is not None

        for cat in categories_to_show:
            cmds = grouped.get(cat, [])
            count = len(cmds)
            is_core = cat == "Core"

            header = Text()
            header.append(cat, style="bold cyan" if is_core else "bold white")
            noun = "command" if count == 1 else "commands"
            header.append(f" — {count} {noun}", style="dim")
            con.print(header)

            if is_core or expand:
                if cmds:
                    _print_columns(con, cmds, col_width=20, cols=5)
                else:
                    con.print("  [dim](none)[/dim]")
            else:
                con.print(
                    f"  [dim]run "
                    f"[bold]onmc commands --category {cat}[/bold] "
                    f"to expand[/dim]"
                )
            con.print()

        if not category and not all_commands:
            con.print(
                "[dim]Run [bold]onmc commands --all[/bold] to list every command, "
                "or [bold]onmc commands --json[/bold] for machine-readable output.[/dim]"
            )


def _print_columns(con: object, items: list[str], col_width: int, cols: int) -> None:
    """Print *items* in a grid of *cols* columns, padded to *col_width*.

    ``con`` is a ``rich.console.Console`` instance; typed as ``object`` to
    avoid importing Rich at module level.
    """
    from rich.console import Console

    assert isinstance(con, Console)  # noqa: S101 — internal guard
    for i in range(0, len(items), cols):
        row = items[i : i + cols]
        line = "  " + "  ".join(item.ljust(col_width) for item in row).rstrip()
        con.print(line)
