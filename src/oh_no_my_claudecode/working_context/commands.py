"""CLI for opt-in, session-scoped adaptive working context."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import typer

from oh_no_my_claudecode.working_context.hooks import load_working_context
from oh_no_my_claudecode.working_context.models import NoteKind

if TYPE_CHECKING:
    from oh_no_my_claudecode.working_context.engine import WorkingContext


@contextmanager
def _engine() -> Iterator[tuple[Path, WorkingContext]]:
    try:
        yield load_working_context(Path.cwd())
    except (OSError, ValueError, LookupError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


def _json(value: object) -> None:
    typer.echo(json.dumps(value, indent=2, ensure_ascii=False))


def register(app: typer.Typer) -> None:
    working = typer.Typer(help="Keep task constraints and fresh context across Claude tool steps.")
    app.add_typer(working, name="working")

    @working.command("enable")
    def enable(
        budget_chars: Annotated[int, typer.Option("--budget-chars", min=1000, max=32000)] = 6000,
        constraints: Annotated[list[str] | None, typer.Option("--constraint")] = None,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Enable working context and install project hooks and ONMC MCP registration."""
        from oh_no_my_claudecode.hooks.installer import install_claude_hooks

        with _engine() as (root, engine):
            previous = engine.config()
            config = engine.configure(
                enabled=True,
                budget_chars=budget_chars,
                constraints=previous.constraints if constraints is None else constraints,
            )
            install_claude_hooks(repo_root=root, register_mcp=True, clean_global=False)
            if as_json:
                _json(config.model_dump(mode="json"))
            else:
                typer.echo("Working context enabled. Project hooks and MCP are installed.")
                typer.echo("Start or resume Claude Code to use the updated hook configuration.")

    @working.command("disable")
    def disable(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
        """Stop adaptive context injection without removing other ONMC hooks."""
        with _engine() as (_, engine):
            previous = engine.config()
            config = engine.configure(
                enabled=False,
                budget_chars=previous.budget_chars,
                constraints=previous.constraints,
            )
            if as_json:
                _json(config.model_dump(mode="json"))
            else:
                typer.echo("Working context disabled.")

    @working.command("start")
    def start(
        task: Annotated[str, typer.Option("--task")],
        session: Annotated[str, typer.Option("--session")] = "default",
        constraints: Annotated[list[str] | None, typer.Option("--constraint")] = None,
        replace: Annotated[bool, typer.Option("--replace")] = False,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Start a named task; replacing its goal or constraints requires --replace."""
        with _engine() as (_, engine):
            result = engine.start(session, task, constraints=constraints, replace=replace)
            if as_json:
                _json(result.model_dump(mode="json"))
            else:
                typer.echo(f"Working session {result.session_id}: {result.goal}")

    @working.command("context")
    def context(
        session: Annotated[str, typer.Option("--session")] = "default",
        focus: Annotated[str | None, typer.Option("--focus")] = None,
        files: Annotated[list[str] | None, typer.Option("--file")] = None,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Show a fresh working packet with evidence and exclusions."""
        with _engine() as (_, engine):
            packet = engine.context(session, focus=focus, files=files, force=True, consume=False)
            if as_json:
                _json(packet.model_dump(mode="json"))
            else:
                typer.echo(packet.markdown)

    @working.command("note")
    def note(
        kind: Annotated[str, typer.Option("--kind")],
        text: Annotated[str, typer.Option("--text")],
        session: Annotated[str, typer.Option("--session")] = "default",
        files: Annotated[list[str] | None, typer.Option("--file")] = None,
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Record a decision, hypothesis, or next_step; file anchors track freshness."""
        with _engine() as (_, engine):
            if kind not in {"decision", "hypothesis", "next_step"}:
                raise ValueError("kind must be decision, hypothesis, or next_step")
            result = engine.note(
                session,
                cast(NoteKind, kind),
                text,
                files=files,
            )
            if as_json:
                _json(result.model_dump(mode="json"))
            else:
                typer.echo(f"Recorded {kind} for {session}.")

    @working.command("status")
    def status(
        session: Annotated[str, typer.Option("--session")] = "default",
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Inspect enablement, constraints, and a session without creating it."""
        with _engine() as (_, engine):
            config = engine.config()
            current = engine.session(session)
            if as_json:
                _json(
                    {
                        "config": config.model_dump(mode="json"),
                        "session": current.model_dump(mode="json") if current else None,
                    }
                )
            else:
                typer.echo(f"Working context: {'enabled' if config.enabled else 'disabled'}")
                typer.echo(f"Budget: {config.budget_chars} characters")
                typer.echo(f"Task: {current.goal}" if current else f"No session: {session}")

    @working.command("verify-memory")
    def verify_memory(
        memory_id: Annotated[str, typer.Argument()],
        as_json: Annotated[bool, typer.Option("--json")] = False,
    ) -> None:
        """Acknowledge current file anchors; does not approve or promote memory content."""
        with _engine() as (_, engine):
            result = engine.verify_memory(memory_id)
            if as_json:
                _json(result)
            else:
                typer.echo("Memory file anchors acknowledged; semantic correctness is unverified.")
