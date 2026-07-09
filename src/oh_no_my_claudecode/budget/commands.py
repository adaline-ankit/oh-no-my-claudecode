"""CLI surface for the ``budget`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): a top-level ``register(app)`` that the registry invokes
at CLI build time, so ``onmc budget`` ships with **zero edits** to ``cli.py`` or
any other shared hub.

``onmc budget`` is the enforcement guardian — it BLOCKS new runs when spend
crosses a hard cap and warns early at a threshold. It is distinct from
``onmc cost`` (a read-only spend breakdown/forecast, whose receipt compiler this
feature reuses) and ``onmc membudget`` (a memory-store *byte* budget).

The pure decision logic lives in :mod:`oh_no_my_claudecode.budget.guard`; this
layer only resolves the repo root, loads/saves config, renders, sets the exit
code, and optionally pushes a notify alert.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.budget.config import (
    DEFAULT_WARN_RATIO,
    DEFAULT_WINDOW,
    VALID_WINDOWS,
    load_budget_config,
    set_cap,
)
from oh_no_my_claudecode.budget.guard import BudgetDecision, check_budget
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

budget_app = typer.Typer(
    help=(
        "Token/cost guardian: enforce a hard spend cap across sessions, warn "
        "early, and block new runs when over budget."
    ),
    no_args_is_help=True,
)

#: Colour per state for Rich rendering.
_STATE_COLOR = {"ok": "green", "warn": "yellow", "blocked": "red"}


def register(app: typer.Typer) -> None:
    """Register the ``onmc budget`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(budget_app, name="budget")


def _resolve_repo_root() -> Path:
    """Resolve the repo root from cwd, exiting cleanly (code 1) if not in a repo."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("error: no git repository found from the current directory.", err=True)
        raise typer.Exit(code=1) from None


def _decision_to_dict(decision: BudgetDecision) -> dict[str, object]:
    """Serialise a :class:`BudgetDecision` to a plain JSON-safe dict."""
    return {
        "allowed": decision.allowed,
        "spend_usd": decision.spend_usd,
        "cap_usd": decision.cap_usd,
        "ratio": decision.ratio,
        "state": decision.state,
        "window": decision.window,
        "reason": decision.reason,
    }


def _render_decision(decision: BudgetDecision) -> None:
    """Render a decision as coloured, human-readable text (Rich when available)."""
    cap_str = f"${decision.cap_usd:.2f}" if decision.cap_usd is not None else "unlimited"
    pct = f"{decision.ratio:.0%}" if decision.cap_usd is not None else "n/a"
    color = _STATE_COLOR.get(decision.state, "white")

    try:
        from rich.console import Console

        console = Console()
        console.print(f"onmc budget  [[{color}]{decision.state.upper()}[/{color}]]")
        console.print(f"  window : {decision.window}")
        console.print(f"  spend  : ${decision.spend_usd:.2f}")
        console.print(f"  cap    : {cap_str}")
        console.print(f"  used   : {pct}")
        console.print(f"  reason : [{color}]{decision.reason}[/{color}]")
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        typer.echo(f"onmc budget  [{decision.state.upper()}]")
        typer.echo(f"  window : {decision.window}")
        typer.echo(f"  spend  : ${decision.spend_usd:.2f}")
        typer.echo(f"  cap    : {cap_str}")
        typer.echo(f"  used   : {pct}")
        typer.echo(f"  reason : {decision.reason}")


def _maybe_notify(repo_root: Path, decision: BudgetDecision) -> None:
    """Push a warn/block alert via the notify sinks. Exception-safe (never raises)."""
    if decision.state == "ok":
        return
    try:
        from oh_no_my_claudecode.notify import (
            EventKind,
            EventSeverity,
            NotifyEvent,
            emit_event,
        )

        if decision.state == "blocked":
            kind = EventKind.DANGER_BLOCKED
            severity = EventSeverity.FAILURE
            title = "onmc budget: HARD CAP reached — new runs blocked"
        else:
            kind = EventKind.GENERIC
            severity = EventSeverity.APPROVAL
            title = "onmc budget: spend nearing cap"
        emit_event(
            repo_root,
            NotifyEvent(kind=kind, title=title, severity=severity, detail=decision.reason),
        )
    except Exception:  # noqa: BLE001, S110 - notification must never break the gate
        pass


@budget_app.command("status")
def status_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the decision as JSON."),
    ] = False,
) -> None:
    """Show current spend, cap, ratio, and budget state.

    Reads ``.onmc/budget.json`` and the run receipts, sums spend over the
    configured rolling window (reusing ``onmc cost``'s compiler), and prints the
    state. Never changes the exit code — use ``onmc budget check`` to gate a
    hook. When no cap is configured, reports an "unlimited" OK state.
    """
    repo_root = _resolve_repo_root()
    decision = check_budget(repo_root)
    if as_json:
        typer.echo(json.dumps(_decision_to_dict(decision)))
        return
    _render_decision(decision)


@budget_app.command("set")
def set_command(
    cap_usd: Annotated[
        float,
        typer.Option("--cap-usd", help="Hard spend cap in USD. Use a negative value to disable."),
    ],
    window: Annotated[
        str,
        typer.Option(
            "--window",
            help="Rolling window to sum spend over: day | week | all.",
        ),
    ] = DEFAULT_WINDOW,
    warn_ratio: Annotated[
        float,
        typer.Option(
            "--warn-ratio",
            help="Fraction of the cap at which to warn (0.0-1.0). Default 0.8.",
        ),
    ] = DEFAULT_WARN_RATIO,
) -> None:
    """Set the hard cap, window, and early-warning ratio.

    Persists to ``.onmc/budget.json`` (creating ``.onmc/`` as needed). A
    negative ``--cap-usd`` disables the guard (unlimited). Idempotent: setting
    the same values twice yields an identical file.
    """
    repo_root = _resolve_repo_root()
    if window not in VALID_WINDOWS:
        typer.echo(
            f"error: --window must be one of {', '.join(VALID_WINDOWS)}.",
            err=True,
        )
        raise typer.Exit(code=1)
    path = set_cap(repo_root, cap_usd, window, warn_ratio)
    config = load_budget_config(repo_root)
    cap_label = f"${config.cap_usd:.2f}" if config.cap_usd is not None else "unlimited"
    typer.echo(
        f"budget cap set: {cap_label} over the {config.window} window "
        f"(warn at {config.warn_ratio:.0%}) -> {path}"
    )


@budget_app.command("check")
def check_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the decision as JSON."),
    ] = False,
    notify: Annotated[
        bool,
        typer.Option("--notify", help="Push a warn/block alert via the notify sinks."),
    ] = False,
) -> None:
    """Gate a run against the budget — exits non-zero when blocked.

    Intended for a pre-run hook or CI step: when the state is ``blocked`` the
    command exits 1 so the caller can refuse to start a new run. ``ok`` and
    ``warn`` states exit 0. With ``--notify``, a warn or block alert is pushed
    through the configured notify sink(s). When no cap is configured, the guard
    is off and this always allows (exit 0).
    """
    repo_root = _resolve_repo_root()
    decision = check_budget(repo_root)

    if notify:
        _maybe_notify(repo_root, decision)

    if as_json:
        typer.echo(json.dumps(_decision_to_dict(decision)))
    else:
        _render_decision(decision)

    if not decision.allowed:
        raise typer.Exit(code=1)
