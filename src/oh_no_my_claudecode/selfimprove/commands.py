"""CLI surface for the ``selfimprove`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): this module exposes a top-level
``register(app)`` that the registry invokes at CLI build time so
``onmc selfimprove`` ships with **zero edits** to ``cli.py``.

``onmc selfimprove review`` scans a transcript/session text for durable
learnings (corrections, preferences, confirmed conventions) and emits ranked
candidate memory proposals. With ``--stage`` each candidate is pushed into
the memstage pending queue for human approval via ``onmc memstage approve``.

Pure stdlib -- no LLM calls, no network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.memstage.queue import stage as memstage_stage
from oh_no_my_claudecode.selfimprove.review import extract_learnings

selfimprove_app = typer.Typer(
    name="selfimprove",
    help=(
        "After-turn learning review -- extract durable learnings from a transcript "
        "and propose memory updates for human approval."
    ),
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Register the ``onmc selfimprove`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(selfimprove_app, name="selfimprove")


@selfimprove_app.command("review")
def review_command(
    from_file: Annotated[
        Path | None,
        typer.Option(
            "--from-file",
            help="Read transcript text from FILE instead of stdin.",
            metavar="FILE",
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                'Wrap output in a JSON envelope '
                '{"kind": "selfimprove", "candidates": [...]} '
                "for pipeline composition."
            ),
        ),
    ] = False,
    do_stage: Annotated[
        bool,
        typer.Option(
            "--stage",
            help=(
                "Push each candidate into the memstage pending queue "
                "(human approves via ``onmc memstage approve``)."
            ),
        ),
    ] = False,
) -> None:
    """Extract candidate learnings from a transcript and rank them.

    Reads from FILE (``--from-file``) or stdin. Scans for user corrections,
    stated preferences, and confirmed conventions using pure heuristics -- no
    LLM calls, no network.

    With ``--stage`` each candidate is pushed into the memstage pending queue
    so a human can review and approve via ``onmc memstage approve``.

    Examples:

        onmc selfimprove review --from-file session.txt

        onmc selfimprove review --from-file session.txt --json

        onmc selfimprove review --from-file session.txt --stage

        cat session.txt | onmc selfimprove review
    """
    # ---- Read input --------------------------------------------------------
    if from_file is not None:
        try:
            text = from_file.read_text(encoding="utf-8")
        except (OSError, FileNotFoundError) as exc:
            typer.echo(f"error: cannot read {from_file}: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    else:
        text = sys.stdin.read()

    # ---- Extract -----------------------------------------------------------
    candidates = extract_learnings(text)

    # ---- Stage (optional) --------------------------------------------------
    staged_ids: list[str] = []
    if do_stage and candidates:
        try:
            repo_root = discover_repo_root(Path.cwd())
        except RepoDiscoveryError:
            typer.echo(
                "error: no git repository found -- cannot stage proposals.", err=True
            )
            raise typer.Exit(code=1) from None

        for candidate in candidates:
            proposal = memstage_stage(
                repo_root,
                kind=candidate.memory_kind,
                title=candidate.title,
                summary=candidate.text,
                reason=candidate.rationale,
            )
            staged_ids.append(proposal.id)

    # ---- Output ------------------------------------------------------------
    if as_json:
        payload: dict[str, object] = {
            "kind": "selfimprove",
            "count": len(candidates),
            "candidates": [c.to_dict() for c in candidates],
        }
        if do_stage:
            payload["staged_ids"] = staged_ids
        typer.echo(json.dumps(payload, indent=2))
        return

    if not candidates:
        typer.echo("No learnings extracted from the provided text.")
        return

    # Human-readable output
    typer.echo(f"Found {len(candidates)} candidate learning(s):\n")
    for i, candidate in enumerate(candidates, start=1):
        label = candidate.signal.upper()
        typer.echo(f"  [{i}] {label}: {candidate.title}")
        typer.echo(f"       kind={candidate.memory_kind}  rationale={candidate.rationale}")
        if do_stage and i <= len(staged_ids):
            typer.echo(f"       staged -> {staged_ids[i - 1]}")
        typer.echo("")
