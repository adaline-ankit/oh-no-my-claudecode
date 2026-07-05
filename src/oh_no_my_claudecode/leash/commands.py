"""CLI surface for the ``leash`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc leash`` ships with **zero
edits** to ``cli.py`` or any other shared hub.

``onmc leash`` is a *guardrails-as-game* control surface: users define
"house rules" (with soft or hard severity), check event text against them, and
track a live compliance score.  State is stored in ``.onmc/leash/`` under the
repository root:

- ``rules.json``    — the persisted rule list.
- ``history.jsonl`` — the check event ledger (used for scoring).

This feature is DISTINCT from ``drift`` (which enforces memory-directives
against code files) and ``wrap`` (which installs live Claude Code hooks).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.leash.rules import (
    LEASH_SUBDIR,
    SEVERITY_HARD,
    SEVERITY_SOFT,
    add_rule,
    check,
    load_rules,
    load_score,
    record_check,
    remove_rule,
)

leash_app = typer.Typer(
    help=(
        "Guardrails-as-game: define session rules, check compliance, "
        "and score the agent."
    ),
    no_args_is_help=True,
)


def _resolve_leash_dir() -> Path:
    """Resolve the .onmc/leash directory from cwd, exiting cleanly if no repo."""
    try:
        repo_root = discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("Not inside a repository. Run from within your project.", err=True)
        raise typer.Exit(code=1) from None
    return repo_root / LEASH_SUBDIR


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def register(app: typer.Typer) -> None:
    """Register the ``onmc leash`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(leash_app, name="leash")


# ---------------------------------------------------------------------------
# Rule management commands
# ---------------------------------------------------------------------------


@leash_app.command("add")
def add_command(
    rule: Annotated[str, typer.Argument(help="The house rule to add.")],
    severity: Annotated[
        str,
        typer.Option(
            "--severity",
            help=(
                f"Rule severity: '{SEVERITY_SOFT}' (advisory) "
                f"or '{SEVERITY_HARD}' (triggers a buzz on violation)."
            ),
        ),
    ] = SEVERITY_SOFT,
) -> None:
    """Add a new guardrail rule to the leash.

    The rule TEXT is used both as the human-readable description and as the
    match pattern.  Patterns are tried as regexes first; if the regex is
    invalid it falls back to case-insensitive substring matching.

    Severity controls what happens on a match:

    \\b soft\\b  — advisory; violations are reported but no buzz is emitted.

    \\b hard\\b  — triggers a buzz (``buzz: true`` in JSON output) to signal
    a serious guardrail breach.

    Examples:

        onmc leash add "no console.log"

        onmc leash add "TODO" --severity hard

        onmc leash add "rm -rf" --severity hard
    """
    if severity not in {SEVERITY_SOFT, SEVERITY_HARD}:
        typer.echo(
            f"Invalid severity {severity!r}. Must be 'soft' or 'hard'.",
            err=True,
        )
        raise typer.Exit(code=1)
    leash_dir = _resolve_leash_dir()
    new_rule = add_rule(rule, severity=severity, leash_dir=leash_dir)
    typer.echo(
        f"Rule added [{new_rule.id}]: {new_rule.text!r}  "
        f"severity={new_rule.severity}  strategy={new_rule.match_strategy}"
    )


@leash_app.command("list")
def list_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit rules as a JSON envelope."),
    ] = False,
) -> None:
    """List all active guardrail rules.

    Examples:

        onmc leash list

        onmc leash list --json
    """
    leash_dir = _resolve_leash_dir()
    rules = load_rules(leash_dir=leash_dir)
    if as_json:
        typer.echo(
            json.dumps(
                {"kind": "leash_rules", "rules": [r.to_dict() for r in rules]},
                indent=2,
            )
        )
        return
    if not rules:
        typer.echo("No rules defined. Use `onmc leash add` to add one.")
        return
    for r in rules:
        typer.echo(
            f"[{r.id}]  {r.severity:4s}  {r.text!r}  "
            f"(strategy={r.match_strategy})"
        )


@leash_app.command("remove")
def remove_command(
    rule_id: Annotated[str, typer.Argument(help="The rule ID to remove.")],
) -> None:
    """Remove a guardrail rule by its ID.

    Use ``onmc leash list`` to find the rule ID.

    Examples:

        onmc leash remove rule_abc123
    """
    leash_dir = _resolve_leash_dir()
    found = remove_rule(rule_id, leash_dir=leash_dir)
    if found:
        typer.echo(f"Rule {rule_id!r} removed.")
    else:
        typer.echo(f"Rule {rule_id!r} not found.", err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Check command
# ---------------------------------------------------------------------------


@leash_app.command("check")
def check_command(
    event: Annotated[
        str,
        typer.Argument(help="Event text or action description to evaluate."),
    ],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the result as a JSON envelope."),
    ] = False,
) -> None:
    """Evaluate an event or action text against the active rules.

    Violations are reported with their rule id, severity, matched text, and
    whether a buzz is emitted (hard violations only).  The check event is
    recorded in the history ledger so ``onmc leash score`` can track the
    compliance trend.

    Examples:

        onmc leash check "I just ran rm -rf node_modules"

        onmc leash check "added a console.log for debugging" --json
    """
    leash_dir = _resolve_leash_dir()
    rules = load_rules(leash_dir=leash_dir)
    violations = check(event, rules)
    ts = _now_iso()
    record_check(event, violations, leash_dir=leash_dir, ts=ts)

    buzz = any(v.buzz for v in violations)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "leash_check",
                    "event": event,
                    "violations": [v.to_dict() for v in violations],
                    "buzz": buzz,
                },
                indent=2,
            )
        )
        return

    if not violations:
        typer.echo("Clean — no rule violations detected.")
        return

    for v in violations:
        prefix = "BUZZ" if v.buzz else "WARN"
        typer.echo(
            f"[{prefix}] Rule {v.rule_id!r} ({v.severity}) violated: "
            f"{v.rule_text!r}  matched={v.matched!r}"
        )


# ---------------------------------------------------------------------------
# Score command
# ---------------------------------------------------------------------------


@leash_app.command("score")
def score_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the score as a JSON envelope."),
    ] = False,
) -> None:
    """Show the compliance score, streak, and grade.

    Compliance is computed from all ``onmc leash check`` events recorded in
    the current session.  A ``streak`` counts consecutive clean checks from
    the most recent event backwards.

    Grade thresholds: A (≥95%), B (≥80%), C (≥60%), D (≥40%), F (<40%).
    ``N/A`` when no checks have been recorded yet.

    Examples:

        onmc leash score

        onmc leash score --json
    """
    leash_dir = _resolve_leash_dir()
    sc = load_score(leash_dir=leash_dir)

    if as_json:
        typer.echo(
            json.dumps({"kind": "leash_score", "score": sc.to_dict()}, indent=2)
        )
        return

    if sc.total_checks == 0:
        typer.echo("No checks recorded yet. Use `onmc leash check` to start scoring.")
        return

    typer.echo(
        f"Grade: {sc.grade}  "
        f"compliance={sc.compliance_pct:.1f}%  "
        f"streak={sc.streak}  "
        f"({sc.passed}/{sc.total_checks} clean)"
    )
