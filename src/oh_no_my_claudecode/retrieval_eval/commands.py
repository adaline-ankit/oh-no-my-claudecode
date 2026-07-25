"""CLI entry-point for the offline retrieval quality evaluation harness.

Registers as ``onmc retrieval-eval`` via the auto-discovery convention
(module named ``commands`` in a subpackage, exports ``register(app)``).

Usage::

    onmc retrieval-eval                    # memory split (recall + guard)
    onmc retrieval-eval --split code       # code split (bm25 vs hybrid)
    onmc retrieval-eval --split all        # memory + code splits
    onmc retrieval-eval --json             # JSON output for CI / scripts

This command is OFFLINE and DETERMINISTIC.  It produces no LLM calls, no
network requests, and no randomness.  The same dataset + the same retrieval
code always produces the same scores.

Splits
------
``memory`` (default):
    Scores ``compile_recall`` (surface "recall") and ``compile_guard``
    (surface "guard") against the frozen memory dataset v1.

``code``:
    Runs the four-way retrieval ablation against the frozen code dataset v1 —
    BM25-only ("code-bm25"), fused BM25+dense+RRF ("code-hybrid"), dense-only
    ("code-dense"), and graph-only ("code-graph").  All measured surfaces run
    the same 40 frozen queries so deltas are directly comparable.  A surface
    with no implementable primitive is reported as SKIPPED with a
    machine-readable ``skip_code`` — never as zeroed metrics.  Today
    "code-graph" is such a surface (no query-to-chunk graph ranker exists).

``all``:
    Runs both splits in sequence and prints a combined report.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from oh_no_my_claudecode.retrieval_eval.runner import RetrievalReport, SurfaceReport


class Split(str, Enum):  # noqa: UP042  # str subclass required by Typer for enum params
    """Which retrieval split to evaluate."""

    memory = "memory"
    code = "code"
    all = "all"


app = typer.Typer(
    name="retrieval-eval",
    help=(
        "Run the offline retrieval quality evaluation harness. "
        "Scores the current retrieval surfaces against frozen labeled datasets "
        "using Recall@5/10, MRR@10, nDCG@10, and P@5. "
        "OFFLINE, DETERMINISTIC — no LLM calls, no network."
    ),
    invoke_without_command=True,
    no_args_is_help=False,
)

_SPLIT_HELP = (
    "Which retrieval split to evaluate. "
    "'memory' (default): recall + guard surfaces from the memory dataset. "
    "'code': the four-way ablation (code-bm25, code-hybrid, code-dense, code-graph) "
    "from the code dataset. "
    "'all': run both splits."
)


@app.callback(invoke_without_command=True)
def retrieval_eval_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(  # noqa: B008
        False,
        "--json",
        help="Output the full report as JSON instead of a Markdown scorecard.",
    ),
    split: Split = typer.Option(Split.memory, "--split", help=_SPLIT_HELP),  # noqa: B008
) -> None:
    """Run the offline retrieval-eval harness and print the scorecard.

    Use ``--split code`` to run the four-way BM25 / dense / graph / fused
    ablation on the frozen code split (40 queries, corpus of 149 code chunks
    from the three in-scope modules: retrieval_eval, retrieval, codeindex).
    Surfaces without an implementable primitive are reported as SKIPPED with a
    machine-readable reason instead of fabricated metrics.

    Use ``--split all`` to run both memory and code splits in one pass.

    The datasets are frozen (SHA-pinned).  Do not edit them to improve
    scores — that defeats the purpose.
    """
    if ctx.invoked_subcommand is not None:
        return

    from oh_no_my_claudecode.retrieval_eval.adapters import default_adapters  # noqa: PLC0415
    from oh_no_my_claudecode.retrieval_eval.code_adapters import (  # noqa: PLC0415
        code_ablation_adapters,
    )
    from oh_no_my_claudecode.retrieval_eval.runner import (  # noqa: PLC0415
        run_code_evaluation,
        run_evaluation,
    )

    if split == Split.memory:
        report = run_evaluation(default_adapters())
        _emit(report, json_output=json_output)

    elif split == Split.code:
        report = run_code_evaluation(code_ablation_adapters())
        _emit(report, json_output=json_output)

    else:  # all
        mem_report = run_evaluation(default_adapters())
        code_report = run_code_evaluation(code_ablation_adapters())
        if json_output:
            combined = {
                "memory": mem_report.to_dict(),
                "code": code_report.to_dict(),
            }
            typer.echo(json.dumps(combined, indent=2))
        else:
            typer.echo("### Memory split\n")
            typer.echo(mem_report.to_markdown())
            typer.echo("\n### Code split\n")
            typer.echo(code_report.to_markdown())
            _emit_code_delta(code_report)


def _emit(report: RetrievalReport, *, json_output: bool) -> None:
    """Print the report as Markdown or JSON."""
    if json_output:
        typer.echo(json.dumps(report.to_dict(), indent=2))
    else:
        typer.echo(report.to_markdown())
        # For code split, also show the delta between bm25 and hybrid.
        surface_names = {sr.surface_name for sr in report.surface_reports}
        if "code-bm25" in surface_names and "code-hybrid" in surface_names:
            _emit_code_delta(report)


def _emit_code_delta(report: RetrievalReport) -> None:
    """Append a delta row showing hybrid minus lexical improvement."""

    bm25_sr: SurfaceReport | None = None
    hybrid_sr: SurfaceReport | None = None
    for sr in report.surface_reports:
        if sr.surface_name == "code-bm25" and not sr.skipped:
            bm25_sr = sr
        elif sr.surface_name == "code-hybrid" and not sr.skipped:
            hybrid_sr = sr

    if bm25_sr is None or hybrid_sr is None:
        return

    from oh_no_my_claudecode.retrieval_eval.runner import compare_surfaces  # noqa: PLC0415

    dr10 = hybrid_sr.mean_recall_at_10 - bm25_sr.mean_recall_at_10
    dp5 = hybrid_sr.mean_precision_at_5 - bm25_sr.mean_precision_at_5
    dmrr = hybrid_sr.mean_mrr_at_10 - bm25_sr.mean_mrr_at_10
    dndcg = hybrid_sr.mean_ndcg_at_10 - bm25_sr.mean_ndcg_at_10
    dctx = hybrid_sr.mean_context_tokens - bm25_sr.mean_context_tokens

    def _fmt(v: float) -> str:
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.3f}"

    verdict = "HYBRID BEATS LEXICAL" if dmrr > 0 else "LEXICAL >= HYBRID"
    typer.echo("")
    typer.echo("#### Code split delta (hybrid minus bm25-only)")
    typer.echo("")
    typer.echo(
        f"| Metric   | BM25  | Hybrid | Delta |\n"
        f"|----------|-------|--------|-------|\n"
        f"| R@10     | {bm25_sr.mean_recall_at_10:.3f} | {hybrid_sr.mean_recall_at_10:.3f} "
        f"| {_fmt(dr10)} |\n"
        f"| P@5      | {bm25_sr.mean_precision_at_5:.3f} | {hybrid_sr.mean_precision_at_5:.3f} "
        f"| {_fmt(dp5)} |\n"
        f"| MRR@10   | {bm25_sr.mean_mrr_at_10:.3f} | {hybrid_sr.mean_mrr_at_10:.3f} "
        f"| {_fmt(dmrr)} |\n"
        f"| nDCG@10  | {bm25_sr.mean_ndcg_at_10:.3f} | {hybrid_sr.mean_ndcg_at_10:.3f} "
        f"| {_fmt(dndcg)} |\n"
        f"| Ctx tok  | {bm25_sr.mean_context_tokens:.0f} | {hybrid_sr.mean_context_tokens:.0f} "
        f"| {_fmt(dctx)} |\n"
        f"\n**Verdict: {verdict}**"
    )

    # Per-query wins/losses of hybrid vs the lexical (BM25) baseline on nDCG@10.
    win_loss = compare_surfaces(bm25_sr, hybrid_sr, metric="ndcg_at_10")
    typer.echo("")
    typer.echo("#### Per-query wins/losses vs lexical baseline (nDCG@10)")
    typer.echo("")
    typer.echo(
        f"| Candidate | Baseline | Wins | Losses | Ties | Mean Δ |\n"
        f"|-----------|----------|------|--------|------|--------|\n"
        f"| {win_loss.candidate_surface} | {win_loss.baseline_surface} "
        f"| {win_loss.wins} | {win_loss.losses} | {win_loss.ties} "
        f"| {_fmt(win_loss.mean_delta)} |\n"
        f"\n**Verdict: {win_loss.verdict}**"
    )


def register(app: typer.Typer) -> None:
    """Auto-discovery hook — called by register_feature_commands()."""
    from oh_no_my_claudecode.retrieval_eval.commands import (
        app as retrieval_eval_app,  # noqa: PLC0415
    )

    app.add_typer(retrieval_eval_app, name="retrieval-eval")
