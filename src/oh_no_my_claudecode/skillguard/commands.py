"""CLI surface for the ``skillguard`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc skillguard`` ships with **zero
edits** to ``cli.py`` or any other shared hub.

Subcommands
-----------
``onmc skillguard stage --name <skill> --op <create|edit|delete>``
    ``[--content-file F | --content "..."]``
    Stage a proposed skill change into the pending queue.  Does NOT touch the
    skill store.

``onmc skillguard list [--json]``
    List pending proposals with ids and one-line gists.

``onmc skillguard diff <id>``
    Show a unified diff (proposed vs current skill content).

``onmc skillguard approve <id> [--json]``
    Approve a proposal: apply via the real skill path, remove from queue, write
    an audit record.

``onmc skillguard reject <id> [--reason ...] [--json]``
    Reject a proposal: drop it from the queue and write an audit record.

All subcommands support ``--json`` for machine consumption (where applicable).
Output is deterministic.  Never asserts Rich ``--help`` text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.skillguard.queue import (
    SkillAuditRecord,
    StagedSkillProposal,
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


def _proposal_payload(proposal: StagedSkillProposal) -> dict[str, object]:
    """JSON-serialisable view of a pending proposal."""
    return {
        "id": proposal.id,
        "op": proposal.op,
        "name": proposal.name,
        "content": proposal.content,
        "reason": proposal.reason,
        "staged_at": proposal.staged_at,
        "seq": proposal.seq,
    }


def _audit_payload(record: SkillAuditRecord) -> dict[str, object]:
    """JSON-serialisable view of an audit record."""
    return {
        "seq": record.seq,
        "proposal_id": record.proposal_id,
        "decision": record.decision,
        "reason": record.reason,
        "skill_id": record.skill_id,
    }


# ---------------------------------------------------------------------------
# Auto-discovery entry point
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``onmc skillguard`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    skillguard_app = typer.Typer(
        help=(
            "Skill write-approval gate: propose skill create/edit/delete, review diffs, "
            "then approve or reject — nothing lands in the skill store without your sign-off."
        ),
        no_args_is_help=True,
    )

    @skillguard_app.command("stage")
    def stage_command(
        name: Annotated[
            str,
            typer.Option("--name", help="Name of the skill to create, edit, or delete."),
        ],
        op: Annotated[
            str,
            typer.Option(
                "--op",
                help="Operation to propose: create, edit, or delete.",
            ),
        ],
        content: Annotated[
            str,
            typer.Option(
                "--content",
                help="Proposed skill body (inline string). Mutually exclusive with --content-file.",
            ),
        ] = "",
        content_file: Annotated[
            Path | None,
            typer.Option(
                "--content-file",
                help="Path to a file whose contents become the proposed skill body.",
                metavar="FILE",
            ),
        ] = None,
        reason: Annotated[
            str,
            typer.Option("--reason", help="Why this skill change is being proposed."),
        ] = "",
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the staged proposal as JSON."),
        ] = False,
    ) -> None:
        """Stage a proposed skill change into the pending queue.

        The change is NOT applied to the skill store — it waits in the queue
        until you run ``approve`` or ``reject``. Review the diff first with
        ``onmc skillguard diff <id>``.

        Exactly one of ``--content`` or ``--content-file`` must be supplied for
        create/edit operations.  For delete, both may be omitted.

        Examples:

            onmc skillguard stage --name "my-pattern" --op create \\
              --content "Always prefer uv over pip" --reason "team convention"

            onmc skillguard stage --name "my-pattern" --op edit \\
              --content-file updated_skill.md

            onmc skillguard stage --name "old-pattern" --op delete \\
              --reason "obsolete since v2 migration"
        """
        name_stripped = name.strip()
        op_stripped = op.strip()

        if content and content_file is not None:
            typer.echo("error: --content and --content-file are mutually exclusive", err=True)
            raise typer.Exit(code=1)

        resolved_content = content
        if content_file is not None:
            try:
                resolved_content = content_file.read_text(encoding="utf-8")
            except OSError as exc:
                typer.echo(f"error: could not read content file — {exc}", err=True)
                raise typer.Exit(code=1) from exc

        repo_root = _resolve_repo_root()
        try:
            proposal = stage(
                repo_root,
                op=op_stripped,
                name=name_stripped,
                content=resolved_content,
                reason=reason,
                staged_at=_try_staged_at(),
            )
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

        if as_json:
            typer.echo(json.dumps(_proposal_payload(proposal)))
            return
        typer.echo(f"staged [{proposal.id}] {proposal.op} '{proposal.name}'")
        typer.echo(f"  seq: {proposal.seq}")
        typer.echo("  run 'onmc skillguard diff <id>' to review, then approve/reject.")

    @skillguard_app.command("list")
    def list_command(
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit pending proposals as JSON."),
        ] = False,
    ) -> None:
        """List pending proposals with ids and one-line gists.

        Shows proposals in queue order (by seq). Each line contains the
        proposal id, operation, and skill name. Use ``diff <id>`` to see the
        full unified diff.
        """
        repo_root = _resolve_repo_root()
        proposals = list_pending(repo_root)

        if as_json:
            typer.echo(json.dumps([_proposal_payload(p) for p in proposals]))
            return
        if not proposals:
            typer.echo(
                "skillguard queue is empty — add one with: "
                "onmc skillguard stage --name <skill> --op <create|edit|delete>"
            )
            return
        for proposal in proposals:
            gist = proposal.name[:60]
            typer.echo(f"{proposal.id}  [{proposal.op}]  {gist}")

    @skillguard_app.command("diff")
    def diff_command(
        proposal_id: Annotated[
            str,
            typer.Argument(help="Proposal id to diff (from 'onmc skillguard list')."),
        ],
    ) -> None:
        """Show a unified diff of the proposed skill change.

        Compares the current skill body (or an empty baseline for new skills)
        against the proposed content. ``+`` lines would be added on approve;
        ``-`` lines would be removed.
        """
        repo_root = _resolve_repo_root()
        output = diff(repo_root, proposal_id)
        typer.echo(output)
        if output.startswith("error:"):
            raise typer.Exit(code=1)

    @skillguard_app.command("approve")
    def approve_command(
        proposal_id: Annotated[
            str,
            typer.Argument(help="Proposal id to approve (from 'onmc skillguard list')."),
        ],
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the audit record as JSON."),
        ] = False,
    ) -> None:
        """Approve a pending proposal and apply it to the skill store.

        The approved change is written via the real skill storage path so it
        lands with full provenance. The proposal is then removed from the
        pending queue and an audit record is written under
        ``.onmc/skillguard/audit/``.
        """
        repo_root = _resolve_repo_root()

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
        label = f"skill {record.skill_id}" if record.skill_id else "skill (deleted)"
        typer.echo(f"approved [{proposal_id}] → {label}")

    @skillguard_app.command("reject")
    def reject_command(
        proposal_id: Annotated[
            str,
            typer.Argument(help="Proposal id to reject (from 'onmc skillguard list')."),
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
        written under ``.onmc/skillguard/audit/`` so the decision is traceable.
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

    app.add_typer(skillguard_app, name="skillguard")
