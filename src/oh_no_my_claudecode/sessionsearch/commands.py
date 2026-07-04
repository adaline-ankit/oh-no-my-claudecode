"""CLI surface for the ``sessionsearch`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc session-search`` ships with
**zero edits** to ``cli.py`` or any other shared hub.

``onmc session-search <query>`` performs fast full-text search across onmc's
entire persisted history (memories, attempts, tasks, memory_artifacts) using
SQLite's FTS5 engine.  Falls back to a LIKE scan when FTS5 is absent.
Raw retrieval — no LLM.  Complements ``onmc recall`` (curated-memory KNN)
with keyword search over ALL history.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.config import database_path, default_config, load_config
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.sessionsearch.index import Hit, search


def register(app: typer.Typer) -> None:
    """Register the ``onmc session-search`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("session-search")
    def session_search_command(
        query: Annotated[
            str,
            typer.Argument(help="Search query.  All alphanumeric tokens are matched (OR logic)."),
        ],
        limit: Annotated[
            int,
            typer.Option(
                "--limit",
                "-n",
                help="Maximum number of results to return.",
                min=1,
                max=500,
            ),
        ] = 20,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help=(
                    "Emit results as a JSON envelope "
                    "{\"kind\": \"session-search\", \"query\": \"...\", \"hits\": [...]} "
                    "for pipeline composition."
                ),
            ),
        ] = False,
    ) -> None:
        """Full-text search across all of onmc's persisted history.

        Searches memories, attempts, tasks, and memory_artifacts using SQLite's
        FTS5 engine (falls back to LIKE when FTS5 is absent).  Results are ranked
        by BM25 relevance and include a short snippet showing the match context.

        Complements ``onmc recall`` (semantic KNN over curated memories) by
        covering the complete history with keyword search.

        Examples:

            onmc session-search "cache invalidation"

            onmc session-search "auth bug" --limit 5

            onmc session-search "migration" --json
        """
        try:
            repo_root = discover_repo_root(Path.cwd())
        except RepoDiscoveryError:
            typer.echo("error: no git repository found from the current directory.", err=True)
            raise typer.Exit(code=1) from None

        try:
            config = load_config(repo_root)
        except FileNotFoundError:
            config = default_config(repo_root)

        db = database_path(config, repo_root)
        hits: list[Hit] = search(db, query, limit=limit)

        if as_json:
            payload = {
                "kind": "session-search",
                "query": query,
                "hits": [
                    {
                        "record_id": h.record_id,
                        "source": h.source,
                        "title": h.title,
                        "snippet": h.snippet,
                        "score": h.score,
                    }
                    for h in hits
                ],
            }
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
            return

        if not hits:
            typer.echo(f"No results for: {query!r}", err=True)
            return

        for i, hit in enumerate(hits, start=1):
            typer.echo(f"[{i}] ({hit.source}) {hit.title}")
            typer.echo(f"    {hit.snippet}")
            typer.echo(f"    id={hit.record_id}  score={hit.score:.3f}")
            if i < len(hits):
                typer.echo("")
