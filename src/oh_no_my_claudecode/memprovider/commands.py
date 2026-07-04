"""CLI surface for the ``memprovider`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc memprovider`` ships with
**zero edits** to ``cli.py`` or any other shared hub.

Subcommands
-----------
``onmc memprovider list [--json]``
    List all registered memory providers with their availability status.

``onmc memprovider search <query> [--provider <name>] [--limit N] [--json]``
    Query across available providers (or a specific provider) and print
    attributed hits.  Providers that are unavailable are skipped silently.

Both subcommands support ``--json`` for machine consumption.
Output is deterministic.  Never asserts Rich ``--help`` text.
"""

from __future__ import annotations

import json
import sys
from typing import Annotated

import typer

from oh_no_my_claudecode.memprovider.base import get_registry

memprovider_app = typer.Typer(
    help=(
        "Manage and query external memory providers that augment onmc's built-in store "
        "(mem0, supermemory, builtin). Providers run alongside the built-in store — "
        "they never replace it."
    ),
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Register the ``onmc memprovider`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(memprovider_app, name="memprovider")


# ---------------------------------------------------------------------------
# onmc memprovider list
# ---------------------------------------------------------------------------


@memprovider_app.command("list")
def memprovider_list(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit a JSON envelope instead of human-readable text."),
    ] = False,
) -> None:
    """List all registered memory providers and their availability.

    The ``builtin`` provider (backed by onmc's own SQLite store) is always
    listed first and is always available.  Optional providers (mem0,
    supermemory) report ``available: false`` when their dependency or API key
    is absent.

    Examples:

        onmc memprovider list

        onmc memprovider list --json
    """
    registry = get_registry()
    providers = registry.providers

    rows = [
        {
            "name": p.name,
            "available": p.available(),
        }
        for p in providers
    ]

    if as_json:
        payload = json.dumps(
            {"kind": "memprovider_list", "providers": rows}, indent=2, sort_keys=True
        )
        typer.echo(payload)
        return

    typer.echo(f"{'PROVIDER':<20} {'AVAILABLE'}")
    typer.echo("-" * 32)
    for row in rows:
        status = "yes" if row["available"] else "no"
        typer.echo(f"{row['name']:<20} {status}")


# ---------------------------------------------------------------------------
# onmc memprovider search
# ---------------------------------------------------------------------------


@memprovider_app.command("search")
def memprovider_search(
    query: Annotated[
        str,
        typer.Argument(help="Free-text search query."),
    ],
    provider: Annotated[
        str | None,
        typer.Option(
            "--provider",
            "-p",
            help="Restrict search to this provider name (e.g. 'builtin', 'mem0').",
            metavar="NAME",
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-n",
            help="Maximum hits per provider.",
            min=1,
            max=100,
        ),
    ] = 10,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit a JSON envelope instead of human-readable text."),
    ] = False,
) -> None:
    """Search across available memory providers and print attributed hits.

    Results from each available provider are merged and attributed via the
    ``provider`` field.  Use ``--provider`` to restrict to a single backend.

    Providers that are unavailable (missing dependency or API key) are silently
    skipped unless named explicitly via ``--provider``.

    Examples:

        onmc memprovider search "cache invalidation"

        onmc memprovider search "auth bug" --provider builtin --json

        onmc memprovider search "ETF allocation" --provider mem0 --limit 5
    """
    registry = get_registry()

    try:
        hits = registry.search(query, provider=provider, limit=limit)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "memprovider_search",
                    "query": query,
                    "provider": provider,
                    "hits": [h.to_dict() for h in hits],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if not hits:
        typer.echo("No results found.", err=True)
        return

    for hit in hits:
        typer.echo(f"[{hit.provider_name}] (score={hit.score:.3f})")
        # Indent content for readability
        for line in hit.content.splitlines():
            typer.echo(f"  {line}")
        if hit.metadata:
            meta_str = ", ".join(f"{k}={v!r}" for k, v in hit.metadata.items() if v)
            if meta_str:
                typer.echo(f"  meta: {meta_str}", file=sys.stderr)
        typer.echo("")
