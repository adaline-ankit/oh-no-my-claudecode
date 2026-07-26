"""CLI surface for the ``mission`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc mission`` ships with **zero
edits** to ``cli.py`` or any other shared hub.  Rendering is done inline here.

``onmc mission "<goal>"`` composes the shipped engineering pipeline
(recall/guard → pack → codegraph → typed harness plan) into one mission plan.
The default is plan mode: a deterministic dry-run that spawns no agents.
``--execute`` delegates to the real verifier-backed ONMC harness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.mission.pipeline import (
    DEFAULT_CONCURRENCY,
    render_mission_markdown,
    run_mission,
)
from oh_no_my_claudecode.pack.builder import DEFAULT_BUDGET
from oh_no_my_claudecode.pack.readiness import brain_readiness_warnings


def register(app: typer.Typer) -> None:
    """Register the ``onmc mission`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("mission")
    def mission_command(
        goal: Annotated[
            str,
            typer.Argument(help="The mission goal — what you want done."),
        ],
        execute: Annotated[
            bool,
            typer.Option(
                "--execute",
                help="Run the verifier-backed harness. Default is a safe dry-run.",
            ),
        ] = False,
        concurrency: Annotated[
            int,
            typer.Option(
                "--concurrency",
                min=1,
                help="Deprecated compatibility option; ignored by Mission execution.",
            ),
        ] = DEFAULT_CONCURRENCY,
        budget: Annotated[
            int,
            typer.Option("--budget", min=400, help="Context-pack markdown character budget."),
        ] = DEFAULT_BUDGET,
        agent: Annotated[
            str,
            typer.Option("--agent", help="Agent CLI: claude, codex, or opencode."),
        ] = "claude",
        model: Annotated[
            str,
            typer.Option("--model", help="Model selector passed to the chosen agent."),
        ] = "default",
        verifier: Annotated[
            str,
            typer.Option("--verifier", help="Verifier command that defines task completion."),
        ] = "pytest",
        max_iterations: Annotated[
            int,
            typer.Option("--max-iterations", min=1, help="Maximum agent loop iterations."),
        ] = 10,
        max_cost_usd: Annotated[
            float | None,
            typer.Option("--max-cost-usd", min=0.0, help="Optional run cost ceiling in USD."),
        ] = None,
        isolate: Annotated[
            bool,
            typer.Option(
                "--isolate/--no-isolate",
                help="Execute in an isolated git worktree (default: enabled).",
            ),
        ] = True,
        risk: Annotated[
            str,
            typer.Option("--risk", help="Execution risk: low, medium, high, or critical."),
        ] = "medium",
        context_budget: Annotated[
            int,
            typer.Option(
                "--context-budget",
                min=1,
                help="Maximum retrieved-context token budget for the harness.",
            ),
        ] = 4_000,
        budget_mode: Annotated[
            str,
            typer.Option("--budget-mode", help="Retrieval preset: tiny, standard, or deep."),
        ] = "standard",
        resume_run_id: Annotated[
            str | None,
            typer.Option("--resume", help="Resume the durable state for a matching run ID."),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the mission plan as JSON instead of markdown."),
        ] = False,
        strict: Annotated[
            bool,
            typer.Option(
                "--strict",
                help=(
                    "Refuse to run the mission when the brain is unready "
                    "(never ingested or repo-file index empty). "
                    "Without --strict a warning is printed to stderr and the "
                    "mission proceeds (possibly unreliable)."
                ),
            ),
        ] = False,
    ) -> None:
        """Plan safely or run the verifier-backed engineering harness.

        Composes recorded dead-ends (guard) + a deterministic context pack +
        the code-graph blast radius + a typed execution contract. Plan mode
        spawns no agents; ``--execute`` launches the selected agent through the
        shared ONMC harness and requires verifier-backed proof.
        """
        from oh_no_my_claudecode.harness import RiskLevel
        from oh_no_my_claudecode.harness_run.budget_modes import BudgetMode

        service = OnmcService(Path.cwd())
        try:
            repo_root, _config, storage = service._load_context()
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        warnings = brain_readiness_warnings(storage)
        if warnings:
            typer.echo(
                "WARNING: brain may be unready — mission context could be unreliable.", err=True
            )
            for w in warnings:
                typer.echo(f"  • {w}", err=True)
            if strict:
                typer.echo(
                    "Refusing to run mission (--strict). Run `onmc ingest` then retry.",
                    err=True,
                )
                raise typer.Exit(code=1)

        if agent not in {"claude", "codex", "opencode"}:
            typer.echo("agent must be claude, codex, or opencode", err=True)
            raise typer.Exit(code=2)
        try:
            resolved_risk = RiskLevel(risk)
            resolved_budget_mode = BudgetMode(budget_mode)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
        if resume_run_id is not None and not execute:
            typer.echo("--resume requires --execute", err=True)
            raise typer.Exit(code=2)

        plan = run_mission(
            storage,
            repo_root,
            goal,
            budget=budget,
            execute=execute,
            concurrency=concurrency,
            agent=agent,  # type: ignore[arg-type]
            model=model,
            verifier=verifier,
            max_iterations=max_iterations,
            max_cost_usd=max_cost_usd,
            isolate=isolate,
            risk=resolved_risk,
            context_budget=context_budget,
            budget_mode=resolved_budget_mode,
            resume_run_id=resume_run_id,
        )

        if as_json:
            typer.echo(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        else:
            typer.echo(render_mission_markdown(plan))

        if execute and plan.harness is not None and plan.harness.get("status") != "completed":
            raise typer.Exit(code=1)
