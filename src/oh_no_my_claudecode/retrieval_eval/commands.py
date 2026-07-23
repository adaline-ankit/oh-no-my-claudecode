"""CLI entry-point for the offline retrieval quality evaluation harness.

Registers as ``onmc retrieval-eval`` via the auto-discovery convention
(module named ``commands`` in a subpackage, exports ``register(app)``).

Usage::

    onmc retrieval-eval            # print human-readable scorecard
    onmc retrieval-eval --json     # print JSON report (for CI / scripts)

This command is OFFLINE and DETERMINISTIC.  It produces no LLM calls, no
network requests, and no randomness.  The same dataset + the same retrieval
code always produces the same scores.
"""

from __future__ import annotations

import json

import typer

app = typer.Typer(
    name="retrieval-eval",
    help=(
        "Run the offline retrieval quality evaluation harness. "
        "Scores the current retrieval surfaces (recall, guard) "
        "against a frozen labeled dataset using Recall@5/10, "
        "MRR@10, nDCG@10, and P@5. "
        "OFFLINE, DETERMINISTIC — no LLM calls, no network."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def retrieval_eval_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output the full report as JSON instead of a Markdown scorecard.",
    ),
) -> None:
    """Run the offline retrieval-eval harness and print the scorecard.

    Measures Recall@5, Recall@10, Precision@5, MRR@10, and nDCG@10 for the
    current ``compile_recall`` and ``compile_guard`` retrieval surfaces.

    Surfaces that cannot be adapted cleanly (search_memory, context_engine)
    are reported as SKIPPED with an honest explanation.

    The dataset is frozen (SHA-pinned).  Do not edit the dataset to improve
    scores — that defeats the purpose.
    """
    if ctx.invoked_subcommand is not None:
        return

    from oh_no_my_claudecode.retrieval_eval.adapters import default_adapters
    from oh_no_my_claudecode.retrieval_eval.runner import run_evaluation

    adapters = default_adapters()
    report = run_evaluation(adapters)

    if json_output:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        typer.echo(report.to_markdown())


def register(app: typer.Typer) -> None:
    """Auto-discovery hook — called by register_feature_commands()."""
    from oh_no_my_claudecode.retrieval_eval.commands import app as retrieval_eval_app

    app.add_typer(retrieval_eval_app, name="retrieval-eval")
