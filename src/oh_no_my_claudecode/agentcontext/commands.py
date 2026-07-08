"""CLI surface for ``onmc context`` — auto-discovered.

Follows the auto-discovery convention: a top-level :func:`register` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time, so ``onmc context`` ships with **zero edits** to
``cli.py`` or any other shared hub.

``onmc context <file>`` gives a coding agent a one-shot snapshot of a file:

1. **Blast radius** — dependents (files that import it), imports (files it
   depends on), and test files — sourced from the cached structural code graph
   (``onmc codegraph build`` populates the cache).

2. **Relevant memory** — onmc memories whose source ref or tags mention the
   file, drawn from the repo memory store.

When the file is not yet in the code graph the command says so and suggests
running ``onmc codegraph build`` rather than crashing.

Examples::

    onmc context src/mypackage/cache.py
    onmc context src/mypackage/cache.py --limit 5
    onmc context src/mypackage/cache.py --json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.agentcontext.build import build_context
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

# Rich console — same singleton used throughout the codebase.
try:
    from rich.table import Table

    from oh_no_my_claudecode.rendering.console import console

    _RICH = True
except ImportError:  # pragma: no cover — rich is always installed in prod
    _RICH = False


def _render_context(ctx: AgentContext) -> None:  # type: ignore[name-defined]  # noqa: F821
    """Render an :class:`~oh_no_my_claudecode.agentcontext.build.AgentContext`."""
    if not _RICH:
        typer.echo(json.dumps(ctx.to_dict(), indent=2))
        return

    br = ctx.blast_radius
    console.print(f"[bold]Context for[/bold] [cyan]{ctx.file}[/cyan]")
    console.print()

    # --- Blast radius section ---
    console.print("[bold]Blast radius[/bold]")
    if not br.in_graph:
        console.print(
            "[yellow]File not found in the code graph.[/yellow] "
            "Run [bold]onmc codegraph build[/bold] to index this repo first."
        )
    else:
        table = Table(show_header=True)
        table.add_column("Relation", style="bold", width=12)
        table.add_column("Files", no_wrap=False)
        for label, files in (
            ("dependents", br.dependents),
            ("imports", br.imports),
            ("tests", br.tests),
        ):
            table.add_row(label, "\n".join(files) if files else "[dim]—[/dim]")
        console.print(table)

    console.print()

    # --- Memory section ---
    console.print("[bold]Relevant memory[/bold]")
    if not ctx.memory:
        console.print("[dim]No relevant memories found.[/dim]")
    else:
        mem_table = Table(show_header=True)
        mem_table.add_column("kind", style="dim", width=18)
        mem_table.add_column("title", no_wrap=False)
        mem_table.add_column("id", style="dim", width=14)
        for hit in ctx.memory:
            short_id = hit.id[:12] + "…" if len(hit.id) > 12 else hit.id
            mem_table.add_row(hit.kind, hit.title, short_id)
        console.print(mem_table)


def register(app: typer.Typer) -> None:
    """Register the ``onmc context`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    from oh_no_my_claudecode.agentcontext.build import AgentContext  # noqa: PLC0415

    @app.command("context")
    def context_command(
        file: Annotated[
            str,
            typer.Argument(
                help=(
                    "Repo-relative or absolute path of the file to inspect "
                    "(e.g. src/mypackage/cache.py)."
                )
            ),
        ],
        limit: Annotated[
            int,
            typer.Option(
                "--limit",
                help="Maximum number of memory entries to show (default 8).",
            ),
        ] = 8,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help=(
                    'Emit machine-readable JSON: '
                    '{"kind":"context","file":str,'
                    '"blast_radius":{...},"memory":[...]}.'
                ),
            ),
        ] = False,
    ) -> None:
        """Show codegraph blast radius and relevant memory for a file.

        Combines two signals a coding agent needs before editing a file:

        \b
        1. Blast radius — dependents (files that import it), imports (files it
           depends on), and test files — from the structural code graph.
        2. Relevant memory — onmc memories whose tags or source ref mention the
           file.

        When the file is not yet indexed, suggests running
        ``onmc codegraph build`` rather than crashing.

        Examples:

            onmc context src/mypackage/cache.py

            onmc context src/mypackage/cache.py --limit 5

            onmc context src/mypackage/cache.py --json
        """
        from oh_no_my_claudecode.core.service import OnmcService  # noqa: PLC0415

        try:
            discover_repo_root(Path.cwd())
        except RepoDiscoveryError:
            typer.echo("error: not a git repository — run from inside your project.", err=True)
            raise typer.Exit(code=1) from None

        svc = OnmcService()

        # Normalise file path to repo-relative if absolute.
        file_arg = file
        try:
            abs_file = Path(file_arg).resolve()
            repo_root = discover_repo_root(Path.cwd())
            try:
                rel = abs_file.relative_to(repo_root)
                file_key = str(rel).replace("\\", "/")
            except ValueError:
                file_key = file_arg
        except Exception:  # noqa: BLE001 — resolution failure is non-fatal
            file_key = file_arg

        # Blast radius via codegraph (builds cache on demand if missing).
        from oh_no_my_claudecode.codegraph.models import Neighbors  # noqa: PLC0415

        try:
            nbrs = svc.codegraph_neighbors(file_key)
        except Exception:  # noqa: BLE001 — codegraph load failure is non-fatal
            nbrs = Neighbors(target=file_key)

        # Relevant memory — search by file path tokens.
        try:
            memory_entries = svc.search_memories([file_key])
        except Exception:  # noqa: BLE001 — memory load failure is non-fatal
            memory_entries = []

        ctx: AgentContext = build_context(
            file=file_key,
            neighbors=nbrs,
            memory_entries=memory_entries,
            limit=limit,
        )

        if as_json:
            typer.echo(json.dumps(ctx.to_dict(), indent=2, sort_keys=True))
            return

        _render_context(ctx)
