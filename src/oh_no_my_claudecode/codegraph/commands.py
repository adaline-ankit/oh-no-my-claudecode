"""Self-registering ``onmc codegraph coverage`` subcommand.

Follows the auto-discovery convention: a top-level :func:`register` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time.

Unlike most self-registering features that add commands to the *root* ``app``,
this module adds a subcommand to the already-registered ``codegraph_app`` Typer
group (defined in ``cli.py``).  By the time :func:`register` is called, that
group is fully defined and the command injection is safe.

``onmc codegraph coverage`` reports the fraction of discoverable source files
that are indexed in the structural code graph, broken down by language.  It
exits 0 with the report (or 1 when no git repository can be resolved).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer


def register(app: typer.Typer) -> None:  # noqa: ARG001 — app is unused; we target codegraph_app
    """Register ``onmc codegraph coverage`` onto the ``codegraph`` sub-group.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.

    We import ``codegraph_app`` from ``cli`` here (not at module level) to avoid
    a circular-import problem: ``cli`` imports ``rendering.console`` which imports
    ``codegraph.models``, but that chain completes *before*
    ``register_feature_commands`` is called at line 7042 of ``cli.py``, so
    ``codegraph_app`` is fully constructed by the time this function executes.
    """
    # Late import — safe because cli.codegraph_app is defined before
    # register_feature_commands is called at module scope in cli.py.
    from oh_no_my_claudecode.cli import codegraph_app  # noqa: PLC0415

    @codegraph_app.command("coverage")
    def codegraph_coverage_command(
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit the coverage report as JSON."),
        ] = False,
        repo: Annotated[
            Path | None,
            typer.Option(
                "--repo",
                help="Repository root (defaults to the current git repo root).",
                show_default=False,
            ),
        ] = None,
    ) -> None:
        """Show code graph coverage: indexed vs. discoverable source files.

        Walks the filesystem to count every source file the graph *could* index
        (``*.py`` plus tree-sitter languages when the extra is installed) and
        compares that against what was actually indexed.  Highlights any
        languages present in the repo that are being silently skipped because
        the ``tree-sitter`` extra is absent.

        Purely informational: exits 0 with the coverage report. Exits 1 only
        when no git repository can be resolved (run from inside your project
        or pass ``--repo``).

        Examples:

            onmc codegraph coverage

            onmc codegraph coverage --json
        """
        from oh_no_my_claudecode.codegraph.coverage import (  # noqa: PLC0415
            codegraph_coverage,
            emit_coverage_warning,
        )
        from oh_no_my_claudecode.codegraph.models import CodeGraph  # noqa: PLC0415
        from oh_no_my_claudecode.core.repo import (  # noqa: PLC0415
            RepoDiscoveryError,
            discover_repo_root,
        )

        # Resolve repo root.
        if repo is not None:
            repo_root = repo.resolve()
        else:
            try:
                repo_root = discover_repo_root(Path.cwd())
            except RepoDiscoveryError:
                typer.echo(
                    "error: not a git repository — run from inside your project or pass --repo.",
                    err=True,
                )
                raise typer.Exit(code=1) from None

        # Load existing graph from cache if available (best-effort, no rebuild).
        from oh_no_my_claudecode.core.service import OnmcService  # noqa: PLC0415

        graph: CodeGraph | None = None
        try:
            svc = OnmcService(repo_root)
            graph = svc._load_or_build_codegraph()  # noqa: SLF001
        except Exception:  # noqa: BLE001,S110 — cache miss or init failure is non-fatal
            graph = None

        report = codegraph_coverage(repo_root, graph)

        if json_output:
            sys.stdout.write(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n")
            return

        emit_coverage_warning(report)
