"""CLI surface for the ``evals`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub (``cli.py``, ``rendering/``, service
layer) is touched.

Registers ``onmc corpus-health``: reads a serialized A/B report
(``ABReport.to_dict()`` JSON), reconstructs per-task pass booleans from its
``comparisons`` list, and folds them through the pure hygiene auditor
(:func:`oh_no_my_claudecode.evals.ab.hygiene.audit_rows`). Deterministic and
offline — no LLM call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.evals.ab.hygiene import audit_rows


def _load_rows(report_path: Path) -> list[dict[str, object]]:
    """Reconstruct per-task pass rows from an ``ABReport.to_dict()`` JSON file.

    Exits with code 1 on an unreadable file or a JSON body without a
    ``comparisons`` list. Rows missing the expected result dicts are skipped.
    """
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        typer.echo(f"Cannot read A/B report {str(report_path)!r}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    comparisons = data.get("comparisons") if isinstance(data, dict) else None
    if not isinstance(comparisons, list):
        typer.echo(f"Not an A/B report: {str(report_path)!r} has no 'comparisons' list.", err=True)
        raise typer.Exit(code=1)

    rows: list[dict[str, object]] = []
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            continue
        alone = comparison.get("alone")
        onmc = comparison.get("onmc")
        if not (isinstance(alone, dict) and isinstance(onmc, dict)):
            continue
        rows.append(
            {
                "task_id": str(comparison.get("task_id", "")),
                "alone_passed": bool(alone.get("passed")),
                "onmc_passed": bool(onmc.get("passed")),
            }
        )
    return rows


def register(app: typer.Typer) -> None:
    """Register the ``corpus-health`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("corpus-health")
    def corpus_health_command(
        report: Annotated[
            Path,
            typer.Argument(
                help="Path to an A/B report JSON (the shape ABReport.to_dict() writes)."
            ),
        ],
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the corpus health verdict as JSON."),
        ] = False,
    ) -> None:
        """Audit an A/B eval corpus for saturated and dead tasks.

        Reads a serialized A/B report and flags each task as saturated (every
        arm always passes — measures nothing), dead (every arm always fails —
        broken task), or discriminating, plus the suite-level discriminating
        ratio. Deterministic and offline — no LLM call. A corpus that cannot
        discriminate is not a benchmark; drop or refresh the flagged tasks
        before the next paid run.
        """
        health = audit_rows(_load_rows(report))

        if as_json:
            typer.echo(json.dumps(health.to_dict()))
            return

        discriminating = sum(t.discriminating for t in health.tasks)
        lines = [
            "",
            f"  onmc corpus-health — {len(health.tasks)} task(s) audited",
            f"  discriminating: {discriminating}/{len(health.tasks)}"
            f"  (ratio {health.discriminating_ratio:.3f})",
            f"  saturated:      {', '.join(health.saturated_ids) or '(none)'}",
            f"  dead:           {', '.join(health.dead_ids) or '(none)'}",
            "",
        ]
        typer.echo("\n".join(lines))
