"""Self-registering CLI surface for the public execution harness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.harness import RiskLevel

from .budget_modes import BudgetMode, resolve_budget_profile
from .controller import HarnessController
from .models import HarnessStatus, RunRequest


def register(app: typer.Typer) -> None:
    """Register top-level ``onmc run TASK`` through command discovery."""

    @app.command("run")
    def run_command(
        task: Annotated[str, typer.Argument(help="Task for the execution harness.")],
        plan_only: Annotated[
            bool,
            typer.Option(
                "--plan-only",
                help="Emit the deterministic plan without invoking an agent or verifier.",
            ),
        ] = False,
        execute: Annotated[
            bool,
            typer.Option(
                "--execute",
                help="Explicitly allow the harness to invoke an agent and mutate the worktree.",
            ),
        ] = False,
        agent: Annotated[
            str,
            typer.Option("--agent", help="Agent CLI: claude, codex, or opencode."),
        ] = "claude",
        model: Annotated[
            str,
            typer.Option("--model", help="Model selector passed to the chosen agent adapter."),
        ] = "default",
        verifier: Annotated[
            str,
            typer.Option("--verifier", help="Verifier command run by the existing loop engine."),
        ] = "pytest",
        max_iterations: Annotated[
            int,
            typer.Option("--max-iterations", min=1, help="Maximum loop iterations."),
        ] = 10,
        max_cost_usd: Annotated[
            float | None,
            typer.Option("--max-cost-usd", min=0.0, help="Optional agent cost ceiling in USD."),
        ] = None,
        isolate: Annotated[
            bool,
            typer.Option("--isolate", help="Run agent changes in the loop engine's worktree."),
        ] = False,
        risk: Annotated[
            str,
            typer.Option("--risk", help="Execution risk: low, medium, high, or critical."),
        ] = RiskLevel.MEDIUM.value,
        budget_mode: Annotated[
            str,
            typer.Option(
                "--budget-mode",
                help="Context budget preset: tiny, standard, or deep.",
            ),
        ] = BudgetMode.STANDARD.value,
        context_budget: Annotated[
            int | None,
            typer.Option(
                "--context-budget",
                min=1,
                help="Override the budget mode's context-token ceiling.",
            ),
        ] = None,
        resume_run_id: Annotated[
            str | None,
            typer.Option("--resume", help="Resume or inspect the durable state for a run ID."),
        ] = None,
        json_output: Annotated[
            bool,
            typer.Option("--json", help="Emit the plan and result as canonical JSON."),
        ] = False,
    ) -> None:
        """Plan safely by default, or execute ONMC's memory-grounded loop.

        Without ``--execute`` this command is plan-only and never launches an
        agent or verifier subprocess. Execution is denied unless the tool broker
        allows both declared capabilities. Durable state can be revisited with
        ``--execute --resume RUN_ID``.
        """
        if plan_only and execute:
            typer.echo("--plan-only and --execute are mutually exclusive", err=True)
            raise typer.Exit(code=2)
        if resume_run_id is not None and not execute:
            typer.echo("--resume requires --execute", err=True)
            raise typer.Exit(code=2)
        try:
            resolved_risk = RiskLevel(risk)
            resolved_mode = BudgetMode(budget_mode)
            profile = resolve_budget_profile(resolved_mode)
            resolved_budget = context_budget if context_budget is not None else profile.token_budget
            repo_root = discover_repo_root(Path.cwd())
            request = RunRequest(
                task=task,
                plan_only=plan_only or not execute,
                execute=execute,
                agent=agent,  # type: ignore[arg-type]
                model=model,
                verifier=verifier,
                max_iterations=max_iterations,
                max_cost_usd=max_cost_usd,
                isolation=isolate,
                risk=resolved_risk,
                context_budget=resolved_budget,
                budget_mode=resolved_mode,
                resume_run_id=resume_run_id,
            )
            result = HarnessController(repo_root).run(request)
        except (FileNotFoundError, RepoDiscoveryError, ValueError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc

        if json_output:
            typer.echo(json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")))
        else:
            typer.echo(result.render_text())
        if execute and result.status is not HarnessStatus.COMPLETED:
            raise typer.Exit(code=1)


__all__ = ["register"]
