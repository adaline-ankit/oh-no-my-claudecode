"""CLI surface for the ``memstage`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc memstage`` ships with **zero
edits** to ``cli.py`` or any other shared hub.

Subcommands
-----------
``onmc memstage add "<text>" [--kind ...] [--reason ...]``
    Stage a proposed memory write into the pending queue.  Does NOT write to
    the memory store.

``onmc memstage list [--json]``
    List pending proposals with ids and one-line gists.

``onmc memstage diff <id>``
    Show the full proposed entry in unified-diff style vs the empty baseline.

``onmc memstage approve <id>``
    Approve a proposal: persist it to the memory store via the real record
    path, remove it from the queue, and write an audit record.

``onmc memstage reject <id> [--reason ...]``
    Reject a proposal: drop it from the queue and write an audit record.

All subcommands support ``--json`` for machine consumption (where applicable).
Output is deterministic.  Never asserts Rich ``--help`` text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.memstage.queue import (
    AuditRecord,
    StagedProposal,
    approve,
    diff,
    list_pending,
    reject,
    stage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_repo_root() -> Path:
    """Discover the repo root, falling back to CWD if discovery fails."""
    from oh_no_my_claudecode.core.repo import (  # noqa: PLC0415
        RepoDiscoveryError,
        discover_repo_root,
    )

    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        return Path.cwd().resolve()


def _try_staged_at() -> str:
    """Best-effort UTC timestamp string for ``staged_at``; ``""`` on failure."""
    try:
        from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now  # noqa: PLC0415

        return isoformat_utc(utc_now())
    except Exception:  # noqa: BLE001
        return ""


def _proposal_payload(proposal: StagedProposal) -> dict[str, object]:
    """JSON-serialisable view of a pending proposal."""
    return {
        "id": proposal.id,
        "kind": proposal.kind,
        "title": proposal.title,
        "summary": proposal.summary,
        "reason": proposal.reason,
        "staged_at": proposal.staged_at,
        "seq": proposal.seq,
    }


def _audit_payload(record: AuditRecord) -> dict[str, object]:
    """JSON-serialisable view of an audit record."""
    return {
        "seq": record.seq,
        "proposal_id": record.proposal_id,
        "decision": record.decision,
        "reason": record.reason,
        "memory_id": record.memory_id,
    }


def _default_kind() -> str:
    """Return the canonical default memory kind."""
    return "doc_fact"


# ---------------------------------------------------------------------------
# Auto-discovery entry point
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``onmc memstage`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    memstage_app = typer.Typer(
        help=(
            "Write-approval staging queue: propose memory writes, review diffs, "
            "then approve or reject — nothing lands in the store without your sign-off."
        ),
        no_args_is_help=True,
    )

    @memstage_app.command("add")
    def add_command(
        text: Annotated[
            str,
            typer.Argument(help="The proposed memory entry body (the summary)."),
        ],
        title: Annotated[
            str,
            typer.Option("--title", help="Short title for the memory entry."),
        ] = "",
        kind: Annotated[
            str,
            typer.Option(
                "--kind",
                help=(
                    "Memory kind (doc_fact, decision, invariant, hotspot, "
                    "git_pattern, validation_rule, failed_approach, "
                    "design_conflict, gotcha). Defaults to 'doc_fact'."
                ),
            ),
        ] = "",
        reason: Annotated[
            str,
            typer.Option("--reason", help="Why this write is being proposed."),
        ] = "",
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the staged proposal as JSON."),
        ] = False,
    ) -> None:
        """Stage a proposed memory write into the pending queue.

        The entry is NOT written to the memory store — it waits in the queue
        until you run ``approve`` or ``reject``. Review the diff first with
        ``onmc memstage diff <id>``.

        Examples:

            onmc memstage add "Always run tests before pushing"

            onmc memstage add "Stripe webhook secret rotates on redeploy" \\
              --kind gotcha --title "Stripe webhook secret rotates" \\
              --reason "Burnt 2h on this"
        """
        summary = text.strip()
        if not summary:
            typer.echo("error: proposal text must not be empty", err=True)
            raise typer.Exit(code=1)

        resolved_kind = kind.strip() if kind.strip() else _default_kind()
        resolved_title = title.strip() if title.strip() else summary[:72]

        repo_root = _resolve_repo_root()
        try:
            proposal = stage(
                repo_root,
                kind=resolved_kind,
                title=resolved_title,
                summary=summary,
                reason=reason,
                staged_at=_try_staged_at(),
            )
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        if as_json:
            typer.echo(json.dumps(_proposal_payload(proposal)))
            return
        typer.echo(f"staged [{proposal.id}] {proposal.title}")
        typer.echo(f"  kind: {proposal.kind}  seq: {proposal.seq}")
        typer.echo("  run 'onmc memstage diff <id>' to review, then approve/reject.")

    @memstage_app.command("list")
    def list_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit pending proposals as JSON."),
        ] = False,
    ) -> None:
        """List pending proposals with ids and one-line gists.

        Shows proposals in queue order (by seq). Each line contains the
        proposal id and title for quick scanning. Use ``diff <id>`` to see
        the full proposed entry.
        """
        repo_root = _resolve_repo_root()
        proposals = list_pending(repo_root)

        if as_json:
            typer.echo(json.dumps([_proposal_payload(p) for p in proposals]))
            return
        if not proposals:
            typer.echo(
                "memstage queue is empty — add one with: "
                'onmc memstage add "<proposed memory>"'
            )
            return
        for proposal in proposals:
            gist = proposal.title[:60]
            typer.echo(f"{proposal.id}  [{proposal.kind}]  {gist}")

    @memstage_app.command("diff")
    def diff_command(
        proposal_id: Annotated[
            str,
            typer.Argument(help="Proposal id to diff (from 'onmc memstage list')."),
        ],
    ) -> None:
        """Show the full proposed entry in unified-diff style.

        Compares an empty baseline (entry doesn't exist yet) against the
        proposed content so every added line is visible. A ``+`` line is
        something that *would* land in the store on approve.
        """
        repo_root = _resolve_repo_root()
        output = diff(repo_root, proposal_id)
        typer.echo(output)
        if output.startswith("error:"):
            raise typer.Exit(code=1)

    @memstage_app.command("approve")
    def approve_command(
        proposal_id: Annotated[
            str,
            typer.Argument(help="Proposal id to approve (from 'onmc memstage list')."),
        ],
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the audit record as JSON."),
        ] = False,
    ) -> None:
        """Approve a pending proposal and persist it to the memory store.

        The approved entry is written via the real memory record path
        (``add_manual_memory``) so it lands in the SQLite store with full
        provenance. The proposal is then removed from the pending queue and an
        audit record is written under ``.onmc/memstage/audit/``.
        """
        repo_root = _resolve_repo_root()

        # Load service via the normal pattern used in other commands.
        try:
            from oh_no_my_claudecode.core.service import OnmcService  # noqa: PLC0415

            service = OnmcService(repo_root)
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"error: could not load onmc service — {exc}", err=True)
            raise typer.Exit(code=1) from exc

        try:
            record = approve(repo_root, proposal_id, service=service)
        except LookupError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        except (ValueError, TypeError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        if as_json:
            typer.echo(json.dumps(_audit_payload(record)))
            return
        typer.echo(f"approved [{proposal_id}] → memory {record.memory_id}")

    @memstage_app.command("reject")
    def reject_command(
        proposal_id: Annotated[
            str,
            typer.Argument(help="Proposal id to reject (from 'onmc memstage list')."),
        ],
        reason: Annotated[
            str,
            typer.Option("--reason", help="Why this proposal is being rejected."),
        ] = "",
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the audit record as JSON."),
        ] = False,
    ) -> None:
        """Reject a pending proposal: drop it and keep an audit trail.

        The proposal is removed from the pending queue. An audit record is
        written under ``.onmc/memstage/audit/`` so the decision is traceable.
        """
        repo_root = _resolve_repo_root()
        try:
            record = reject(repo_root, proposal_id, reason=reason)
        except LookupError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        if as_json:
            typer.echo(json.dumps(_audit_payload(record)))
            return
        typer.echo(f"rejected [{proposal_id}]")
        if reason:
            typer.echo(f"  reason: {reason}")

    app.add_typer(memstage_app, name="memstage")
