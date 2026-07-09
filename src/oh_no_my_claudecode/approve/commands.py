"""CLI surface for the ``approve`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): a top-level ``register(app)``
callable the registry invokes at CLI build time.  No shared hub is touched —
**zero** edits to ``cli.py``.

``onmc approve <SWARM_ID> <MESSAGE>`` is the executor that closes the
phone-to-merge loop.  It:

1. builds the swarm's trust card (reusing ``missionbridge.card.build_card``),
2. parses the chat *message* into an action (reusing
   ``missionbridge.approve.parse_action``),
3. plans which units the action is allowed to merge (pure
   :func:`~oh_no_my_claudecode.approve.executor.plan_approval`), and
4. executes the plan — DRY by default (plan only), or for real with
   ``--execute``.

The real merger wraps the existing ``land`` driver (merge an already-open PR)
and honestly reports verified units that still need a PR opened first
(``onmc swarm pr``).  It re-checks the verified gate at execution time, so a
held / unverified unit can never be merged even if state changed under it.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.approve.executor import (
    ApprovalPlan,
    ExecutionResult,
    MergeOutcome,
    Merger,
    execute_plan,
    plan_approval,
)
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.missionbridge.approve import parse_action
from oh_no_my_claudecode.missionbridge.card import build_card

#: Extract a PR number from a ``gh``-style PR URL (``.../pull/123``).
_PR_NUMBER_RE = re.compile(r"/pull/(\d+)\b")


def _repo_root() -> Path:
    """Resolve the onmc repo root from the cwd, or exit cleanly if outside one."""
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo(
            "Not inside an onmc repository (no repo root found). Run from your project.",
            err=True,
        )
        raise typer.Exit(code=1) from None


def _pr_number(pr_url: str) -> int | None:
    """Parse the PR number out of a PR URL, or ``None`` when it has no number."""
    match = _PR_NUMBER_RE.search(pr_url)
    return int(match.group(1)) if match is not None else None


def _real_merger(repo_root: Path, swarm_id: str, unit_id: str) -> MergeOutcome:
    """Perform the real, outward-facing merge for one verified unit.

    Re-reads the trust card and RE-CHECKS the verified gate before acting — the
    plan was pure, but state may have changed, and the accountability guarantee
    is that a non-verified unit is never merged.  When the unit has an open PR it
    is squash-merged via the ``land`` driver; a verified unit without a PR is
    reported (open one first with ``onmc swarm pr``) rather than guessed at.
    """
    card = build_card(repo_root, swarm_id)
    unit = next((u for u in card.units if u.unit_id == unit_id), None)
    if unit is None:
        return MergeOutcome(unit_id, ok=False, detail="unit vanished from swarm state")

    # Execution-time trust gate — mirrors executor._is_eligible.  Never merge a
    # unit that is not a verified success, even if the plan predated a change.
    if not (unit.verified and not unit.held):
        return MergeOutcome(unit_id, ok=False, detail="refused at execute: not a verified success")

    if not unit.pr_url:
        return MergeOutcome(
            unit_id,
            ok=False,
            detail="no open PR — open one first with `onmc swarm pr`",
        )

    pr_number = _pr_number(unit.pr_url)
    if pr_number is None:
        return MergeOutcome(
            unit_id, ok=False, detail=f"could not parse a PR number from {unit.pr_url}",
            pr_url=unit.pr_url,
        )

    # Import the land machinery lazily so a dry run never touches gh/network.
    from oh_no_my_claudecode.land.commands import _build_gh_client
    from oh_no_my_claudecode.land.driver import LandError, land

    try:
        result = land(pr_number, gh=_build_gh_client())
    except LandError as exc:
        return MergeOutcome(unit_id, ok=False, detail=f"land failed: {exc}", pr_url=unit.pr_url)

    outcome = result["outcome"]
    return MergeOutcome(
        unit_id,
        ok=outcome == "merged",
        detail=f"land: {outcome}" + (f" ({result['reason']})" if result.get("reason") else ""),
        pr_url=unit.pr_url,
    )


def _build_merger() -> Merger:
    """Return the real merger.  Module-level so tests can monkeypatch it."""
    return _real_merger


def _plan_payload(plan: ApprovalPlan, result: ExecutionResult) -> dict[str, object]:
    """Build the ``--json`` envelope for a planned/executed approval."""
    return {
        "kind": "approve_result",
        "action": str(plan.kind),
        "note": plan.note,
        "dry_run": result.dry_run,
        "eligible": list(plan.eligible),
        "refused": [{"unit_id": uid, "reason": reason} for uid, reason in plan.refused],
        "merged": [asdict(outcome) for outcome in result.merged],
    }


def register(app: typer.Typer) -> None:
    """Register the ``approve`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("approve")
    def approve_command(
        swarm_id: Annotated[
            str,
            typer.Argument(help="Swarm id whose trust card the approval acts on."),
        ],
        message: Annotated[
            str,
            typer.Argument(
                help='Chat reply or button callback to act on (e.g. "approve all", '
                '"approve unit 2", "mission:approve:unit-0001").',
            ),
        ],
        execute: Annotated[
            bool,
            typer.Option(
                "--execute",
                "--yes",
                help="Perform the real merge(s). Omit for a DRY plan (no action taken).",
            ),
        ] = False,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit a machine-readable JSON envelope."),
        ] = False,
    ) -> None:
        """Turn an approved chat action into a real merge of verified unit PR(s).

        Closes the phone-to-merge loop: parse the *message*, plan which units it
        may merge (VERIFIED successes only — held / unverified / aborted units
        are REFUSED and never merged), then act.

        DRY by default — prints what WOULD merge and what is refused, changing
        nothing.  Pass ``--execute`` (alias ``--yes``) to merge for real.

        Exits non-zero when the action targeted a specific unit that was refused,
        or when a real merge failed — so a gateway / automation can gate on it.

        \b
        Examples
        --------
        onmc approve ab12cd34 "approve all"
        onmc approve ab12cd34 "approve unit 2" --execute
        onmc approve ab12cd34 "mission:approve:unit-0001" --json
        """
        repo_root = _repo_root()
        card = build_card(repo_root, swarm_id)
        action = parse_action(message)
        plan = plan_approval(card, action)

        merger = _build_merger() if execute else None
        result = execute_plan(repo_root, swarm_id, plan, merger=merger, dry_run=not execute)

        if as_json:
            typer.echo(json.dumps(_plan_payload(plan, result), indent=2))
        else:
            _render(swarm_id, plan, result)

        raise typer.Exit(code=_exit_code(plan, result))


def _render(swarm_id: str, plan: ApprovalPlan, result: ExecutionResult) -> None:
    """Print a human-readable plan + result to stdout."""
    mode = "DRY (no action taken)" if result.dry_run else "EXECUTE"
    typer.echo(f"approve {swarm_id} — {plan.kind} · {mode}")
    typer.echo(f"  {plan.note}")

    if result.merged:
        typer.echo("  merged:")
        for outcome in result.merged:
            glyph = "✅" if outcome.ok else "❌"
            tail = f" — {outcome.pr_url}" if outcome.pr_url else ""
            typer.echo(f"    {glyph} {outcome.unit_id}: {outcome.detail}{tail}")

    if result.skipped:
        typer.echo("  refused (never merged):")
        for unit_id, reason in result.skipped:
            typer.echo(f"    ⛔ {unit_id}: {reason}")


def _exit_code(plan: ApprovalPlan, result: ExecutionResult) -> int:
    """Non-zero when a targeted unit was refused or a real merge failed."""
    from oh_no_my_claudecode.missionbridge.models import ApproveKind

    # A per-unit approval whose target was refused is an actionable failure.
    if plan.kind is ApproveKind.APPROVE_UNIT and plan.refused:
        return 2
    # A real merge that did not succeed is a failure too.
    if not result.dry_run and any(not outcome.ok for outcome in result.merged):
        return 1
    return 0
