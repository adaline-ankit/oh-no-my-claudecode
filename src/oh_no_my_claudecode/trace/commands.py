"""CLI surface for the ``trace`` feature — auto-discovered.

Registers ``onmc observe``: ship this repo's run receipts as OTLP verdict
spans to whatever OTel backend the standard env vars point at (Langfuse,
Phoenix, Grafana, any collector). ``--dry-run`` shows what would ship and
where, without sending a byte. See docs/observability.md.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.ledger.accounting import load_receipts
from oh_no_my_claudecode.trace.otel_ledger import verdict_span
from oh_no_my_claudecode.trace.otel_ship import resolve_otlp_config, ship_receipts


def register(app: typer.Typer) -> None:
    @app.command("observe")
    def observe(
        dry_run: Annotated[
            bool, typer.Option("--dry-run", help="Show what would ship, send nothing.")
        ] = False,
        endpoint: Annotated[
            str, typer.Option("--endpoint", help="Override OTEL_EXPORTER_OTLP_ENDPOINT.")
        ] = "",
    ) -> None:
        """Ship run-receipt verdicts to the configured OTel backend."""
        repo_root = Path.cwd()
        target, headers = resolve_otlp_config()
        if endpoint:
            target = endpoint.rstrip("/")
        if dry_run:
            receipts = load_receipts(repo_root)
            spans = [verdict_span(r, when_ns=time.time_ns()) for r in receipts]
            typer.echo(f"would ship {len(spans)} verdict span(s) to {target or '<unset>'}")
            if not target:
                typer.echo("set OTEL_EXPORTER_OTLP_ENDPOINT — see docs/observability.md")
            raise typer.Exit(0)
        try:
            count = ship_receipts(repo_root, endpoint=target or None, headers=headers)
        except (ValueError, RuntimeError) as error:
            typer.echo(f"observe failed: {error}", err=True)
            raise typer.Exit(1) from error
        typer.echo(f"shipped {count} verdict span(s) to {target}")
