"""Self-registering ``onmc codeindex`` subcommand group.

Auto-discovered by :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
via the top-level :func:`register` callable.

Subcommands
-----------
``onmc codeindex build``
    Atomic full rebuild of the code-intelligence index.

``onmc codeindex update <path>``
    Incremental one-file update (no-ops if blob SHA unchanged).

``onmc codeindex stats``
    Print index statistics (chunks, edges, languages, build timestamp).

``onmc codeindex query <symbol>``
    Look up a symbol by name and print its chunks.

All subcommands accept ``--json`` for machine-readable output and
``--repo`` to override the repository root.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer


def register(app: typer.Typer) -> None:
    """Register the ``codeindex`` command group onto *app*.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    codeindex_app = typer.Typer(
        name="codeindex",
        help="Incremental code-intelligence index (blob-SHA keyed, AST chunks).",
        no_args_is_help=True,
    )
    app.add_typer(codeindex_app, name="codeindex")

    # ------------------------------------------------------------------
    # Shared repo-root resolver
    # ------------------------------------------------------------------

    def _resolve_repo(repo: Path | None) -> Path:
        from oh_no_my_claudecode.core.repo import (  # noqa: PLC0415
            RepoDiscoveryError,
            discover_repo_root,
        )

        if repo is not None:
            return repo.resolve()
        try:
            return discover_repo_root(Path.cwd())
        except RepoDiscoveryError:
            typer.echo(
                "error: not a git repository — run from inside your project or pass --repo.",
                err=True,
            )
            raise typer.Exit(code=1) from None

    # ------------------------------------------------------------------
    # onmc codeindex build
    # ------------------------------------------------------------------

    @codeindex_app.command("build")
    def build_command(
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit stats as JSON."),
        ] = False,
        repo: Annotated[
            Path | None,
            typer.Option("--repo", help="Repository root.", show_default=False),
        ] = None,
        quiet: Annotated[
            bool,
            typer.Option("--quiet", "-q", help="Suppress progress output."),
        ] = False,
    ) -> None:
        """Atomically rebuild the full code-intelligence index.

        Walks all indexable source files, chunks them by AST symbols, and
        stores chunks + edges in ``.onmc/codeindex.db``.  Unchanged files
        are always re-indexed during a full build (use ``update`` for
        incremental).

        Exits 0 on success with a stats summary, 1 on error.

        Examples:

            onmc codeindex build

            onmc codeindex build --json

            onmc codeindex build --repo /path/to/project
        """
        from oh_no_my_claudecode.codeindex.builder import build  # noqa: PLC0415
        from oh_no_my_claudecode.codeindex.query import stats  # noqa: PLC0415
        from oh_no_my_claudecode.codeindex.store import open_store  # noqa: PLC0415

        repo_root = _resolve_repo(repo)
        if not quiet and not json_output:
            typer.echo(f"Building code index for {repo_root} …", err=True)

        try:
            store = open_store(repo_root)
            build(repo_root, store=store)
            index_stats = stats(store)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        if json_output:
            sys.stdout.write(json.dumps(index_stats.to_dict(), indent=2, sort_keys=True) + "\n")
            return

        typer.echo(
            f"done — {index_stats.total_chunks} chunks, "
            f"{index_stats.total_edges} edges, "
            f"{index_stats.total_files} files"
        )

    # ------------------------------------------------------------------
    # onmc codeindex update <path>
    # ------------------------------------------------------------------

    @codeindex_app.command("update")
    def update_command(
        changed_path: Annotated[
            str,
            typer.Argument(help="Repo-relative path of the file to re-index."),
        ],
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit result as JSON."),
        ] = False,
        repo: Annotated[
            Path | None,
            typer.Option("--repo", help="Repository root.", show_default=False),
        ] = None,
    ) -> None:
        """Incrementally update one file in the code index.

        Re-chunks *path* only if its git blob SHA has changed since the last
        index.  If the file is unchanged the command exits 0 with no output.

        Exits 0 on success, 1 on error.

        Examples:

            onmc codeindex update src/cache.py

            onmc codeindex update src/cache.py --json
        """
        from oh_no_my_claudecode.codeindex.builder import update  # noqa: PLC0415
        from oh_no_my_claudecode.codeindex.store import open_store  # noqa: PLC0415

        repo_root = _resolve_repo(repo)
        try:
            store = open_store(repo_root)
            changed = update(repo_root, changed_path, store=store)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        if json_output:
            sys.stdout.write(json.dumps({"updated": changed, "path": changed_path}) + "\n")
            return

        if changed:
            typer.echo(f"updated: {changed_path}")

    # ------------------------------------------------------------------
    # onmc codeindex stats
    # ------------------------------------------------------------------

    @codeindex_app.command("stats")
    def stats_command(
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit stats as JSON."),
        ] = False,
        repo: Annotated[
            Path | None,
            typer.Option("--repo", help="Repository root.", show_default=False),
        ] = None,
    ) -> None:
        """Print code index statistics.

        Shows chunk and edge counts, file count, language breakdown, and the
        HEAD commit SHA at last build.  Exits 1 when no index has been built
        yet.

        Examples:

            onmc codeindex stats

            onmc codeindex stats --json
        """
        from oh_no_my_claudecode.codeindex.query import stats  # noqa: PLC0415
        from oh_no_my_claudecode.codeindex.store import open_store  # noqa: PLC0415

        repo_root = _resolve_repo(repo)
        store = open_store(repo_root)

        if not store.path_exists():
            typer.echo("no index found — run: onmc codeindex build", err=True)
            raise typer.Exit(code=1)

        index_stats = stats(store)

        if json_output:
            sys.stdout.write(json.dumps(index_stats.to_dict(), indent=2, sort_keys=True) + "\n")
            return

        typer.echo(f"chunks       : {index_stats.total_chunks}")
        typer.echo(f"edges        : {index_stats.total_edges}")
        typer.echo(f"files        : {index_stats.total_files}")
        typer.echo(f"stale chunks : {index_stats.stale_chunks}")
        typer.echo(f"commit       : {index_stats.commit_sha or '(unknown)'}")
        typer.echo(f"built at     : {index_stats.built_at or '(unknown)'}")
        if index_stats.languages:
            typer.echo("languages    :")
            for lang, cnt in sorted(index_stats.languages.items()):
                typer.echo(f"  {lang:<12} {cnt}")

    # ------------------------------------------------------------------
    # onmc codeindex query <symbol>
    # ------------------------------------------------------------------

    @codeindex_app.command("query")
    def query_command(
        symbol: Annotated[
            str,
            typer.Argument(help="Symbol name (exact) or substring to search."),
        ],
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit results as JSON."),
        ] = False,
        exact: Annotated[
            bool,
            typer.Option("--exact", help="Exact symbol match (default: substring)."),
        ] = False,
        repo: Annotated[
            Path | None,
            typer.Option("--repo", help="Repository root.", show_default=False),
        ] = None,
    ) -> None:
        """Look up a symbol by name and print its indexed chunks.

        By default performs a case-insensitive substring search.  Pass
        ``--exact`` for an exact-match lookup.

        Exits 0 with results (or empty), 1 on error.

        Examples:

            onmc codeindex query invalidate_cache

            onmc codeindex query cache --json

            onmc codeindex query MyClass.method --exact
        """
        from oh_no_my_claudecode.codeindex import query as q  # noqa: PLC0415
        from oh_no_my_claudecode.codeindex.store import open_store  # noqa: PLC0415

        repo_root = _resolve_repo(repo)
        store = open_store(repo_root)

        chunks = q.get_symbol(store, symbol) if exact else q.search_symbols(store, symbol)

        if json_output:
            sys.stdout.write(
                json.dumps([c.to_dict() for c in chunks], indent=2, sort_keys=True) + "\n"
            )
            return

        if not chunks:
            typer.echo(f"no chunks found for '{symbol}'")
            return

        for chunk in chunks:
            typer.echo(
                f"{chunk.path}:{chunk.start_line}-{chunk.end_line}  "
                f"[{chunk.kind}] {chunk.symbol}"
            )
