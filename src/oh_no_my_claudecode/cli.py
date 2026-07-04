from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, cast

import typer

from oh_no_my_claudecode.claim import DEFAULT_TTL_SECONDS, Claim, ClaimLedger
from oh_no_my_claudecode.command_registry import register_feature_commands
from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks import session_start_context_json
from oh_no_my_claudecode.llm.base import LLMConfigurationError, LLMProviderError
from oh_no_my_claudecode.mcp_server import run_mcp_server
from oh_no_my_claudecode.models import (
    AttemptKind,
    AttemptStatus,
    BriefStyle,
    LLMProviderType,
    MemoryArtifactType,
    MemoryKind,
    SourceType,
    TaskLifecycleError,
    TaskStatus,
)
from oh_no_my_claudecode.rendering.console import (
    console,
    render_ask_result,
    render_attempt_added,
    render_attempt_detail,
    render_attempt_list,
    render_attempt_updated,
    render_audit_report,
    render_benchmark_report,
    render_blame_result,
    render_brief,
    render_codegraph_build,
    render_codegraph_context,
    render_codegraph_neighbors,
    render_conventions,
    render_coverage_suggestions,
    render_coverage_summary,
    render_doctor_report,
    render_evolution_card,
    render_fleet_doctor,
    render_fleet_status,
    render_gh_aw_init_result,
    render_hook_status,
    render_hud,
    render_import_summary,
    render_ingest_result,
    render_init_summary,
    render_ledger_summary,
    render_llm_configured,
    render_llm_status,
    render_loop_result,
    render_memory_artifact_added,
    render_memory_detail,
    render_memory_diff,
    render_memory_list,
    render_mine_result,
    render_nomistakes_result,
    render_notify_status,
    render_notify_tail,
    render_onboard_summary,
    render_playbook_detail,
    render_playbook_generate_summary,
    render_playbook_list,
    render_preflight_report,
    render_pull_all_summary,
    render_release_draft,
    render_reuse_hits,
    render_review_output,
    render_savings_card,
    render_skill_detail,
    render_skill_list,
    render_skill_promoted,
    render_skill_pruned,
    render_solve_output,
    render_status,
    render_sync_result,
    render_task_detail,
    render_task_list,
    render_task_started,
    render_task_updated,
    render_teach_output,
    render_user_memory_added,
    render_user_memory_detail,
    render_user_memory_list,
    render_user_memory_removed,
    render_user_profile,
    render_verify_report,
    render_why_report,
)
from oh_no_my_claudecode.setup import run_setup_wizard
from oh_no_my_claudecode.ui import export_dashboard_snapshot, serve_dashboard
from oh_no_my_claudecode.utils.text import limit_markdown_tokens
from oh_no_my_claudecode.wiki import WikiFormat
from oh_no_my_claudecode.wiki.foam import build_foam_vault
from oh_no_my_claudecode.wiki.logseq import build_logseq_vault

app = typer.Typer(
    help="Memory-grounded autonomous coding loops for Claude Code and Codex.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
memory_app = typer.Typer(help="Inspect stored memory.", no_args_is_help=True)
spec_app = typer.Typer(
    help="Inspect and validate the Agent Memory open spec.", no_args_is_help=True
)
task_app = typer.Typer(help="Manage task lifecycle state.", no_args_is_help=True)
attempt_app = typer.Typer(help="Track task-scoped attempts.", no_args_is_help=True)
llm_app = typer.Typer(help="Configure optional LLM providers.", no_args_is_help=True)
hooks_app = typer.Typer(help="Install and run Claude Code compaction hooks.", no_args_is_help=True)
claude_md_app = typer.Typer(
    help="Generate and maintain CLAUDE.md from ONMC memory.",
    no_args_is_help=False,
    invoke_without_command=True,
)
wiki_app = typer.Typer(
    help="Generate wiki and knowledge-graph exports from stored memory.",
    no_args_is_help=False,
    invoke_without_command=True,
)
playbook_app = typer.Typer(
    help="Synthesize and manage memory-derived playbooks.",
    no_args_is_help=True,
)
user_app = typer.Typer(
    help="Manage cross-repo user preferences (stored in ~/.onmc, not repo-scoped).",
    no_args_is_help=True,
)
profile_app = typer.Typer(
    help="Show and rebuild the derived user behavioral profile (~/.onmc/user.db).",
    no_args_is_help=True,
)
skill_app = typer.Typer(
    help="Manage self-improving skills synthesized from playbooks and memory patterns.",
    no_args_is_help=True,
)
notify_app = typer.Typer(
    help="Inspect and test the context firewall notification sink.",
    no_args_is_help=True,
)
gh_aw_app = typer.Typer(
    help="Scaffold memory-aware GitHub Actions agentic workflows.",
    no_args_is_help=True,
)
mcp_app = typer.Typer(
    help="MCP Trust Gateway — classify tool calls against a policy.",
    no_args_is_help=True,
)
swarm_app = typer.Typer(
    help=(
        "Parallel accountable agent loops — a bounded pool of run_loop workers. "
        "Honest: 'many tasks' = a queue drained by min(cpu-1, 8) workers, not "
        "unlimited simultaneous agents."
    ),
    no_args_is_help=True,
)
conventions_app = typer.Typer(
    help="Capture and inherit the repo's coding conventions (.onmc/conventions.md).",
    no_args_is_help=True,
)
claim_app = typer.Typer(
    help="Coordinate file/path leases for parallel agents.",
    no_args_is_help=True,
)
ledger_app = typer.Typer(
    help=(
        "Agent-work accounting (cost / wall-time / success-rate / ROI) over the "
        "run receipts that onmc loop and swarm write. Honest: cost is n/a when a "
        "receipt did not report it — never fabricated."
    ),
    no_args_is_help=True,
)
fleet_app = typer.Typer(
    help="Operator view for local agent fleets (swarm + claims + receipts).",
    no_args_is_help=True,
)
app.add_typer(memory_app, name="memory")
app.add_typer(spec_app, name="spec")
app.add_typer(task_app, name="task")
app.add_typer(attempt_app, name="attempt")
app.add_typer(llm_app, name="llm")
app.add_typer(hooks_app, name="hooks")
app.add_typer(claude_md_app, name="claude-md")
app.add_typer(playbook_app, name="playbook")
app.add_typer(skill_app, name="skill")
app.add_typer(user_app, name="user")
app.add_typer(profile_app, name="profile")
app.add_typer(notify_app, name="notify")
app.add_typer(gh_aw_app, name="gh-aw")
app.add_typer(mcp_app, name="mcp")
app.add_typer(swarm_app, name="swarm")
app.add_typer(conventions_app, name="conventions")
app.add_typer(claim_app, name="claim")
app.add_typer(ledger_app, name="ledger")
app.add_typer(fleet_app, name="fleet")
app.add_typer(wiki_app, name="wiki")


@app.command("tui")
def tui_command() -> None:
    """Open the interactive terminal brain-browser for memory curation."""
    from rich.console import Console

    from oh_no_my_claudecode.tui import run_tui

    try:
        svc = _service()
        # Trigger _load_context early to give a friendly error if not initialised.
        svc.status()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    run_tui(svc, console=Console())


@app.command("setup")
def setup_command(
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Use defaults and skip interactive prompts."),
    ] = False,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Skip provider setup and LLM-assisted extraction."),
    ] = False,
) -> None:
    """Run the interactive ONMC onboarding wizard."""
    try:
        run_setup_wizard(cwd=Path.cwd(), yes=yes, no_llm=no_llm)
    except RepoDiscoveryError:
        raise typer.Exit(
            code=_fatal(
                "✗ Not inside a git repository. "
                "cd into your project (or [bold]git init[/bold]) "
                "and run [bold]onmc setup[/bold]."
            )
        ) from None


def main() -> None:
    try:
        app()
    except (RepoDiscoveryError, FileNotFoundError) as exc:
        msg = str(exc)
        if "Not inside a git repository" in msg or isinstance(exc, RepoDiscoveryError):
            console.print(
                "[red]✗ Not inside a git repository.[/red] "
                "cd into your project (or [bold]git init[/bold]) "
                "and run [bold]onmc setup[/bold]."
            )
        else:
            console.print(f"[red]{msg}[/red]")
        raise SystemExit(1) from None


# ---------------------------------------------------------------------------
# MCP Trust Gateway commands
# ---------------------------------------------------------------------------

# mcp policy sub-group
mcp_policy_app = typer.Typer(
    help="Manage the MCP trust policy file (.onmc/mcp-policy.yaml).",
    no_args_is_help=True,
)
mcp_app.add_typer(mcp_policy_app, name="policy")


@mcp_policy_app.command("init")
def mcp_policy_init_command(
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing policy file."),
    ] = False,
    path: Annotated[
        Path | None,
        typer.Argument(
            help="Repo root.  Defaults to current directory.",
        ),
    ] = None,
) -> None:
    """Write a documented starter .onmc/mcp-policy.yaml for the MCP trust gateway.

    The generated file declares example server allow-lists, tool scopes
    (read / write / network), and approval-required lists with inline comments.

    Re-running is safe — the file is not overwritten unless --force is passed.
    """
    from oh_no_my_claudecode.rendering.console import render_mcp_policy

    repo_root = path.resolve() if path is not None else Path.cwd()
    policy_path_before = repo_root / ".onmc" / "mcp-policy.yaml"
    existed = policy_path_before.exists()
    result_path = _service().mcp_policy_init(force=force, repo_root=repo_root)
    written = not existed or force
    render_mcp_policy(result_path, written=written)


@mcp_app.command("check")
def mcp_check_command(
    calls_file: Annotated[
        Path | None,
        typer.Argument(
            help=(
                "Path to a JSONL file of recorded tool calls.  "
                "Each line: {\"server\": \"...\", \"tool\": \"...\", \"args\": {...}}.  "
                "Omit or pass '-' to read from stdin."
            ),
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit classifications as JSON to stdout."),
    ] = False,
    fail_on: Annotated[
        str,
        typer.Option(
            "--fail-on",
            help=(
                "Exit non-zero when any decision has this verdict or worse.  "
                "One of: block, approval_required.  Default: block."
            ),
        ),
    ] = "block",
    no_audit_log: Annotated[
        bool,
        typer.Option("--no-audit-log", help="Skip writing to .onmc/mcp-audit.log."),
    ] = False,
    path: Annotated[
        Path | None,
        typer.Option("--repo", help="Repo root for locating .onmc/mcp-policy.yaml."),
    ] = None,
) -> None:
    """Classify MCP tool calls from a JSONL file (or stdin) against the trust policy.

    Reads recorded tool-call events, applies the .onmc/mcp-policy.yaml policy,
    scans arguments for embedded secrets and prompt-injection phrases, and
    renders a decision table.

    Exit codes:

    - 0 — all calls pass the --fail-on threshold
    - 1 — at least one call blocked / requires approval (when threshold met)
    - 2 — usage error

    Example::

        onmc mcp check calls.jsonl --fail-on block
        cat calls.jsonl | onmc mcp check - --json
    """
    import sys as _sys

    valid_fail_on = ("block", "approval_required")
    if fail_on not in valid_fail_on:
        msg = f"--fail-on must be one of: {', '.join(valid_fail_on)}"
        raise typer.Exit(code=_fatal(msg))

    # Read source
    if calls_file is None or str(calls_file) == "-":
        calls_jsonl = _sys.stdin.read()
    else:
        if not calls_file.exists():
            msg = f"File not found: {calls_file}"
            raise typer.Exit(code=_fatal(msg))
        calls_jsonl = calls_file.read_text(encoding="utf-8")

    repo_root = path.resolve() if path is not None else Path.cwd()

    results = _service().mcp_check(
        calls_jsonl,
        repo_root=repo_root,
        write_audit_log=not no_audit_log,
    )

    if as_json:
        output_rows = []
        for call_obj, dec_obj in results:
            output_rows.append(
                {
                    "server": call_obj.server,
                    "tool": call_obj.tool,
                    "verdict": dec_obj.verdict,
                    "severity": dec_obj.severity,
                    "reasons": dec_obj.reasons,
                }
            )
        sys.stdout.write(json.dumps(output_rows, indent=2) + "\n")
    else:
        from oh_no_my_claudecode.rendering.console import render_mcp_decision_table

        render_mcp_decision_table(results)

    # Exit code gate
    _verdict_rank = {"allow": 0, "approval_required": 1, "block": 2}
    threshold_rank = _verdict_rank.get(fail_on, 2)
    for _call, dec in results:
        if _verdict_rank.get(dec.verdict, 0) >= threshold_rank:
            raise typer.Exit(code=1)


def _service() -> OnmcService:
    return OnmcService(Path.cwd())


def _claim_ledger() -> ClaimLedger:
    return ClaimLedger(discover_repo_root(Path.cwd()))


def _claims_payload(claims: list[Claim]) -> list[dict[str, object]]:
    return [
        {
            "owner": claim.owner,
            "path": claim.path,
            "acquired_at": claim.acquired_at,
            "expires_at": claim.expires_at,
        }
        for claim in claims
    ]


def _print_claim_conflicts(conflicts: list[Claim]) -> None:
    for conflict in conflicts:
        console.print(
            f"[red]Claim conflict:[/red] {conflict.path} is held by {conflict.owner} "
            f"until {conflict.expires_at:g}."
        )


@claim_app.command("acquire")
def claim_acquire_command(
    owner: Annotated[str, typer.Argument(help="Agent or process claiming the paths.")],
    paths: Annotated[list[str], typer.Argument(help="One or more file paths to claim.")],
    ttl_seconds: Annotated[
        int,
        typer.Option("--ttl-seconds", min=1, help="Lease duration in seconds."),
    ] = DEFAULT_TTL_SECONDS,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Acquire file/path leases for an owner."""
    try:
        result = _claim_ledger().acquire(owner, paths, ttl_seconds=ttl_seconds)
    except ValueError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    payload = {
        "ok": result.ok,
        "claims": _claims_payload(result.claims),
        "conflicts": _claims_payload(result.conflicts),
    }
    if json_output:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    elif result.ok:
        console.print(f"[green]Acquired {len(paths)} claim(s) for {owner}.[/green]")
    else:
        _print_claim_conflicts(result.conflicts)
    if not result.ok:
        raise typer.Exit(code=1)


@claim_app.command("release")
def claim_release_command(
    owner: Annotated[str, typer.Argument(help="Owner whose claim(s) should be released.")],
    path: Annotated[
        str | None,
        typer.Option("--path", help="Release only this path for the owner."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Release one path or all active paths for an owner."""
    try:
        result = _claim_ledger().release(owner, path=path)
    except ValueError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    payload = {
        "released": result.released,
        "claims": _claims_payload(result.claims),
    }
    if json_output:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        console.print(f"[green]Released {result.released} claim(s) for {owner}.[/green]")


@claim_app.command("status")
def claim_status_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Show active path claims."""
    result = _claim_ledger().status()
    payload = {"claims": _claims_payload(result.claims)}
    if json_output:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return
    if not result.claims:
        console.print("[dim]No active claims.[/dim]")
        return
    for claim in result.claims:
        console.print(f"{claim.path}  [cyan]{claim.owner}[/cyan]  expires {claim.expires_at:g}")


@claim_app.command("check")
def claim_check_command(
    paths: Annotated[list[str], typer.Argument(help="One or more file paths to check.")],
    owner: Annotated[
        str | None,
        typer.Option("--owner", help="Allow claims already held by this owner."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Check whether paths are free to claim."""
    try:
        result = _claim_ledger().check(paths, owner=owner)
    except ValueError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    payload = {
        "ok": result.ok,
        "claims": _claims_payload(result.claims),
        "conflicts": _claims_payload(result.conflicts),
    }
    if json_output:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    elif result.ok:
        console.print("[green]No active claim conflicts.[/green]")
    else:
        _print_claim_conflicts(result.conflicts)
    if not result.ok:
        raise typer.Exit(code=1)


@app.command("init")
def init_command() -> None:
    """Initialize ONMC state in the current git repository."""
    repo_root, config = _service().init_project()
    render_init_summary(repo_root.as_posix(), config)


@app.command("ingest", context_settings={"allow_extra_args": True, "ignore_unknown_options": False})
def ingest_command(
    ctx: typer.Context,
    files: Annotated[
        bool,
        typer.Option("--files", help="Ingest only the file paths passed after this flag."),
    ] = False,
    install_hook: Annotated[
        bool,
        typer.Option("--install-hook", help="Install the ONMC incremental post-commit hook."),
    ] = False,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Skip the optional LLM extraction pass."),
    ] = False,
) -> None:
    """Ingest repo knowledge into local structured memory."""
    try:
        if files and install_hook:
            raise typer.Exit(code=_fatal("Choose either --files or --install-hook, not both."))
        if install_hook:
            _, hook_path = _service().install_ingest_hook()
            console.print("[green]Incremental ingest hook installed.[/green]")
            console.print(f"[green]Hook path:[/green] {hook_path}")
            return
        if files:
            if not ctx.args:
                raise typer.Exit(code=_fatal("Provide one or more file paths after --files."))
            _, result = _service().ingest_files(list(ctx.args), no_llm=no_llm)
        else:
            if ctx.args:
                raise typer.Exit(code=_fatal("Unexpected trailing arguments."))
            _, result = _service().ingest(no_llm=no_llm)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_ingest_result(result)


@app.command("brief")
def brief_command(
    task: Annotated[str, typer.Option("--task", help="Task description to compile a brief for.")],
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Skip the optional LLM reranking pass."),
    ] = False,
    style: Annotated[
        BriefStyle,
        typer.Option("--style", help="Brief rendering style."),
    ] = BriefStyle.FULL,
    max_tokens: Annotated[
        int | None,
        typer.Option("--max-tokens", min=1, help="Trim markdown output to a token budget."),
    ] = None,
    stdout: Annotated[
        bool,
        typer.Option("--stdout", help="Print markdown only, optimized for agent paste context."),
    ] = False,
    terse: Annotated[
        bool,
        typer.Option("--terse", help="Emit compact terse output (overrides ONMC_TERSE env var)."),
    ] = False,
) -> None:
    """Compile a task-specific context brief."""
    from oh_no_my_claudecode.serialize.terse import is_terse, render_memories_terse

    try:
        _, artifact = _service().compile_brief(task, no_llm=no_llm)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    use_terse = terse or is_terse(default=False)
    if use_terse:
        memories = list(artifact.relevant_memories)
        console.print(render_memories_terse(memories), markup=False)
        return

    if stdout or style != BriefStyle.FULL or max_tokens is not None:
        markdown = artifact.to_markdown(style=style)
        if max_tokens is not None:
            markdown = limit_markdown_tokens(markdown, max_tokens)
        console.print(markdown.rstrip(), markup=False)
        return
    render_brief(artifact)
    console.print(f"[green]Wrote brief:[/green] {artifact.output_path}")


codegraph_app = typer.Typer(
    help=(
        "Structural repo graph — tiny, smart context for agents. "
        "Deterministic, offline (stdlib ast only)."
    ),
    no_args_is_help=True,
)
app.add_typer(codegraph_app, name="codegraph")


@codegraph_app.command("summary")
def codegraph_summary_command(
    max_files: Annotated[
        int,
        typer.Option("--max-files", min=1, help="Maximum hot files to include."),
    ] = 40,
    max_dirs: Annotated[
        int,
        typer.Option("--max-dirs", min=1, help="Maximum directories to include."),
    ] = 12,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the markdown codegraph to this path."),
    ] = None,
) -> None:
    """Generate a compact markdown codegraph for token-efficient navigation."""
    try:
        markdown = _service().codegraph(max_files=max_files, max_dirs=max_dirs)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if output is None:
        console.print(markdown.rstrip(), markup=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    typer.echo(f"Wrote codegraph: {output}")


@codegraph_app.command("build")
def codegraph_build_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the built graph as JSON."),
    ] = False,
) -> None:
    """Build the structural code graph and cache it to .onmc/codegraph.json."""
    try:
        cache_path, graph = _service().codegraph_build()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if json_output:
        sys.stdout.write(json.dumps(graph.to_dict(), indent=2, sort_keys=True) + "\n")
        return
    render_codegraph_build(cache_path, graph)


@codegraph_app.command("neighbors")
def codegraph_neighbors_command(
    target: Annotated[
        str,
        typer.Argument(help="File path or symbol name to compute the blast radius for."),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit neighbors as JSON."),
    ] = False,
) -> None:
    """Show the blast radius (importers + dependents + tests) of a file or symbol."""
    try:
        result = _service().codegraph_neighbors(target)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if json_output:
        sys.stdout.write(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n")
        return
    render_codegraph_neighbors(result)


@codegraph_app.command("context")
def codegraph_context_command(
    goal: Annotated[
        str,
        typer.Argument(help="Goal or task description to select relevant files for."),
    ],
    budget: Annotated[
        int,
        typer.Option("--budget", min=1, help="Maximum number of files to return."),
    ] = 8,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the selection as JSON."),
    ] = False,
) -> None:
    """Select a small, bounded set of files relevant to a goal."""
    try:
        result = _service().codegraph_context(goal, budget=budget)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if json_output:
        sys.stdout.write(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n")
        return
    render_codegraph_context(result)


@app.command("why")
def why_command(
    path: Annotated[str, typer.Argument(help="File path to explain (repo-relative or absolute).")],
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Skip the optional LLM narrative; deterministic only."),
    ] = False,
    at: Annotated[
        str,
        typer.Option(
            "--at",
            help=(
                "Bound the git-history section to this commit-ish (hash, tag, or branch). "
                "Memory entries reflect the current store and are NOT time-bounded."
            ),
        ),
    ] = "",
    terse: Annotated[
        bool,
        typer.Option("--terse", help="Emit compact terse output (overrides ONMC_TERSE env var)."),
    ] = False,
) -> None:
    """Explain why a file looks the way it does, from memory + git history."""
    from oh_no_my_claudecode.serialize.terse import is_terse, render_why_terse

    try:
        _, report = _service().why(path, no_llm=no_llm, at_commit=at)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    use_terse = terse or is_terse(default=False)
    if use_terse:
        console.print(render_why_terse(report), markup=False)
        return

    render_why_report(report)
    console.print(f"[green]Wrote why report:[/green] {report.output_path}")


@app.command("onboard")
def onboard_command(
    steps: Annotated[
        bool,
        typer.Option(
            "--steps",
            help=(
                "Print all tour stops at once and exit (non-interactive). "
                "Suitable for piping, CI, and tests."
            ),
        ),
    ] = False,
) -> None:
    """Give a new dev (or agent) the guided five-minute repo tour from memory.

    Compiles an ordered sequence of stops — danger zones, load-bearing decisions,
    top playbooks, and where to look first — entirely offline from stored ONMC
    memory. Interactive by default (paginated, press Enter to advance); use
    --steps for a single non-interactive dump.
    """
    from rich.console import Console as RichConsole

    from oh_no_my_claudecode.onboard.runner import run_onboard

    try:
        repo_root, tour = _service().onboard()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if steps:
        run_onboard(tour, steps=True, console=RichConsole())
        console.print(f"[green]Wrote onboarding artifact:[/green] {repo_root}")
        return

    run_onboard(tour, steps=False, console=RichConsole())
    render_onboard_summary(tour, output_path="")


@app.command("blame")
def blame_command(
    path: Annotated[str, typer.Argument(help="File path to blame (repo-relative or absolute).")],
    terse: Annotated[
        bool,
        typer.Option("--terse", help="Emit compact terse output (overrides ONMC_TERSE env var)."),
    ] = False,
) -> None:
    """Git blame for knowledge: map a file's symbols to the memories that govern them.

    Shows which recorded decisions, invariants, hotspots, and gotchas apply to
    each top-level symbol / section of the file.  Memories that reference the
    file but don't name a specific symbol appear in a file-level bucket.

    Symbol extraction is heuristic (regex, not AST) — results are approximate.
    Supported: .py, .ts, .tsx, .js, .jsx, .mjs, .cjs, .md, .mdx.
    """
    from oh_no_my_claudecode.serialize.terse import is_terse

    try:
        _, result = _service().blame(path)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    use_terse = terse or is_terse(default=False)
    if use_terse:
        # Compact terse: plain text lines
        lines = [f"blame: {result.path}"]
        if not result.has_data:
            lines.append("no recorded knowledge — run onmc ingest/mine")
        else:
            for anchor in result.anchors:
                line_label = f":{anchor.line}" if anchor.line is not None else ""
                lines.append(f"  {anchor.anchor}{line_label}")
                for memory in anchor.memories:
                    lines.append(f"    [{memory.kind.value}] {memory.title}")
            if result.file_level_memories:
                lines.append("  (whole file)")
                for memory in result.file_level_memories:
                    lines.append(f"    [{memory.kind.value}] {memory.title}")
        console.print("\n".join(lines), markup=False)
        return

    render_blame_result(result)
    console.print(f"[green]Wrote blame report:[/green] {result.output_path}")


@app.command("coverage")
def coverage_command(
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Emit the CoverageReport (and suggestions when --suggest) "
                "as JSON instead of the dashboard."
            ),
        ),
    ] = False,
    suggest: Annotated[
        bool,
        typer.Option(
            "--suggest",
            help=(
                "Print actionable documentation suggestions for each uncovered hotspot. "
                "Deterministic — no LLM required."
            ),
        ),
    ] = False,
    apply: Annotated[
        bool,
        typer.Option(
            "--apply",
            help=(
                "Create stub memory entries (confidence=0.2, tag=coverage-stub) for each "
                "suggestion that does not already exist. Implies --suggest. "
                "Idempotent: re-running skips stubs that already exist."
            ),
        ),
    ] = False,
) -> None:
    """Show a knowledge-gap dashboard: coverage % + uncovered hotspot files.

    Answers "which parts of this repo does the memory actually cover, and where
    are the blind spots?"  The killer feature is surfacing high-churn files that
    have zero memory coverage — those are the landmines most likely to cause
    regressions when touched without context.

    Pass --suggest to turn the gap dashboard into an actionable to-do list.
    Pass --apply to automatically create stub memory entries for each suggestion
    (idempotent — re-running skips entries that already exist).

    Requires at least one `onmc ingest` run (file stats must exist).
    """
    do_suggest = suggest or apply
    try:
        _, report, suggestions = _service().coverage(suggest=do_suggest, apply=apply)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        import dataclasses

        if do_suggest:
            payload: dict[str, object] = {
                "report": dataclasses.asdict(report),
                "suggestions": [dataclasses.asdict(s) for s in suggestions],
            }
            console.print(json.dumps(payload, indent=2), markup=False)
        else:
            console.print(
                json.dumps(dataclasses.asdict(report), indent=2),
                markup=False,
            )
        return

    render_coverage_summary(report)
    if do_suggest:
        render_coverage_suggestions(suggestions)
        if apply:
            console.print(
                f"[green]Applied:[/green] {len(suggestions)} stub(s) created or already present."
            )


@app.command("memory-diff")
def memory_diff_command(
    commit_a: Annotated[
        str,
        typer.Argument(help="Older commit-ish (hash, tag, or branch name)."),
    ],
    commit_b: Annotated[
        str,
        typer.Argument(help="Newer commit-ish (hash, tag, or branch name)."),
    ],
) -> None:
    """Show what repo knowledge changed between two commits.

    Diffs the committed `.agent-memory/` JSON snapshots at commitA and commitB.
    Reports added, removed, and changed memory entries by id and title.

    When `.agent-memory/` is not committed at either point, falls back to a plain
    git diff of changed files and clearly labels the output as fallback mode.

    Run `onmc sync --commit` and commit `.agent-memory/` to unlock full diffs.
    """
    try:
        _, result = _service().memory_diff(commit_a, commit_b)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_memory_diff(result)
    from oh_no_my_claudecode.timetravel.memory_diff import memory_diff_to_markdown

    markdown = memory_diff_to_markdown(result)
    console.print(
        "[green]Wrote memory-diff artifact:[/green] (see .onmc/compiled/ for the markdown)"
    )
    _ = markdown  # artifact already written by service.memory_diff()


@app.command("digest")
def digest_command(
    since: Annotated[
        str,
        typer.Option(
            "--since",
            help="Git ref (tag, branch, commit hash) to diff knowledge from.",
        ),
    ],
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of a rich terminal report."),
    ] = False,
) -> None:
    """Show what the repo/team learned since a git ref.

    Produces a knowledge changelog grouped by kind (Decisions, Invariants,
    Gotchas, Failed Approaches, …) covering memories added or updated since
    *since*.

    Prefers committed ``.agent-memory/`` snapshots for precision; falls back to
    live ``created_at`` filtering when the committed export is absent at the
    given ref.

    The report is also written as a markdown artifact to ``.onmc/compiled/``.

    \b
    Examples:
      onmc digest --since v1.2.0
      onmc digest --since main
      onmc digest --since abc1234
    """
    import json as _json
    import sys as _sys

    from rich.panel import Panel

    from oh_no_my_claudecode.serialize.terse import is_terse

    try:
        artifact_path, result = _service().digest(since)
    except ValueError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if output_json:
        payload: dict[str, object] = {
            "since_ref": result.since_ref,
            "since_short": result.since_short,
            "since_date": result.since_date,
            "head_short": result.head_short,
            "head_date": result.head_date,
            "source": result.source,
            "fallback_reason": result.fallback_reason,
            "total": result.total,
            "by_kind": {
                kind.value: [
                    {
                        "id": e.id,
                        "kind": e.kind.value,
                        "title": e.title,
                        "summary": e.summary,
                        "change_type": e.change_type,
                    }
                    for e in entries
                ]
                for kind, entries in result.by_kind.items()
            },
        }
        # Use sys.stdout directly so Rich doesn't word-wrap inside JSON strings.
        _sys.stdout.write(_json.dumps(payload, indent=2) + "\n")
        return

    terse = is_terse(default=False)

    since_label = (
        f"{result.since_ref} ({result.since_short})"
        if result.since_short != result.since_ref
        else result.since_ref
    )
    console.print(
        Panel.fit(
            f"Since: [bold]{since_label}[/bold] — {result.since_date}\n"
            f"As of: [bold]{result.head_short}[/bold] — {result.head_date}\n"
            f"Source: [dim]{result.source}[/dim]",
            title="onmc digest",
        )
    )

    if result.fallback_reason:
        console.print(f"[yellow]Note:[/yellow] {result.fallback_reason}")
        console.print()

    if result.total == 0:
        console.print("[dim]Nothing new learned since this ref.[/dim]")
    else:
        from rich.table import Table

        from oh_no_my_claudecode.digest.compiler import _KIND_LABELS, _SECTION_ORDER
        from oh_no_my_claudecode.utils.text import shorten

        for kind in _SECTION_ORDER:
            bucket = result.by_kind.get(kind)
            if not bucket:
                continue
            section_label = _KIND_LABELS.get(kind, kind.value.replace("_", " ").title())
            table = Table(title=section_label, show_header=True)
            table.add_column("", style="dim", width=2)
            table.add_column("Title", min_width=28)
            if not terse:
                table.add_column("Summary", min_width=44)
            for entry in bucket:
                badge = "[green]+[/green]" if entry.change_type == "added" else "[yellow]~[/yellow]"
                if terse:
                    table.add_row(badge, entry.title)
                else:
                    table.add_row(badge, entry.title, shorten(entry.summary, max_length=80))
            console.print(table)

    console.print(f"[green]Wrote digest artifact:[/green] {artifact_path}")


@app.command("guard")
def guard_command(
    task: Annotated[str, typer.Option("--task", help="Task description to check for dead-ends.")],
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, help="Maximum number of dead-end entries to return."),
    ] = 8,
    terse: Annotated[
        bool,
        typer.Option("--terse", help="Emit compact terse output (overrides ONMC_TERSE env var)."),
    ] = False,
) -> None:
    """Surface recorded dead-ends so you never repeat a known failure."""
    from oh_no_my_claudecode.config import compiled_dir, load_config
    from oh_no_my_claudecode.serialize.terse import is_terse, render_guard_terse
    from oh_no_my_claudecode.utils.time import utc_now

    try:
        repo_root, result = _service().guard(task, limit=limit)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    use_terse = terse or is_terse(default=False)
    if use_terse:
        console.print(render_guard_terse(result.entries, task, max_items=limit), markup=False)
        return

    markdown = result.to_markdown()

    if result.has_dead_ends:
        from rich.panel import Panel

        console.print(
            Panel.fit(
                markdown.rstrip(),
                title="[bold red]Guard: DO NOT retry these dead-ends[/bold red]",
                border_style="red",
            )
        )
    else:
        console.print("[green]Guard: no recorded dead-ends match this task.[/green]")

    # Write artifact to .onmc/compiled/<ts>-guard.md
    try:
        config = load_config(repo_root)
        out_dir = compiled_dir(config, repo_root)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = utc_now().strftime("%Y%m%d-%H%M%S")
        artifact_path = out_dir / f"{ts}-guard.md"
        artifact_path.write_text(markdown, encoding="utf-8")
        console.print(f"[green]Wrote guard artifact:[/green] {artifact_path}")
    except Exception:  # noqa: BLE001, S110
        pass  # artifact write failure must not break the command


@app.command("recall")
def recall_command(
    query: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Error text or stacktrace to search for. "
                "Omit to read from stdin (pipe-friendly: `cmd 2>&1 | onmc recall`)."
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, help="Maximum number of incident matches to return."),
    ] = 8,
    terse: Annotated[
        bool,
        typer.Option("--terse", help="Emit compact terse output (overrides ONMC_TERSE env var)."),
    ] = False,
) -> None:
    """Search memory for past incidents matching an error or stacktrace.

    Paste an error message or stacktrace as an argument or pipe it via stdin.
    Returns prior failures/fixes that match, ranked by relevance.

    Examples:

      onmc recall "TypeError: cannot read property x of undefined"

      cat error.log | onmc recall
    """
    import sys

    from oh_no_my_claudecode.config import compiled_dir, load_config
    from oh_no_my_claudecode.serialize.terse import is_terse, render_incident_recall_terse
    from oh_no_my_claudecode.utils.time import utc_now

    # Resolve query: argument takes priority; fall back to stdin.
    raw_query: str
    if query is not None:
        raw_query = query
    elif not sys.stdin.isatty():
        raw_query = sys.stdin.read()
    else:
        _fatal("Provide an error/stacktrace as an argument or pipe it via stdin.")
        raise typer.Exit(code=1)

    try:
        repo_root, result = _service().recall(raw_query, limit=limit)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    use_terse = terse or is_terse(default=False)
    if use_terse:
        console.print(
            render_incident_recall_terse(result.entries, raw_query, max_items=limit),
            markup=False,
        )
        return

    markdown = result.to_markdown()

    if result.has_matches:
        from rich.panel import Panel

        console.print(
            Panel.fit(
                markdown.rstrip(),
                title="[bold cyan]Seen this before?[/bold cyan]",
                border_style="cyan",
            )
        )
    else:
        console.print(
            f"[yellow]Recall: no recorded incidents match this error.[/yellow]\n"
            f"[dim]{result.no_data_hint}[/dim]"
        )

    # Write artifact to .onmc/compiled/<ts>-recall.md
    try:
        config = load_config(repo_root)
        out_dir = compiled_dir(config, repo_root)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = utc_now().strftime("%Y%m%d-%H%M%S")
        artifact_path = out_dir / f"{ts}-recall.md"
        artifact_path.write_text(markdown, encoding="utf-8")
        console.print(f"[green]Wrote recall artifact:[/green] {artifact_path}")
    except Exception:  # noqa: BLE001, S110
        pass  # artifact write failure must not break the command


@app.command("reuse")
def reuse_command(
    query: Annotated[
        str,
        typer.Argument(
            help="A description of the behaviour you need, or an existing symbol name.",
        ),
    ],
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, help="Maximum number of reuse hits to return."),
    ] = 8,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the ranked hits as JSON instead of a table."),
    ] = False,
    use_ast_grep: Annotated[
        bool,
        typer.Option(
            "--ast-grep/--no-ast-grep",
            help=(
                "Use ast-grep (the 'ast-grep' or 'sg' binary) for structural/AST-pattern"
                " matching in addition to the text heuristic.  No-op when neither binary"
                " is on PATH (falls back to text-only, zero regression)."
            ),
        ),
    ] = False,
) -> None:
    """Surface existing code that already does a thing — reuse before reimplementing.

    Indexes the repo with stdlib `ast` and ranks top-level functions/classes by
    how well their name, docstring, and argument names match your query.
    Entirely offline and deterministic — no LLM, no network.

    With ``--ast-grep`` (and the ``ast-grep``/``sg`` binary installed), also runs
    structural AST-pattern matching that catches structurally-similar code even
    when variable names differ.

    Examples:

      onmc reuse "tokenize text into words"

      onmc reuse tokenize --json

      onmc reuse "def $F($$$ARGS):" --ast-grep
    """
    try:
        _, hits, structural_hits = _service().reuse_find(query, limit=limit, ast_grep=use_ast_grep)
    except RepoDiscoveryError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        import dataclasses

        payload: dict[str, object] = {
            "hits": [dataclasses.asdict(hit) for hit in hits],
            "structural": [dataclasses.asdict(m) for m in structural_hits],
        }
        console.print(json.dumps(payload, indent=2), markup=False)
        return

    render_reuse_hits(hits, query)
    if structural_hits:
        console.print(
            f"\n[bold]Structural matches (ast-grep)[/bold]: {len(structural_hits)} found",
            markup=True,
        )
        for match in structural_hits:
            loc = f"{match.file}:{match.line_start}-{match.line_end}"
            snippet = repr(match.text[:80])
            console.print(f"  [cyan]{loc}[/cyan]  {snippet}", markup=True)


@app.command("ask")
def ask_command(
    question: Annotated[
        str,
        typer.Argument(help="Natural-language question to answer from repo memory."),
    ],
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, help="Maximum number of memory entries to rank."),
    ] = 8,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit result as JSON."),
    ] = False,
    no_synth: Annotated[
        bool,
        typer.Option("--no-synth", help="Skip LLM synthesis and return ranked entries only."),
    ] = False,
) -> None:
    """Ask a natural-language question answered from repo memory.

    Returns the most relevant memories with citations.  When an LLM provider
    is configured, also synthesizes a concise answer grounded in those memories.
    Ranking and citations always work offline — synthesis is best-effort and
    its failure never breaks the command.

    Examples:

      onmc ask "why do we avoid bypassing the cache boundary?"

      onmc ask "what failed when we tried to use X?" --no-synth

      onmc ask "what is the auth decision?" --json
    """
    import dataclasses

    try:
        _, result = _service().ask(question, limit=limit, synthesize=not no_synth)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        # Use sys.stdout.write to avoid Rich's line-wrapping breaking JSON.
        sys.stdout.write(json.dumps(dataclasses.asdict(result), default=str) + "\n")
        return

    render_ask_result(result)


@app.command("check")
def check_command(
    staged: Annotated[
        bool,
        typer.Option("--staged", help="Check git-staged files (default)."),
    ] = True,
    files: Annotated[
        list[str] | None,
        typer.Option("--file", help="Explicit file paths to check (repeat for multiple)."),
    ] = None,
    base: Annotated[
        str | None,
        typer.Option("--base", help="Diff against this git ref instead of staged files."),
    ] = None,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Exit nonzero when warn-level findings exist."),
    ] = False,
    install_hook: Annotated[
        bool,
        typer.Option("--install-hook", help="Install onmc check as a git pre-commit hook."),
    ] = False,
) -> None:
    """Flag staged/changed files that touch recorded invariants or dead-ends.

    By default checks all git-staged files (``git diff --cached --name-only``).
    Pass ``--file`` to check explicit paths.  Pass ``--base <ref>`` to diff
    against a git ref.

    Exit code is 0 by default (warn-only).  Pass ``--strict`` to exit nonzero
    when any warn-level findings are present.

    Pass ``--install-hook`` to wire this command as an idempotent git
    pre-commit hook (appends to any existing hook; never clobbers it).
    """
    import subprocess

    from oh_no_my_claudecode.check import CheckSeverity, install_pre_commit_hook, run_check
    from oh_no_my_claudecode.core.repo import discover_repo_root

    try:
        repo_root = discover_repo_root(Path.cwd())
    except Exception as exc:  # noqa: BLE001
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if install_hook:
        hook_path, was_created = install_pre_commit_hook(repo_root)
        if was_created:
            console.print(f"[green]Pre-commit hook installed:[/green] {hook_path}")
        else:
            console.print(
                f"[green]Pre-commit hook updated (onmc block appended):[/green] {hook_path}"
            )
        return

    # Resolve file list from the requested source.
    changed_files: list[str]
    if files:
        changed_files = list(files)
    elif base is not None:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", base, "HEAD"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            changed_files = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        except subprocess.CalledProcessError as exc:
            raise typer.Exit(code=_fatal(f"git diff failed: {exc.stderr.strip()}")) from exc
    else:
        # Default: staged files.
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            changed_files = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
        except subprocess.CalledProcessError as exc:
            raise typer.Exit(code=_fatal(f"git diff failed: {exc.stderr.strip()}")) from exc

    if not changed_files:
        console.print("[dim]onmc check: no files to check.[/dim]")
        return

    try:
        _, _, storage = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError:
        # onmc not initialized — silently skip (don't block the commit).
        console.print("[dim]onmc check: store not initialized, skipping.[/dim]")
        return

    check_result = run_check(repo_root, storage, changed_files)

    if not check_result.findings:
        console.print(
            f"[green]onmc check:[/green] {len(changed_files)} file(s) checked, no findings."
        )
        return

    # Group findings by file for readable output.
    from collections import defaultdict

    from oh_no_my_claudecode.check import CheckFinding

    by_file: dict[str, list[CheckFinding]] = defaultdict(list)
    for finding in check_result.findings:
        by_file[finding.rel_path].append(finding)

    console.print(
        f"[bold]onmc check[/bold] — {len(changed_files)} file(s), "
        f"{check_result.warn_count} warning(s), {check_result.info_count} info(s)"
    )
    console.print()

    for rel_path, path_findings in sorted(by_file.items()):
        console.print(f"[bold]{rel_path}[/bold]")
        for finding in path_findings:
            if finding.severity == CheckSeverity.WARN:
                prefix = "  [yellow]WARNING[/yellow]"
            else:
                prefix = "  [dim]INFO[/dim]   "
            short_summary = finding.summary[:120]
            if len(finding.summary) > 120:
                short_summary += "..."
            console.print(f"{prefix} [{finding.kind}] {finding.title}")
            console.print(f"         {short_summary}")
        console.print()

    if strict and check_result.has_warnings:
        raise typer.Exit(code=1)


@app.command("ui")
def ui_command(
    host: Annotated[
        str,
        typer.Option("--host", help="Dashboard bind address."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", min=0, max=65535, help="Dashboard TCP port."),
    ] = 8765,
    open_browser: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open the dashboard in a browser."),
    ] = True,
    export_path: Annotated[
        Path | None,
        typer.Option("--export", help="Write a standalone HTML snapshot instead of serving."),
    ] = None,
) -> None:
    """Open the local read-only ONMC visual dashboard."""
    service = _service()
    try:
        service.status()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if export_path is not None:
        written = export_dashboard_snapshot(service, export_path)
        console.print(f"[green]Dashboard snapshot:[/green] {written}")
        console.print("[yellow]Review repository memory before sharing this file.[/yellow]")
        if open_browser:
            import webbrowser

            webbrowser.open(written.as_uri())
        return
    if host not in {"127.0.0.1", "localhost", "::1"}:
        console.print(
            "[yellow]Warning: non-loopback binding exposes repository memory "
            "to your network.[/yellow]"
        )
    serve_dashboard(service, host=host, port=port, open_browser=open_browser)


@app.command("status")
def status_command() -> None:
    """Show local ONMC status."""
    try:
        render_status(_service().status())
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc


@app.command("statusline")
def statusline_command() -> None:
    """Print a compact one-line brain health string for Claude Code statusLine.

    Example output: 🧠 142 mem · 87% fresh · 3 stale · 12k tok/day

    Wire into Claude Code by adding to your settings.json:
      \"statusLine\": \"onmc statusline\"
    """
    svc = _service()
    typer.echo(svc.statusline())


@app.command("hud")
def hud_command() -> None:
    """Display a rich multi-line memory health HUD panel."""
    try:
        health = _service().memory_health()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_hud(health)


@app.command("report")
def report_command(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the markdown report to this path."),
    ] = None,
) -> None:
    """Generate a shareable agent-readiness report."""
    try:
        report = _service().agent_readiness_report()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if output is None:
        console.print(report.rstrip(), markup=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    typer.echo(f"Wrote report: {output}")


@app.command("sync")
def sync_command(
    commit: Annotated[bool, typer.Option("--commit", help="Export to .agent-memory/.")] = False,
    restore: Annotated[
        bool,
        typer.Option("--restore", help="Restore from .agent-memory/."),
    ] = False,
    install_hook: Annotated[
        bool,
        typer.Option("--install-hook", help="Install a post-commit sync hook."),
    ] = False,
) -> None:
    """Export, restore, or hook git-portable ONMC memory state."""
    selected = [commit, restore, install_hook]
    if sum(1 for item in selected if item) != 1:
        raise typer.Exit(
            code=_fatal("Choose exactly one of --commit, --restore, or --install-hook.")
        )
    try:
        if commit:
            _, result = _service().sync_commit()
            render_sync_result(result, action="Sync Export Complete")
            console.print(
                "[green]Exported "
                f"{result.memory_count} memories, "
                f"{result.task_count} tasks to .agent-memory/[/green]"
            )
            console.print(
                "Add .agent-memory/ to git tracking: "
                "`git add .agent-memory/ && git commit -m 'chore: add agent memory export'`"
            )
            return
        if restore:
            _, result = _service().sync_restore()
            render_sync_result(result, action="Sync Restore Complete")
            console.print(
                "[green]Restored "
                f"{result.memory_count} memories, "
                f"{result.task_count} tasks from .agent-memory/[/green]"
            )
            return
        _, hook_path = _service().install_sync_hook()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    console.print(
        "post-commit hook installed. Memory will export to .agent-memory/ on every commit."
    )
    console.print(f"[green]Hook path:[/green] {hook_path}")


@app.command("pull")
def pull_command(
    source: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Local path to another repo (or its .agent-memory/ dir), "
                "or a remote git URL (https://, git@, ssh://). "
                "Omit when using --all."
            )
        ),
    ] = None,
    pull_all: Annotated[
        bool,
        typer.Option(
            "--all",
            help=(
                "Pull from every source listed in federation.sources in config.yaml. "
                "Mutually exclusive with the SOURCE argument."
            ),
        ),
    ] = False,
    repo_label: Annotated[
        str | None,
        typer.Option(
            "--label",
            help=(
                "Override the short repo label used for the federated:<label> tag. "
                "For local paths defaults to the source directory name; "
                "for git URLs defaults to the last path segment of the URL. "
                "Ignored when --all is used."
            ),
        ),
    ] = None,
    ref: Annotated[
        str | None,
        typer.Option(
            "--ref",
            help=(
                "Branch, tag, or commit-ish to check out when cloning a remote git URL. "
                "Ignored for local paths and when --all is used."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="List what would be pulled without writing any memories (--all only).",
        ),
    ] = False,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Emit a machine-readable JSON summary to stdout."),
    ] = False,
) -> None:
    """Import another repo's .agent-memory/ export into this brain (federated memories).

    SOURCE can be a local filesystem path or a remote git URL:

    \b
      onmc pull ../sibling-repo
      onmc pull https://github.com/org/repo
      onmc pull git@github.com:org/repo.git --ref main
      onmc pull https://github.com/org/repo --label my-label
      onmc pull --all
      onmc pull --all --dry-run

    Federated memories are tagged ``federated:<repo-label>`` so they are clearly
    attributed to their source and are never confused with local memories.
    Re-pulling is idempotent: memories already present are skipped.

    When SOURCE is a git URL the repo is shallow-cloned to a temporary directory,
    its .agent-memory/ export is imported, and the clone is cleaned up immediately.

    Use --all to pull from every source configured in ``federation.sources`` in
    config.yaml.  One failing source never aborts the rest.
    """
    from oh_no_my_claudecode.federation.remote import is_git_url

    # --all mode: pull all configured federation sources
    if pull_all:
        if source is not None:
            raise typer.Exit(
                code=_fatal("Pass either a SOURCE argument or --all, not both.")
            )
        try:
            _, results = _service().pull_all(dry_run=dry_run)
        except FileNotFoundError as exc:
            raise typer.Exit(code=_fatal(str(exc))) from exc

        if not results:
            console.print(
                "[yellow]No federation sources configured.[/yellow]\n"
                "Add sources to config.yaml under [bold]federation.sources[/bold], e.g.:\n\n"
                "  federation:\n"
                "    sources:\n"
                "      - ../sibling-repo\n"
                "      - https://github.com/org/shared-brain\n"
            )
            raise typer.Exit(code=0)

        if output_json:
            payload: list[dict[str, object]] = []
            for src_id, outcome in results:
                if isinstance(outcome, Exception):
                    payload.append({"source": src_id, "error": str(outcome)})
                else:
                    payload.append(
                        {
                            "source": outcome.source,
                            "repo_label": outcome.repo_label,
                            "imported": outcome.imported,
                            "skipped": outcome.skipped,
                        }
                    )
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
            has_errors = any(isinstance(r, Exception) for _, r in results)
            raise typer.Exit(code=1 if has_errors else 0)

        render_pull_all_summary(results, dry_run=dry_run)
        has_errors = any(isinstance(r, Exception) for _, r in results)
        raise typer.Exit(code=1 if has_errors else 0)

    # Single-source mode (original behaviour)
    if source is None:
        raise typer.Exit(
            code=_fatal(
                "Provide a SOURCE argument or use --all to pull all configured sources."
            )
        )

    if dry_run:
        raise typer.Exit(code=_fatal("--dry-run is only valid with --all."))

    try:
        if is_git_url(source):
            _, result = _service().pull(source, ref=ref, repo_label=repo_label)
        else:
            _, result = _service().pull(Path(source).resolve(), ref=ref, repo_label=repo_label)
    except (FileNotFoundError, RuntimeError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if output_json:
        typer.echo(
            json.dumps(
                {
                    "source": result.source,
                    "repo_label": result.repo_label,
                    "imported": result.imported,
                    "skipped": result.skipped,
                }
            )
        )
        return

    console.print(
        f"[green]Pulled from[/green] {result.source} [dim](label: {result.repo_label})[/dim]"
    )
    console.print(
        f"  imported: [bold]{result.imported}[/bold]  skipped (already present): {result.skipped}"
    )


@app.command("serve")
def serve_command(
    mcp: Annotated[
        bool,
        typer.Option("--mcp", help="Run the ONMC MCP server over stdio."),
    ] = False,
    repo: Annotated[
        str,
        typer.Option("--repo", help="Repository path to serve (resolved once at startup)."),
    ] = ".",
) -> None:
    """Serve ONMC over the requested runtime protocol."""
    if not mcp:
        raise typer.Exit(code=_fatal("Use `onmc serve --mcp` to run the MCP server."))
    try:
        run_mcp_server(Path(repo).resolve())
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc


@app.command("solve")
def solve_command(
    task: Annotated[str, typer.Option("--task", help="Engineering task to solve.")],
    task_id: Annotated[
        str | None,
        typer.Option("--task-id", help="Optional existing task to link this output to."),
    ] = None,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Use heuristic fallback instead of the configured LLM."),
    ] = False,
) -> None:
    """Compile repo-aware context and ask the configured LLM for the next best approach."""
    try:
        _, record, output = _service().solve(task=task, task_id=task_id, no_llm=no_llm)
    except (
        FileNotFoundError,
        LookupError,
        ValueError,
        LLMConfigurationError,
        LLMProviderError,
    ) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_solve_output(output, record)
    console.print(f"[green]Wrote output:[/green] {record.markdown_path}")


@app.command("review")
def review_command(
    task: Annotated[str, typer.Option("--task", help="Task or proposed change to review.")],
    input_file: Annotated[
        Path | None,
        typer.Option("--input-file", help="Optional file containing plan, diff, or notes."),
    ] = None,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Use heuristic fallback instead of the configured LLM."),
    ] = False,
) -> None:
    """Compile repo-aware review context and critique the proposed approach."""
    try:
        external_input = input_file.read_text(encoding="utf-8") if input_file else None
        _, record, output = _service().review(
            task=task,
            external_input=external_input,
            no_llm=no_llm,
        )
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        LLMConfigurationError,
        LLMProviderError,
    ) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_review_output(output, record)
    console.print(f"[green]Wrote output:[/green] {record.markdown_path}")


@app.command("teach")
def teach_command(
    task: Annotated[str, typer.Option("--task", help="Task to explain and teach from.")],
    task_id: Annotated[
        str | None,
        typer.Option("--task-id", help="Optional existing task to link this output to."),
    ] = None,
    interactive: Annotated[
        bool,
        typer.Option("--interactive", help="Enter a follow-up Q&A loop after the initial output."),
    ] = False,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Use heuristic fallback instead of the configured LLM."),
    ] = False,
) -> None:
    """Compile repo-aware teaching context and generate a learning artifact."""
    try:
        _, record, output = _service().teach(task=task, task_id=task_id, no_llm=no_llm)
    except (
        FileNotFoundError,
        LookupError,
        ValueError,
        LLMConfigurationError,
        LLMProviderError,
    ) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_teach_output(output, record)
    console.print(f"[green]Wrote output:[/green] {record.markdown_path}")
    if interactive and not no_llm:
        while True:
            question = typer.prompt("Ask a follow-up question (or press Enter to exit)", default="")
            if not question.strip():
                break
            try:
                answer = _service().teach_followup(task=task, question=question, task_id=task_id)
            except (FileNotFoundError, ValueError, LLMConfigurationError, LLMProviderError) as exc:
                raise typer.Exit(code=_fatal(str(exc))) from exc
            console.print(answer)


@llm_app.command("status")
def llm_status_command() -> None:
    """Show optional LLM provider configuration status."""
    try:
        _, status = _service().llm_status()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_llm_status(status)


@llm_app.command("configure")
def llm_configure_command(
    provider: Annotated[
        LLMProviderType,
        typer.Option("--provider", help="LLM provider to configure."),
    ],
    model: Annotated[str, typer.Option("--model", help="Default model name.")],
    api_key_env_var: Annotated[
        str | None,
        typer.Option(
            "--api-key-env-var",
            help="Environment variable to read the provider API key from.",
        ),
    ] = None,
    temperature: Annotated[
        float,
        typer.Option("--temperature", min=0.0, max=2.0, help="Default temperature."),
    ] = 0.0,
    max_tokens: Annotated[
        int,
        typer.Option("--max-tokens", min=1, help="Default maximum output tokens."),
    ] = 1024,
) -> None:
    """Persist optional LLM provider settings to the local ONMC config."""
    try:
        _, settings = _service().configure_llm(
            provider=provider,
            model=model,
            api_key_env_var=api_key_env_var,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_llm_configured(settings)


@hooks_app.command("install")
def hooks_install_command(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Accept defaults without prompting."),
    ] = False,
    no_mcp: Annotated[
        bool,
        typer.Option("--no-mcp", help="Skip MCP server setup."),
    ] = False,
) -> None:
    """Install project-scoped Claude Code hooks into .claude/settings.json."""
    try:
        add_mcp_server = False if no_mcp else yes
        if not yes and not no_mcp:
            add_mcp_server = typer.confirm(
                "Register ONMC as a project MCP server (.mcp.json)?",
                default=False,
            )
        result, status = _service().install_hooks(add_mcp_server=add_mcp_server)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    console.print(
        "Hooks installed for this repo. Claude Code snapshots context before compaction "
        "(PreCompact) and injects a continuation brief after it (SessionStart: compact)."
    )
    if result.legacy_global_cleaned:
        console.print(
            "[yellow]Removed legacy onmc entries from the global ~/.claude/settings.json.[/yellow]"
        )
    console.print(f"[green]Backup:[/green] {status.backup_path}")
    render_hook_status(status)


@hooks_app.command("uninstall")
def hooks_uninstall_command() -> None:
    """Remove ONMC entries from project Claude Code settings and .mcp.json."""
    try:
        status = _service().uninstall_hooks()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    console.print(
        "ONMC hooks removed from .claude/settings.json and .mcp.json. "
        "The .onmc-backup file is kept as a safety artifact."
    )
    render_hook_status(status)


@hooks_app.command("status")
def hooks_status_command() -> None:
    """Show current Claude hook installation and snapshot status."""
    try:
        status = _service().hooks_status()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_hook_status(status)


def _read_hook_payload() -> dict[str, object]:
    """Read the Claude Code hook JSON payload from stdin, tolerating absence.

    Hook commands receive a JSON payload on stdin. Missing, empty, or invalid
    stdin yields an empty payload so the hooks degrade to their no-context
    behavior instead of failing.
    """
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


@hooks_app.command("pre-compact")
def hooks_pre_compact_command() -> None:
    """Capture a compaction snapshot before Claude Code compacts context."""
    try:
        payload = _read_hook_payload()
        raw_transcript = payload.get("transcript_path")
        transcript_path = (
            Path(raw_transcript) if isinstance(raw_transcript, str) and raw_transcript else None
        )
        _service().pre_compact(transcript_path=transcript_path)
    except Exception as exc:  # noqa: BLE001 - hook commands must never block the session.
        typer.echo(f"ONMC pre-compact warning: {exc}", err=True)


def _run_session_start_hook() -> None:
    """Emit the SessionStart additionalContext JSON.

    Stdout must contain ONLY the hook JSON — Claude Code parses it verbatim to
    inject context into the model. Diagnostics go to stderr and the command
    always exits 0 so a failure never blocks the session.

    Branches on the ``source`` field from the stdin payload:
    - ``"compact"`` or absent/unknown: emit the continuation brief.
    - ``"startup"``, ``"resume"``, ``"clear"``: emit the boot digest.
    """
    try:
        payload = _read_hook_payload()
        source = payload.get("source", "")
        if isinstance(source, str) and source in {"startup", "resume", "clear"}:
            digest_md, _ = _service().boot_digest()
            if digest_md:
                sys.stdout.write(session_start_context_json(digest_md) + "\n")
            return
        # source == "compact" or absent/unknown -- emit continuation brief.
        _, brief_md = _service().session_start()
        sys.stdout.write(session_start_context_json(brief_md) + "\n")
    except Exception as exc:  # noqa: BLE001 - hook commands must never block the session.
        typer.echo(f"ONMC session-start warning: {exc}", err=True)


@hooks_app.command("session-start")
def hooks_session_start_command() -> None:
    """Inject context at session start: boot digest on startup, continuation brief after compaction."""  # noqa: E501
    _run_session_start_hook()


@hooks_app.command("post-compact", hidden=True, deprecated=True)
def hooks_post_compact_command() -> None:
    """Deprecated alias for `onmc hooks session-start`."""
    _run_session_start_hook()


@hooks_app.command("prompt-recall")
def hooks_prompt_recall_command() -> None:
    """Inject the most relevant repo memories for the current user prompt.

    Reads the UserPromptSubmit JSON payload from stdin, extracts the ``prompt``
    field, searches stored memory for relevant entries, and writes the
    UserPromptSubmit additionalContext JSON to stdout.  Stdout is always pure
    JSON or empty — never mixed with diagnostics.  Always exits 0.
    """
    try:
        payload = _read_hook_payload()
        raw_prompt = payload.get("prompt", "")
        prompt = raw_prompt if isinstance(raw_prompt, str) else ""
        if not prompt.strip():
            return
        # Use the safe wrapper that enforces a timeout budget and swallows all
        # exceptions — hooks must never block or crash the host agent session.
        from oh_no_my_claudecode.hooks.prompt_recall import compile_prompt_recall_safe

        try:
            _repo_root, _config, storage = _service()._load_context()  # noqa: SLF001
        except Exception:  # noqa: BLE001
            return
        recall_text, _ = compile_prompt_recall_safe(storage, prompt)
        if recall_text:
            sys.stdout.write(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": recall_text,
                        }
                    }
                )
                + "\n"
            )
    except Exception:  # noqa: BLE001, S110 - hook commands must never block the session.
        pass


@hooks_app.command("session-end")
def hooks_session_end_command() -> None:
    """Run memory consolidation and heuristic auto-capture on SessionEnd.

    Called automatically by the Claude Code SessionEnd hook.  Reads the event
    payload from stdin (session_id, transcript_path, cwd, reason), runs a
    best-effort consolidation pass followed by heuristic auto-capture of
    durable memory from the just-ended session transcript.  Errors are
    swallowed; stdout is never written (SessionEnd hooks cannot inject
    context).

    Set ``ONMC_AUTOCAPTURE=0`` in the environment to disable auto-capture
    while keeping consolidation active.
    """
    import contextlib
    import os

    payload: dict[str, object] = {}
    with contextlib.suppress(Exception):
        payload = _read_hook_payload()
    with contextlib.suppress(Exception):  # noqa: SIM117
        _service().consolidate(dry_run=False)
    # Auto-capture — opt-out via env var.
    if os.environ.get("ONMC_AUTOCAPTURE", "1") == "0":
        return
    with contextlib.suppress(Exception):
        raw_session_id = payload.get("session_id")
        session_id = raw_session_id if isinstance(raw_session_id, str) and raw_session_id else None
        raw_transcript = payload.get("transcript_path")
        transcript_path = (
            Path(raw_transcript) if isinstance(raw_transcript, str) and raw_transcript else None
        )
        _service().capture_session(session_id=session_id, transcript_path=transcript_path)


# Tools that carry a file_path in tool_input (Edit / Write variants).
_EDIT_TOOL_NAMES = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})


@hooks_app.command("pre-tool-use")
def hooks_pre_tool_use_command() -> None:
    """Inject file-level danger warnings before the agent edits a file.

    Called automatically by the Claude Code PreToolUse hook (matcher:
    ``Edit|Write|MultiEdit|NotebookEdit``).  Reads the hook payload from
    stdin, extracts ``tool_input.file_path``, looks up hotspot / invariant /
    failed-approach memories for that file, and emits a PreToolUse
    ``additionalContext`` JSON payload to stdout when anything notable is
    found.  Non-edit tools and unknown paths produce no output.

    Design invariants:
    - Always exits 0 — never blocks the edit.
    - Any exception is silently swallowed; stdout stays clean on error.
    - Output is tiny: at most a handful of bullet points.
    """
    try:
        payload = _read_hook_payload()
        tool_name = payload.get("tool_name", "")
        if not isinstance(tool_name, str) or tool_name not in _EDIT_TOOL_NAMES:
            return
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return
        raw_file_path = tool_input.get("file_path")
        if not isinstance(raw_file_path, str) or not raw_file_path.strip():
            return
        try:
            from oh_no_my_claudecode.core.repo import discover_repo_root
            from oh_no_my_claudecode.hooks.pre_tool_use import compile_pretool_warning

            # Determine repo root: prefer cwd from payload, fall back to process cwd.
            raw_cwd = payload.get("cwd")
            cwd = Path(raw_cwd) if isinstance(raw_cwd, str) and raw_cwd else Path.cwd()
            try:
                repo_root = discover_repo_root(cwd)
            except Exception:  # noqa: BLE001
                repo_root = cwd

            _, _config, storage = _service()._load_context()  # noqa: SLF001
            warning_md, n = compile_pretool_warning(storage, repo_root, raw_file_path)
        except Exception:  # noqa: BLE001
            return
        if n == 0 or not warning_md:
            return
        sys.stdout.write(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "additionalContext": warning_md,
                    }
                }
            )
            + "\n"
        )
    except Exception:  # noqa: BLE001, S110 - hook commands must never block the session.
        pass


@hooks_app.command("task-intercept")
def hooks_task_intercept_command() -> None:
    """Intercept native ``Task`` agent-spawning and redirect it to ``onmc swarm``.

    Installed by ``onmc wrap`` on the ``PreToolUse`` hook (matcher ``"Task"``).
    Reads the hook payload from stdin and emits either a ``deny`` decision
    (strict) redirecting the model to ``onmc swarm plan``, an
    ``additionalContext`` nudge (soft), or nothing (non-Task tool, or
    self-exemption when ``ONMC_ALLOW_TASK`` is set or an onmc swarm is active).

    Design invariants (identical to every onmc hook):
    - Always exits 0 — a wrapper that bricks Claude Code is unacceptable.
    - Any exception is swallowed; stdout stays clean (empty = allow) on error.
    """
    try:
        from oh_no_my_claudecode.core.repo import discover_repo_root
        from oh_no_my_claudecode.wrap import compile_task_intercept, read_wrap_strict

        payload = _read_hook_payload()
        raw_cwd = payload.get("cwd")
        cwd = Path(raw_cwd) if isinstance(raw_cwd, str) and raw_cwd else Path.cwd()
        try:
            repo_root = discover_repo_root(cwd)
        except Exception:  # noqa: BLE001
            repo_root = cwd
        strict = read_wrap_strict(repo_root)
        output = compile_task_intercept(payload, repo_root, strict=strict)
        if output:
            sys.stdout.write(output + "\n")
    except Exception:  # noqa: BLE001, S110 - hook commands must never block the session.
        pass


@hooks_app.command("prompt-router")
def hooks_prompt_router_command() -> None:
    """Route the user prompt through onmc and inject a "prefer onmc paths" nudge.

    Installed by ``onmc wrap`` on the ``UserPromptSubmit`` hook. Reads the
    prompt from the stdin payload, routes it via the deterministic router +
    dead-end guard, and writes a terse ``additionalContext`` JSON payload.
    Stdout is always pure JSON or empty. Always exits 0; never raises.
    """
    try:
        from oh_no_my_claudecode.core.repo import discover_repo_root
        from oh_no_my_claudecode.wrap import compile_prompt_policy, read_wrap_strict

        payload = _read_hook_payload()
        raw_prompt = payload.get("prompt", "")
        prompt = raw_prompt if isinstance(raw_prompt, str) else ""
        if not prompt.strip():
            return
        raw_cwd = payload.get("cwd")
        cwd = Path(raw_cwd) if isinstance(raw_cwd, str) and raw_cwd else Path.cwd()
        try:
            repo_root = discover_repo_root(cwd)
        except Exception:  # noqa: BLE001
            repo_root = cwd
        strict = read_wrap_strict(repo_root)
        # Storage is optional — the policy degrades to routing-only when memory
        # is unavailable (e.g. onmc not initialised in this repo).
        storage = None
        try:
            _repo_root, _config, storage = _service()._load_context()  # noqa: SLF001
        except Exception:  # noqa: BLE001
            storage = None
        output = compile_prompt_policy(prompt, storage, strict=strict)
        if output:
            sys.stdout.write(output + "\n")
    except Exception:  # noqa: BLE001, S110 - hook commands must never block the session.
        pass


@app.command("consolidate")
def consolidate_command(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Compute the consolidation plan without writing anything."),
    ] = False,
) -> None:
    """Clean and strengthen the memory store (dedup, merge, promote/demote, edge graph)."""
    try:
        _, result = _service().consolidate(dry_run=dry_run)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    label = "[yellow]dry-run — no writes[/yellow]" if dry_run else "[green]done[/green]"
    console.print(f"[bold]Memory consolidation[/bold] {label}")
    for line in result.summary_lines():
        console.print(f"  {line}")


@claude_md_app.callback(invoke_without_command=True)
def claude_md_callback(
    ctx: typer.Context,
    watch: Annotated[
        bool,
        typer.Option("--watch", help="Watch ONMC state and regenerate CLAUDE.md on updates."),
    ] = False,
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Use deterministic generation only."),
    ] = False,
) -> None:
    """Generate and maintain CLAUDE.md from ONMC memory."""
    if watch and ctx.invoked_subcommand is None:
        _service().watch_claude_md(no_llm=no_llm)


@claude_md_app.command("generate")
def claude_md_generate_command(
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Use deterministic generation only."),
    ] = False,
) -> None:
    """Generate CLAUDE.md from stored memory."""
    markdown = _service().generate_claude_md(no_llm=no_llm, write=True)
    console.print(markdown)


@claude_md_app.command("update")
def claude_md_update_command(
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Use deterministic generation only."),
    ] = False,
) -> None:
    """Update stale CLAUDE.md sections."""
    markdown, stale_sections = _service().update_claude_md(no_llm=no_llm, write=True)
    console.print(markdown)
    if stale_sections:
        console.print(f"[green]Updated sections:[/green] {', '.join(stale_sections)}")


@claude_md_app.command("preview")
def claude_md_preview_command(
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Use deterministic generation only."),
    ] = False,
) -> None:
    """Preview CLAUDE.md without writing it."""
    markdown = _service().generate_claude_md(no_llm=no_llm, write=False)
    console.print(markdown)


@app.command("mine")
def mine_command(
    github: Annotated[
        bool,
        typer.Option("--github", help="Mine GitHub PRs and reviews from the repo remote."),
    ] = False,
    session: Annotated[
        str | None,
        typer.Option("--session", help="Mine a specific session id."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show findings without writing them."),
    ] = False,
    since: Annotated[
        str | None,
        typer.Option("--since", help="Only process transcripts newer than this value."),
    ] = None,
    no_llm: Annotated[
        bool,
        typer.Option(
            "--no-llm",
            help="Skip LLM extraction and only inspect transcript availability.",
        ),
    ] = False,
) -> None:
    """Mine Claude Code session transcripts into ONMC memory."""
    if github and session is not None:
        raise typer.Exit(code=_fatal("Use either --github or --session, not both."))
    if github and since is not None:
        raise typer.Exit(code=_fatal("Use either --github or --since, not both."))
    if not no_llm and not github:
        console.print(
            "Note: onmc mine sends session transcript excerpts to your configured LLM provider.\n"
            "Only assistant turns are sent. User turns are excluded.\n"
            "Disable with: onmc mine --no-llm (heuristic extraction only)"
        )
    result = _service().mine(
        dry_run=dry_run,
        session_id=session,
        since=since,
        no_llm=no_llm,
        github=github,
    )
    render_mine_result(result, dry_run=dry_run)
    if dry_run:
        return
    message = result.get("message")
    if isinstance(message, str) and message:
        return
    extracted_count = sum(
        len(items)
        for items in (
            result.get("attempts"),
            result.get("memories"),
            result.get("artifacts"),
        )
        if isinstance(items, list)
    )
    if extracted_count:
        source_label = result.get("memory_source")
        display_source = (
            str(source_label)
            if isinstance(source_label, str) and source_label
            else SourceType.TRANSCRIPT.value
        )
        source_phrase = (
            "from GitHub PRs"
            if display_source == SourceType.GITHUB_PR.value
            else "from this session"
        )
        console.print(
            f"  Extracted {extracted_count} records {source_phrase}.\n"
            f"  Review them? [onmc memory list --source {display_source}] or press Enter to skip",
            markup=False,
        )


@app.command("capture")
def capture_command(
    session: Annotated[
        str | None,
        typer.Option("--session", help="Session ID to capture (default: most recent)."),
    ] = None,
    transcript: Annotated[
        Path | None,
        typer.Option("--transcript", help="Explicit path to a .jsonl transcript file."),
    ] = None,
) -> None:
    """Heuristically capture durable memory from a session transcript.

    Extracts fixes, decisions, invariants, and notes from the session
    transcript without any LLM call.  Deduplicated entries are stored
    with source_type=session so they can be listed or pruned independently.

    Useful for on-demand re-capture or testing the auto-capture path that
    runs automatically on SessionEnd (set ONMC_AUTOCAPTURE=0 to disable).
    """
    try:
        count = _service().capture_session(session_id=session, transcript_path=transcript)
        if count:
            console.print(f"[green]Captured {count} new memory entries from session.[/green]")
        else:
            console.print("No new memory entries captured (nothing matched or already stored).")
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc


@app.command("doctor")
def doctor_command() -> None:
    """Run a health check over repo state, memory, provider setup, and integrations."""
    ok, report = _service().doctor()
    render_doctor_report(ok, report)
    raise typer.Exit(code=0 if ok else 1)


@app.command("audit")
def audit_command(
    path: Annotated[
        Path | None,
        typer.Argument(
            help=(
                "Repo root to scan.  Defaults to the current directory.  "
                "The directory does not need to be an initialised ONMC repo — "
                "audit is purely static."
            ),
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the full AuditReport as JSON to stdout."),
    ] = False,
    fail_on: Annotated[
        str,
        typer.Option(
            "--fail-on",
            help=(
                "Exit non-zero when at least one finding at this severity or higher "
                "exists.  One of: critical, high, medium, low, info.  Default: high."
            ),
        ),
    ] = "high",
    use_semgrep: Annotated[
        bool,
        typer.Option(
            "--semgrep/--no-semgrep",
            help=(
                "Also run semgrep static analysis and fold its findings into the "
                "report.  Requires the 'semgrep' binary on PATH.  When the binary "
                "is absent this flag is silently ignored — no pip dependency is "
                "added.  Default: off."
            ),
        ),
    ] = False,
) -> None:
    """Scan agent configuration for security risks and emit a scored report.

    Scans CLAUDE.md, AGENTS.md, .claude/settings.json, .claude/settings.local.json,
    .mcp.json, and hooks/ for secrets, over-broad permissions, hook injection
    vectors, and prompt-injection surfaces.

    Exit codes:

    - 0 — no findings at or above ``--fail-on`` threshold
    - 1 — one or more findings at or above the threshold  (CI gate)
    - 2 — usage error

    Use ``--fail-on critical`` for a lenient CI gate, ``--fail-on medium`` for
    a stricter one.
    """
    from oh_no_my_claudecode.audit.scanner import AuditSeverity

    valid_severities: list[AuditSeverity] = ["critical", "high", "medium", "low", "info"]
    if fail_on not in valid_severities:
        msg = f"--fail-on must be one of: {', '.join(valid_severities)}"
        raise typer.Exit(code=_fatal(msg))

    repo_root: Path = path.resolve() if path is not None else Path.cwd()

    report = _service().audit(repo_root=repo_root, semgrep=use_semgrep)

    if as_json:
        import dataclasses

        def _to_dict(obj: object) -> object:
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return {
                    k: _to_dict(v)
                    for k, v in dataclasses.asdict(obj).items()
                }
            if isinstance(obj, set):
                return sorted(obj)
            return obj

        sys.stdout.write(json.dumps(_to_dict(report), indent=2, default=str) + "\n")
    else:
        render_audit_report(report)

    threshold: AuditSeverity = fail_on
    if report.findings_at_or_above(threshold):
        raise typer.Exit(code=1)


@app.command("preflight")
def preflight_command(
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--only",
            help=(
                "Run only these steps (repeatable).  One or more of: "
                "ruff, mypy, cliref, pytest.  Default: run all, in CI order."
            ),
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the PreflightReport as JSON to stdout."),
    ] = False,
    provision: Annotated[
        bool,
        typer.Option(
            "--provision",
            help=(
                "Run each tool via `uv run --with <tool>` so a fresh worktree "
                "(no dev deps installed) resolves ruff/mypy/pytest on demand, "
                "and pin typer<1.0 for the cli-reference step to match CI."
            ),
        ),
    ] = False,
) -> None:
    """Run the exact CI quality gate locally, in the same order CI runs it.

    Mirrors ``.github/workflows/ci.yml`` step-for-step:

    1. ``ruff check .``
    2. ``mypy --strict src/oh_no_my_claudecode``
    3. ``generate-cli-reference.py --check``
    4. ``pytest tests/``

    Use ``--only`` to run a subset, e.g. ``onmc preflight --only ruff --only mypy``.

    Exit codes:

    - 0 — every step that ran passed (matches the CI gate)
    - 1 — one or more steps failed, or no valid step was selected
    - 2 — usage error
    """
    from oh_no_my_claudecode.preflight.runner import STEP_IDS

    steps: list[str] | None = None
    if only:
        invalid = [s for s in only if s not in STEP_IDS]
        if invalid:
            msg = (
                f"--only must be one of: {', '.join(STEP_IDS)} "
                f"(got: {', '.join(invalid)})"
            )
            raise typer.Exit(code=_fatal(msg))
        steps = only

    report = _service().preflight(steps=steps, provision=provision)

    if as_json:
        import dataclasses

        payload = {
            "ok": report.ok,
            "steps": [dataclasses.asdict(step) for step in report.steps],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        render_preflight_report(report)

    if not report.ok:
        raise typer.Exit(code=1)


@app.command("verify-diff")
def verify_diff_command(
    base: Annotated[
        str,
        typer.Option("--base", help="Git ref to diff against (default: main)."),
    ] = "main",
    expect_symbol: Annotated[
        list[str] | None,
        typer.Option(
            "--expect-symbol",
            help="Symbol that must appear in added lines.  Repeatable.",
        ),
    ] = None,
    expect_file: Annotated[
        list[str] | None,
        typer.Option(
            "--expect-file",
            help="Repo-relative path that must receive added lines.  Repeatable.",
        ),
    ] = None,
    structural: Annotated[
        bool,
        typer.Option(
            "--structural",
            help=(
                "Use difftastic (the 'difft' binary) for a structural/AST diff that"
                " ignores formatting noise.  No-op when 'difft' is not on PATH"
                " (falls back to line-diff)."
            ),
        ),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the full VerifyReport as JSON to stdout."),
    ] = False,
) -> None:
    """Adversarially verify the working diff against a base ref.

    Passes ONLY when the change is real (non-empty), introduces every expected
    symbol/file, and is lawful (no banned or secret patterns in added lines).
    Designed to close the empty-diff false-converge: a passing test suite over
    an unchanged tree must NOT count as success.  With ``--structural`` and the
    ``difft`` binary installed, it also rejects reformat-only diffs.

    Exit codes:

    - 0 — every check passed
    - 1 — one or more checks failed
    """
    report = _service().verify_diff(
        base=base,
        expect_symbols=tuple(expect_symbol or ()),
        expect_files=tuple(expect_file or ()),
        structural=structural,
    )

    if as_json:
        import dataclasses

        payload = {
            "ok": report.ok,
            "findings": [dataclasses.asdict(f) for f in report.findings],
        }
        sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
    else:
        render_verify_report(report)

    if not report.ok:
        raise typer.Exit(code=1)


@wiki_app.callback(invoke_without_command=True)
def wiki_callback(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            help=(
                "Directory to write wiki pages into."
                " Defaults to .onmc/wiki/ (gitignored)."
                " Pass e.g. docs/wiki to produce a committable copy."
            ),
        ),
    ] = None,
    wiki_format: Annotated[
        WikiFormat,
        typer.Option("--format", help="Output format: markdown wiki or Obsidian vault."),
    ] = WikiFormat.MARKDOWN,
) -> None:
    """Generate a markdown wiki or Obsidian knowledge-graph vault.

    When invoked without a subcommand, generates the wiki immediately.
    Use ``onmc wiki logseq`` for a Logseq-compatible knowledge graph export.
    """
    if ctx.invoked_subcommand is not None:
        return
    try:
        repo_root, written = _service().generate_wiki(output_dir=output, format=wiki_format)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if not written:
        console.print("[yellow]No wiki pages were generated (store may be empty).[/yellow]")
        raise typer.Exit(code=0)

    index_name = "Home.md" if wiki_format is WikiFormat.OBSIDIAN else "index.md"
    index_path = next((p for p in written if p.name == index_name), written[0])
    label = "Obsidian vault" if wiki_format is WikiFormat.OBSIDIAN else "Wiki"
    console.print(f"[green]{label} generated:[/green] {len(written)} page(s)")
    for page in sorted(written):
        try:
            display = page.relative_to(repo_root)
        except ValueError:
            display = page
        console.print(f"  {display}")
    console.print(f"\n[bold]Index:[/bold] {index_path}")


@wiki_app.command("logseq")
def wiki_logseq_command(
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help=(
                "Directory to write Logseq pages into."
                " Defaults to .onmc/logseq/ (gitignored)."
            ),
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print a JSON envelope listing written paths."),
    ] = False,
) -> None:
    """Export memory as a Logseq-compatible knowledge graph.

    Writes one markdown page per memory into a ``pages/`` subdirectory, using
    Logseq's ``key:: value`` page properties and ``[[wikilinks]]`` for memory
    edges.  No new dependency — pure stdlib string generation.

    The output directory defaults to ``.onmc/logseq/`` and is safe to open
    directly in the Logseq desktop app as a graph folder.
    """
    service = OnmcService(Path.cwd())
    try:
        repo_root, _config, storage = service._load_context()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    out_dir = out if out is not None else (repo_root / ".onmc" / "logseq")
    out_dir.mkdir(parents=True, exist_ok=True)

    pages = build_logseq_vault(storage)

    written: list[Path] = []
    for rel_path, content in pages.items():
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(dest)

    if as_json:
        import json as _json

        typer.echo(
            _json.dumps(
                {
                    "kind": "logseq",
                    "out_dir": str(out_dir),
                    "pages": sorted(str(p.relative_to(out_dir)) for p in written),
                    "count": len(written),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if not written:
        console.print("[yellow]No Logseq pages generated (store may be empty).[/yellow]")
        raise typer.Exit(code=0)

    console.print(f"[green]Logseq graph generated:[/green] {len(written)} page(s)")
    for page in sorted(written):
        try:
            display = page.relative_to(repo_root)
        except ValueError:
            display = page
        console.print(f"  {display}")
    console.print(f"\n[bold]Open in Logseq:[/bold] {out_dir}")


@wiki_app.command("foam")
def wiki_foam_command(
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help=(
                "Directory to write Foam notes into."
                " Defaults to .onmc/foam/ (gitignored)."
            ),
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print a JSON envelope listing written paths."),
    ] = False,
) -> None:
    """Export memory as a Foam-compatible markdown knowledge graph.

    Writes one markdown note per memory into a ``notes/`` subdirectory and an
    ``index.md`` entry point, using YAML frontmatter and ``[[wikilinks]]`` for
    memory edges.  No new dependency — pure stdlib string generation.

    Foam is a VS Code extension that reads a flat directory of markdown notes
    and renders an interactive knowledge graph.  The output directory defaults
    to ``.onmc/foam/`` and can be opened directly in VS Code with the Foam
    extension installed.
    """
    service = OnmcService(Path.cwd())
    try:
        repo_root, _config, storage = service._load_context()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    out_dir = out if out is not None else (repo_root / ".onmc" / "foam")
    out_dir.mkdir(parents=True, exist_ok=True)

    pages = build_foam_vault(storage)

    written: list[Path] = []
    for rel_path, content in pages.items():
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        written.append(dest)

    if as_json:
        import json as _json

        typer.echo(
            _json.dumps(
                {
                    "kind": "foam",
                    "out_dir": str(out_dir),
                    "pages": sorted(str(p.relative_to(out_dir)) for p in written),
                    "count": len(written),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if not written:
        console.print("[yellow]No Foam notes generated (store may be empty).[/yellow]")
        raise typer.Exit(code=0)

    console.print(f"[green]Foam vault generated:[/green] {len(written)} note(s)")
    for page in sorted(written):
        try:
            display = page.relative_to(repo_root)
        except ValueError:
            display = page
        console.print(f"  {display}")
    console.print(f"\n[bold]Open in VS Code (Foam):[/bold] {out_dir}")


@memory_app.command("list")
def memory_list_command(
    kind: Annotated[
        MemoryKind | None,
        typer.Option("--kind", help="Filter by memory kind."),
    ] = None,
    source_type: Annotated[
        SourceType | None,
        typer.Option("--source", help="Filter by memory source type."),
    ] = None,
    artifact_type: Annotated[
        MemoryArtifactType | None,
        typer.Option("--type", help="Filter task-derived memory artifacts by type."),
    ] = None,
    min_confidence: Annotated[
        float | None,
        typer.Option("--min-confidence", min=0.0, max=1.0, help="Filter by minimum confidence."),
    ] = None,
    confirmed: Annotated[
        bool,
        typer.Option("--confirmed", help="Show only explicitly confirmed memories."),
    ] = False,
    wide: Annotated[
        bool,
        typer.Option("--wide/--compact", help="Show a wider, more readable memory table."),
    ] = True,
) -> None:
    """List stored memory entries."""
    if artifact_type is not None and (kind is not None or source_type is not None):
        raise typer.Exit(
            code=_fatal("Use --type alone, or filter stored memory with --kind/--source.")
        )
    try:
        memories = _service().list_memories(
            kind=kind,
            source_type=source_type,
            min_confidence=min_confidence,
            confirmed_only=confirmed,
        )
        artifacts = _service().list_memory_artifacts(artifact_type=artifact_type)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if kind is not None or source_type is not None:
        artifacts = []
    if artifact_type is not None:
        memories = []
    render_memory_list(memories, artifacts=artifacts, wide=wide)


@memory_app.command("add")
def memory_add_command(
    task_id: str,
    artifact_type: Annotated[
        MemoryArtifactType,
        typer.Option("--type", help="Task-derived memory artifact type."),
    ],
    title: Annotated[str, typer.Option("--title", help="Short artifact title.")],
    summary: Annotated[
        str,
        typer.Option("--summary", help="What worked, failed, or conflicted."),
    ],
    why_it_matters: Annotated[
        str,
        typer.Option(
            "--why-it-matters",
            help="Why a future agent or engineer should keep this in mind.",
        ),
    ] = "Preserve this task outcome so future work starts from a known result.",
    apply_when: Annotated[
        str | None,
        typer.Option("--apply-when", help="When this guidance should be used."),
    ] = None,
    avoid_when: Annotated[
        str | None,
        typer.Option("--avoid-when", help="When this guidance should not be applied."),
    ] = None,
    evidence: Annotated[
        str,
        typer.Option("--evidence", help="Evidence from the task or attempts."),
    ] = "Recorded from task-scoped work.",
    related_files: Annotated[
        list[str] | None,
        typer.Option("--file", help="Repeat to record related file paths."),
    ] = None,
    related_modules: Annotated[
        list[str] | None,
        typer.Option("--module", help="Repeat to record related module names."),
    ] = None,
    confidence: Annotated[
        float,
        typer.Option("--confidence", min=0.0, max=1.0, help="Confidence from 0.0 to 1.0."),
    ] = 0.7,
) -> None:
    """Add a task-derived memory artifact."""
    try:
        artifact = _service().add_memory_artifact(
            task_id,
            artifact_type=artifact_type,
            title=title,
            summary=summary,
            why_it_matters=why_it_matters,
            apply_when=apply_when,
            avoid_when=avoid_when,
            evidence=evidence,
            related_files=related_files or [],
            related_modules=related_modules or [],
            confidence=confidence,
        )
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_memory_artifact_added(artifact)


@memory_app.command("show")
def memory_show_command(memory_id: str) -> None:
    """Show a single memory entry with provenance."""
    try:
        artifact = _service().get_memory_artifact(memory_id)
        memory = _service().get_memory(memory_id) if artifact is None else None
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if artifact is not None:
        render_memory_detail(artifact)
        return
    if memory is None:
        raise typer.Exit(code=_fatal(f"Memory not found: {memory_id}"))
    render_memory_detail(memory)


@memory_app.command("confirm")
def memory_confirm_command(memory_id: str) -> None:
    """Mark a memory record as verified useful."""
    try:
        memory = _service().confirm_memory(memory_id)
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_memory_detail(memory)


@memory_app.command("reject")
def memory_reject_command(memory_id: str) -> None:
    """Mark a memory record as wrong or stale."""
    try:
        memory = _service().reject_memory(memory_id)
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_memory_detail(memory)


@memory_app.command("edit")
def memory_edit_command(memory_id: str) -> None:
    """Edit a memory summary and reset its feedback score."""
    try:
        current = _service().get_memory(memory_id)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if current is None:
        raise typer.Exit(code=_fatal(f"Memory not found: {memory_id}"))
    edited = _service().edit_memory_in_editor(memory_id)
    if edited is None:
        edited = typer.prompt("New summary", default=current.summary)
    if not edited.strip():
        raise typer.Exit(code=_fatal("Edited summary cannot be empty."))
    if not typer.confirm("Save this?", default=True):
        console.print("[yellow]Memory edit cancelled.[/yellow]")
        return
    updated = _service().edit_memory(memory_id, edited.strip())
    render_memory_detail(updated)


@memory_app.command("verify")
def memory_verify_command() -> None:
    """Re-check anchored memories against the filesystem and record staleness."""
    from rich.table import Table

    from oh_no_my_claudecode.memory.staleness import classify_staleness
    from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now

    try:
        repo_root, _config, storage = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    memories = storage.list_memories()
    counts: dict[str, int] = {"fresh": 0, "stale": 0, "orphaned": 0, "unanchored": 0}
    verified_at = isoformat_utc(utc_now())

    for memory in memories:
        label = classify_staleness(repo_root, memory)
        storage.set_memory_staleness(memory.id, label, verified_at)
        counts[label] += 1

    table = Table(title="Memory Staleness Report")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    color_map = {"fresh": "green", "stale": "yellow", "orphaned": "red", "unanchored": "dim"}
    for status, count in counts.items():
        color = color_map[status]
        table.add_row(f"[{color}]{status}[/{color}]", str(count))
    console.print(table)
    console.print(f"[green]Verified {len(memories)} memories.[/green]")


@memory_app.command("prune")
def memory_prune_command(
    orphaned: Annotated[
        bool,
        typer.Option("--orphaned", help="Remove memories whose anchor file no longer exists."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be deleted without deleting."),
    ] = False,
) -> None:
    """Remove orphaned generated memories (manual memories are always preserved)."""
    if not orphaned:
        raise typer.Exit(code=_fatal("Specify --orphaned to select which memories to prune."))
    try:
        _repo_root, _config, storage = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    candidates = [
        m
        for m in storage.list_memories()
        if m.staleness == "orphaned"
        and m.source_type not in (SourceType.MANUAL, SourceType.MANUAL_SEED)
    ]
    if not candidates:
        console.print("[green]No orphaned generated memories found.[/green]")
        return

    for memory in candidates:
        console.print(f"  [red]orphaned[/red] {memory.id[:12]}  {memory.title[:60]}")

    if dry_run:
        console.print(
            f"[yellow]Dry run: would delete {len(candidates)} orphaned memories.[/yellow]"
        )
        return

    deleted = storage.delete_orphaned_generated_memories()
    console.print(f"[red]Deleted {deleted} orphaned generated memories.[/red]")


@memory_app.command("embed")
def memory_embed_command(
    force: Annotated[
        bool,
        typer.Option("--force", help="Recompute vectors even when a valid cache entry exists."),
    ] = False,
) -> None:
    """Pre-build semantic embedding vectors for all memories.

    Vectors are cached in the local SQLite database (migration v6).  Subsequent
    searches use the cache, so this command is optional — vectors are also built
    lazily on first search when embeddings are enabled.  Run it to warm the
    cache or after switching to a different real-model embedder.
    """
    from oh_no_my_claudecode.embeddings.rerank import build_vectors_for_all_memories

    try:
        _repo_root, _config, storage = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    written = build_vectors_for_all_memories(storage, force=force)
    console.print(f"[green]Embedded {written} memor{'y' if written == 1 else 'ies'}.[/green]")


@task_app.command("start")
def task_start_command(
    title: Annotated[str, typer.Option("--title", help="Short task title.")],
    description: Annotated[str, typer.Option("--description", help="Task description.")],
    labels: Annotated[
        list[str] | None,
        typer.Option("--label", help="Repeat to attach one or more labels."),
    ] = None,
) -> None:
    """Create and activate a new task for the current repository."""
    try:
        task = _service().start_task(
            title=title,
            description=description,
            labels=labels or [],
        )
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_task_started(task)


@task_app.command("list")
def task_list_command() -> None:
    """List tasks for the current repository."""
    try:
        tasks = _service().list_tasks()
        attempt_counts = _service().attempt_counts_by_task()
        memory_artifact_counts = _service().memory_artifact_counts_by_task()
        task_output_counts = _service().task_output_counts_by_task()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_task_list(
        tasks,
        attempt_counts=attempt_counts,
        memory_artifact_counts=memory_artifact_counts,
        task_output_counts=task_output_counts,
    )


@task_app.command("show")
def task_show_command(task_id: str) -> None:
    """Show a stored task with lifecycle details."""
    try:
        task = _service().get_task(task_id)
        attempts = _service().list_attempts_for_task(task_id)
        artifacts = _service().list_memory_artifacts_for_task(task_id)
        outputs = _service().list_task_outputs_for_task(task_id)
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if task is None:
        raise typer.Exit(code=_fatal(f"Task not found: {task_id}"))
    render_task_detail(task, attempts=attempts, artifacts=artifacts, outputs=outputs)


@task_app.command("end")
def task_end_command(
    task_id: str,
    summary: Annotated[str, typer.Option("--summary", help="Final task summary.")],
    status: Annotated[
        TaskStatus,
        typer.Option("--status", help="Terminal task status."),
    ] = TaskStatus.SOLVED,
) -> None:
    """End a task with a terminal status and final summary."""
    try:
        task = _service().end_task(task_id, status=status, summary=summary)
    except (FileNotFoundError, LookupError, TaskLifecycleError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_task_updated(task, action="Task Ended")


@task_app.command("status")
def task_status_command(
    task_id: str,
    status: Annotated[
        TaskStatus,
        typer.Option("--status", help="New task status."),
    ],
) -> None:
    """Update task status."""
    try:
        task = _service().update_task_status(task_id, status)
    except (FileNotFoundError, LookupError, TaskLifecycleError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_task_updated(task, action="Task Updated")


@attempt_app.command("add")
def attempt_add_command(
    task_id: str,
    summary: Annotated[str, typer.Option("--summary", help="Short attempt summary.")],
    kind: Annotated[
        AttemptKind,
        typer.Option("--kind", help="Attempt kind."),
    ],
    status: Annotated[
        AttemptStatus,
        typer.Option("--status", help="Attempt status."),
    ],
    reasoning_summary: Annotated[
        str | None,
        typer.Option("--reasoning-summary", help="Why this attempt seemed worth trying."),
    ] = None,
    evidence_for: Annotated[
        str | None,
        typer.Option("--evidence-for", help="Signals supporting the attempt."),
    ] = None,
    evidence_against: Annotated[
        str | None,
        typer.Option("--evidence-against", help="Signals against the attempt."),
    ] = None,
    files_touched: Annotated[
        list[str] | None,
        typer.Option("--file", help="Repeat to record touched file paths."),
    ] = None,
) -> None:
    """Add an attempt record for a task."""
    try:
        attempt = _service().add_attempt(
            task_id,
            summary=summary,
            kind=kind,
            status=status,
            reasoning_summary=reasoning_summary,
            evidence_for=evidence_for,
            evidence_against=evidence_against,
            files_touched=files_touched or [],
        )
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_attempt_added(attempt)


@attempt_app.command("list")
def attempt_list_command(task_id: str) -> None:
    """List attempts attached to a task."""
    try:
        attempts = _service().list_attempts_for_task(task_id)
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_attempt_list(task_id, attempts)


@attempt_app.command("show")
def attempt_show_command(attempt_id: str) -> None:
    """Show one attempt record."""
    try:
        attempt = _service().get_attempt(attempt_id)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if attempt is None:
        raise typer.Exit(code=_fatal(f"Attempt not found: {attempt_id}"))
    render_attempt_detail(attempt)


@attempt_app.command("update")
def attempt_update_command(
    attempt_id: str,
    status: Annotated[
        AttemptStatus,
        typer.Option("--status", help="Updated attempt status."),
    ],
    summary: Annotated[
        str | None,
        typer.Option("--summary", help="Replace the attempt summary."),
    ] = None,
    reasoning_summary: Annotated[
        str | None,
        typer.Option("--reasoning-summary", help="Update reasoning notes."),
    ] = None,
    evidence_for: Annotated[
        str | None,
        typer.Option("--evidence-for", help="Update supporting evidence."),
    ] = None,
    evidence_against: Annotated[
        str | None,
        typer.Option("--evidence-against", help="Update counter-evidence."),
    ] = None,
    files_touched: Annotated[
        list[str] | None,
        typer.Option("--file", help="Replace touched file paths."),
    ] = None,
) -> None:
    """Update an existing attempt."""
    try:
        attempt = _service().update_attempt(
            attempt_id,
            status=status,
            summary=summary,
            reasoning_summary=reasoning_summary,
            evidence_for=evidence_for,
            evidence_against=evidence_against,
            files_touched=files_touched,
        )
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_attempt_updated(attempt)


@playbook_app.command("generate")
def playbook_generate_command(
    no_llm: Annotated[
        bool,
        typer.Option("--no-llm", help="Skip the optional LLM polish pass; deterministic only."),
    ] = False,
) -> None:
    """Synthesize playbooks from stored memory, persist, and write artifacts."""
    try:
        _, playbooks, artifact_paths = _service().generate_playbooks(no_llm=no_llm)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    if not playbooks:
        console.print(
            "[yellow]No playbooks generated. Ingest more memory first "
            "(`onmc ingest` / `onmc memory confirm`).[/yellow]"
        )
        return
    render_playbook_generate_summary(playbooks, artifact_paths)


@playbook_app.command("list")
def playbook_list_command() -> None:
    """List all persisted playbooks."""
    try:
        playbooks = _service().list_playbooks()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    render_playbook_list(playbooks)


@playbook_app.command("show")
def playbook_show_command(
    playbook_id: Annotated[str, typer.Argument(help="Playbook ID (or prefix) to show.")],
) -> None:
    """Show a single playbook with steps and provenance."""
    try:
        playbooks = _service().list_playbooks()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    # Support prefix match for convenience.
    matches = [pb for pb in playbooks if pb.id.startswith(playbook_id)]
    if not matches:
        raise typer.Exit(code=_fatal(f"Playbook not found: {playbook_id}"))
    if len(matches) > 1:
        raise typer.Exit(
            code=_fatal(
                f"Ambiguous prefix '{playbook_id}' matches {len(matches)} playbooks. "
                "Provide a longer prefix."
            )
        )
    render_playbook_detail(matches[0])


# ---------------------------------------------------------------------------
# Skill commands
# ---------------------------------------------------------------------------


@skill_app.command("promote")
def skill_promote_command(
    playbook_id: Annotated[
        str | None,
        typer.Argument(help="Playbook ID (or prefix) to promote to a skill."),
    ] = None,
    auto: Annotated[
        bool,
        typer.Option("--auto", help="Auto-detect recurring patterns and promote all."),
    ] = False,
    name: Annotated[
        str | None,
        typer.Option("--name", help="Override the skill name (only used with a playbook-id)."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the new skill(s) as JSON."),
    ] = False,
) -> None:
    """Promote a playbook or recurring patterns to skill(s).

    Provide a playbook ID to lift a single playbook into a named, reusable
    skill.  Use --auto to scan all stored memories for recurring fail→fix
    patterns and high-signal tag clusters, promoting each to a skill.

    \b
    Examples
    --------
    onmc skill promote pb_abc123
    onmc skill promote pb_abc123 --name "Cache Invalidation"
    onmc skill promote --auto
    onmc skill promote --auto --json
    """
    if not auto and playbook_id is None:
        raise typer.Exit(code=_fatal("Provide a playbook-id or pass --auto."))
    try:
        skills = _service().skill_promote(playbook_id, auto=auto, name=name)
    except (FileNotFoundError, LookupError, ValueError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    from oh_no_my_claudecode.models.skill import Skill as _Skill

    if json_output:
        typer.echo(
            json.dumps(
                [
                    sk.model_dump(mode="json") if isinstance(sk, _Skill) else {}
                    for sk in skills
                ],
                indent=2,
            )
        )
        return
    render_skill_promoted([sk for sk in skills if isinstance(sk, _Skill)])


@skill_app.command("list")
def skill_list_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit skills as JSON array."),
    ] = False,
) -> None:
    """List all persisted skills."""
    try:
        skills = _service().skill_list()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    from oh_no_my_claudecode.models.skill import Skill as _Skill

    if json_output:
        typer.echo(
            json.dumps(
                [sk.model_dump(mode="json") if isinstance(sk, _Skill) else {} for sk in skills],
                indent=2,
            )
        )
        return
    render_skill_list([sk for sk in skills if isinstance(sk, _Skill)])


@skill_app.command("show")
def skill_show_command(
    skill_id: Annotated[str, typer.Argument(help="Skill ID (or prefix) to show.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the skill as JSON."),
    ] = False,
) -> None:
    """Show a single skill with body, trigger, and metadata."""
    try:
        skill = _service().skill_show(skill_id)
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    from oh_no_my_claudecode.models.skill import Skill as _Skill

    if json_output and isinstance(skill, _Skill):
        typer.echo(json.dumps(skill.model_dump(mode="json"), indent=2))
        return
    if isinstance(skill, _Skill):
        render_skill_detail(skill)


@skill_app.command("feedback")
def skill_feedback_command(
    skill_id: Annotated[str, typer.Argument(help="Skill ID to apply feedback to.")],
    direction: Annotated[
        str,
        typer.Argument(help="Trust signal: 'up' (helped) or 'down' (did not help)."),
    ],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the updated skill as JSON."),
    ] = False,
) -> None:
    """Apply a trust signal to a stored skill.

    'up' marks the skill as having helped and nudges its confidence upward.
    'down' records the usage without incrementing success_count and nudges
    confidence downward (clamped at a floor so the skill remains visible).

    \b
    Examples
    --------
    onmc skill feedback sk_abc123 up
    onmc skill feedback sk_abc123 down
    onmc skill feedback sk_abc123 up --json
    """
    if direction not in ("up", "down"):
        raise typer.Exit(
            code=_fatal(
                f"direction must be 'up' or 'down', got {direction!r}. "
                "Usage: onmc skill feedback <skill-id> <up|down>"
            )
        )
    try:
        updated = _service().skill_feedback(skill_id, direction)
    except (FileNotFoundError, LookupError, ValueError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    from oh_no_my_claudecode.models.skill import Skill as _Skill

    if json_output and isinstance(updated, _Skill):
        typer.echo(
            json.dumps(
                {
                    "id": updated.id,
                    "direction": direction,
                    "use_count": updated.use_count,
                    "success_count": updated.success_count,
                    "confidence": round(updated.confidence, 4),
                }
            )
        )
        return
    if isinstance(updated, _Skill):
        arrow = "[green]up[/green]" if direction == "up" else "[yellow]down[/yellow]"
        console.print(
            f"[bold]Feedback:[/bold] {arrow}  "
            f"skill=[dim]{updated.id[:16]}[/dim]  "
            f"uses={updated.use_count}  "
            f"conf={updated.confidence:.4f}"
        )


@skill_app.command("prune")
def skill_prune_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit pruned skills as JSON array."),
    ] = False,
) -> None:
    """Disable auto_inject on low-success, long-unused skills.

    A skill is pruned when it has been used at least 3 times with a success
    rate below 30%, or has not been used in the last 60 days.  Pruning sets
    auto_inject=False so the injection layer skips it; the skill remains in
    storage and can be re-examined or deleted manually.
    """
    try:
        pruned = _service().skill_prune()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    from oh_no_my_claudecode.models.skill import Skill as _Skill

    if json_output:
        typer.echo(
            json.dumps(
                [sk.model_dump(mode="json") if isinstance(sk, _Skill) else {} for sk in pruned],
                indent=2,
            )
        )
        return
    render_skill_pruned([sk for sk in pruned if isinstance(sk, _Skill)])


@skill_app.command("export")
def skill_export_command(
    out_dir: Annotated[
        Path | None,
        typer.Option("--out", help="Output directory (default: .claude/skills/)."),
    ] = None,
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            help="'project' (default) → .claude/skills/; 'personal' → ~/.claude/skills/.",
        ),
    ] = "project",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit list of written paths as JSON."),
    ] = False,
) -> None:
    """Export skills as Agent Skills SKILL.md files (agentskills.io standard).

    Writes one <slug>/SKILL.md per skill.  The output is compatible with
    Claude Code, Cursor, Codex, Gemini, Copilot, OpenCode, Goose, Letta,
    Hermes, and 16+ other tools that support the agentskills.io open standard.

    \b
    Examples
    --------
    onmc skill export
    onmc skill export --out .claude/skills
    onmc skill export --scope personal
    onmc skill export --json
    """
    if scope not in ("project", "personal"):
        raise typer.Exit(
            code=_fatal(f"--scope must be 'project' or 'personal', got {scope!r}.")
        )
    try:
        written = _service().skill_export(out_dir=out_dir, scope=scope)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        typer.echo(json.dumps([str(p) for p in written]))
        return

    if not written:
        console.print(
            "[yellow]No skills yet — promote some with [bold]onmc skill promote[/bold].[/yellow]"
        )
        return

    dest_dir = written[0].parent.parent if written else (out_dir or Path(".claude/skills"))
    console.print(
        f"[green]Exported {len(written)} skill(s)[/green] to [bold]{dest_dir}[/bold]"
    )
    for path in written:
        console.print(f"  [dim]{path}[/dim]")
    console.print(
        "\n[dim]Tip: these SKILL.md files work in Claude Code, Cursor, Codex, Gemini, "
        "Copilot, OpenCode, Goose, Letta, Hermes, and more.[/dim]"
    )


# ---------------------------------------------------------------------------
# User-scope (cross-repo) memory commands
# ---------------------------------------------------------------------------


@user_app.command("add")
def user_add_command(
    title: Annotated[str, typer.Option("--title", help="Short preference title.")],
    summary: Annotated[
        str,
        typer.Option("--summary", help="Full description of the preference or working-style fact."),
    ],
) -> None:
    """Add a cross-repo user preference (stored in ~/.onmc, not git-tracked).

    User preferences travel with you across all repositories and appear at the
    top of every session boot digest so your coding style is always applied.
    Examples: "always use pytest", "run ruff before committing".
    """
    memory = _service().add_user_memory(title=title, summary=summary)
    render_user_memory_added(memory)


@user_app.command("list")
def user_list_command() -> None:
    """List all cross-repo user preferences."""
    memories = _service().list_user_memories()
    render_user_memory_list(memories)


@user_app.command("show")
def user_show_command(memory_id: str) -> None:
    """Show a single user preference by ID."""
    memory = _service().get_user_memory(memory_id)
    if memory is None:
        raise typer.Exit(code=_fatal(f"User preference not found: {memory_id}"))
    render_user_memory_detail(memory)


@user_app.command("remove")
def user_remove_command(memory_id: str) -> None:
    """Remove a user preference by ID."""
    found = _service().remove_user_memory(memory_id)
    render_user_memory_removed(memory_id, found=found)


# ---------------------------------------------------------------------------
# Profile commands — derived behavioral profile from user-scope memories
# ---------------------------------------------------------------------------


@profile_app.command("show")
def profile_show_command(
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Output the profile as JSON."),
    ] = False,
) -> None:
    """Show the derived behavioral profile compiled from ~/.onmc/user.db.

    Buckets user memories into preferences, patterns, mistakes-to-avoid, and
    tooling — entirely offline, no LLM calls.  Use `onmc user add` to seed
    the profile with more memories.
    """
    profile = _service().user_profile()
    if json_out:
        import dataclasses

        console.print(
            json.dumps(dataclasses.asdict(profile), ensure_ascii=False, indent=2)
        )
        return
    render_user_profile(profile)


@profile_app.command("rebuild")
def profile_rebuild_command(
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Output the rebuilt profile as JSON."),
    ] = False,
) -> None:
    """Recompute the behavioral profile from ~/.onmc/user.db and display it.

    Equivalent to `onmc profile show` — the profile is always freshly derived
    from the current user store (no cache).
    """
    profile = _service().user_profile()
    if json_out:
        import dataclasses

        console.print(
            json.dumps(dataclasses.asdict(profile), ensure_ascii=False, indent=2)
        )
        return
    render_user_profile(profile)


@spec_app.command("print")
def spec_print_command() -> None:
    """Print the Agent Memory Spec version and schema summary."""
    summary = _service().spec_print()
    console.print(summary, markup=False)


@spec_app.command("validate")
def spec_validate_command(
    path: Annotated[
        Path | None,
        typer.Option(
            "--path",
            help=(
                "Path to the .agent-memory/ directory to validate. "
                "Defaults to .agent-memory/ in the current repo root."
            ),
        ),
    ] = None,
) -> None:
    """Validate that a .agent-memory/ directory conforms to the open spec.

    Checks manifest presence and field completeness, validates all memory and
    task record files, and verifies enum values against the spec. Exits with
    code 1 if any errors are found.
    """
    try:
        _, report = _service().spec_validate(path=path)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    for line in report.summary_lines():
        if line.startswith("  ERROR:"):
            console.print(f"[red]{line}[/red]")
        elif line.startswith("  WARN:"):
            console.print(f"[yellow]{line}[/yellow]")
        else:
            status_color = "green" if report.passed else "red"
            console.print(f"[{status_color}]{line}[/{status_color}]")

    if not report.passed:
        raise typer.Exit(code=1)


@app.command("bench")
def bench_command(
    repo_memory: Annotated[
        bool,
        typer.Option(
            "--repo-memory",
            help="Run against the current repo's real memory store instead of built-in scenario.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON summary to stdout."),
    ] = False,
) -> None:
    """Measure whether onmc memory actually reduces wasted work.

    Runs a deterministic proof harness comparing two conditions: without onmc
    memory vs with onmc memory (brief/recall injected).  Default uses a
    built-in synthetic scenario that works on any repo with no init needed.

    The harness is a deterministic simulation — no LLM is called.  Results are
    reproducible in CI.  See the bench/harness.py module docstring for the full
    methodology.
    """
    import json as _json

    from rich.table import Table

    from oh_no_my_claudecode.bench.harness import (
        BUILTIN_SCENARIO,
        BenchScenario,
        MemoryRecord,
        run_benchmark,
    )
    from oh_no_my_claudecode.config import compiled_dir
    from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now

    scenario: BenchScenario

    if repo_memory:
        try:
            _repo_root, _config, storage = _service()._load_context()  # noqa: SLF001
        except FileNotFoundError as exc:
            raise typer.Exit(code=_fatal(str(exc))) from exc

        memories_raw = storage.list_memories()
        repo_memories = [
            MemoryRecord(kind=m.kind.value, summary=m.summary, relevant_to=[]) for m in memories_raw
        ]
        # Re-use built-in tasks but replace the memory store with real repo memories
        scenario = BenchScenario(
            name="onmc-repo-memory",
            description="Built-in tasks run against this repo's real memory store.",
            tasks=list(BUILTIN_SCENARIO.tasks),
            memories=repo_memories,
            baseline_context_tokens=BUILTIN_SCENARIO.baseline_context_tokens,
        )
    else:
        scenario = BUILTIN_SCENARIO

    result = run_benchmark(scenario)

    if json_output:
        import dataclasses

        typer.echo(
            _json.dumps(
                {
                    "scenario": result.scenario_name,
                    "without_memory": dataclasses.asdict(result.without_memory),
                    "with_memory": dataclasses.asdict(result.with_memory),
                    "deltas": {
                        "repeated_failure_rate": round(result.repeated_failure_rate_delta, 4),
                        "wasted_attempts": result.wasted_attempts_delta,
                        "context_tokens_pct_reduction": round(
                            result.context_tokens_pct_reduction, 1
                        ),
                        "tasks_resolved": result.tasks_resolved_delta,
                    },
                },
                indent=2,
            )
        )
        return

    # Rich comparison table
    table = Table(title=f"onmc bench — {result.scenario_name}", show_lines=True)
    table.add_column("Metric", style="bold")
    table.add_column("Without memory", justify="right")
    table.add_column("With memory", justify="right")
    table.add_column("Delta", justify="right")

    w = result.without_memory
    m = result.with_memory

    table.add_row(
        "Repeated-failure rate",
        f"{w.repeated_failure_rate:.0%}",
        f"{m.repeated_failure_rate:.0%}",
        f"[green]-{result.repeated_failure_rate_delta:.0%}[/green]",
    )
    table.add_row(
        "Wasted attempts",
        str(w.wasted_attempts),
        str(m.wasted_attempts),
        f"[green]-{result.wasted_attempts_delta}[/green]",
    )
    table.add_row(
        "Context tokens (proxy)",
        str(w.context_tokens),
        str(m.context_tokens),
        f"[green]-{result.context_tokens_pct_reduction:.0f}%[/green]",
    )
    table.add_row(
        "Tasks resolved",
        str(w.tasks_resolved),
        str(m.tasks_resolved),
        f"[green]+{result.tasks_resolved_delta}[/green]",
    )
    console.print(table)

    console.print(
        f"\n[bold]Headline deltas:[/bold] "
        f"repeated-failure rate: "
        f"{w.repeated_failure_rate:.0%} → {m.repeated_failure_rate:.0%}"
        f"  |  context tokens: -{result.context_tokens_pct_reduction:.0f}%"
        f"  |  wasted attempts: -{result.wasted_attempts_delta}"
    )
    console.print(
        "[dim]Methodology: deterministic simulation — no LLM calls. "
        "Results are identical across runs. See bench/harness.py for details.[/dim]"
    )

    # Write artifact
    try:
        svc = _service()
        _repo_root, _config, _storage = svc._load_context()  # noqa: SLF001
        artifact_dir = compiled_dir(_config, _repo_root)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        ts = isoformat_utc(utc_now()).replace(":", "-").replace("+", "Z")
        artifact_path = artifact_dir / f"{ts}-bench.md"
        artifact_path.write_text(result.to_markdown(), encoding="utf-8")
        console.print(f"[green]Wrote bench artifact:[/green] {artifact_path}")
    except Exception:  # noqa: BLE001, S110
        pass  # artifact write is best-effort; bench still exits 0


@app.command("savings")
def savings_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Show a shareable 'Memory Wrapped' token-ROI card.

    Renders a screenshot-worthy terminal card summarising the memory brain:
    memories / skills / playbooks stored, the simulated context-token savings
    percentage, repeated-failure rate improvement, and hotspot coverage.

    Token-ROI numbers come from the same deterministic bench harness as
    ``onmc bench`` — no LLM is called.  Results are identical across runs on
    the same memory store.  Use ``--json`` for machine-readable output.
    """
    import json as _json

    try:
        _, result = _service().savings()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        typer.echo(
            _json.dumps(
                {
                    "memories_count": result.memories_count,
                    "skills_count": result.skills_count,
                    "playbooks_count": result.playbooks_count,
                    "context_tokens_pct_reduction": result.context_tokens_pct_reduction,
                    "repeated_failure_rate_delta": result.repeated_failure_rate_delta,
                    "wasted_attempts_saved": result.wasted_attempts_saved,
                    "covered_hotspots": result.covered_hotspots,
                    "total_hotspots": result.total_hotspots,
                    "top_covered_names": result.top_covered_names,
                    "scenario_name": result.scenario_name,
                    "now": result.now,
                    "extra_notes": result.extra_notes,
                },
                indent=2,
            )
        )
        return

    render_savings_card(result)


@app.command("evolution")
def evolution_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Show the compounding-proof evolution card across loop/autopilot runs.

    Reads all run receipts from ``.agent-memory/receipts/`` and computes
    trend metrics: cost delta, iterations-to-converge delta, and verified
    rate.  All numbers come from real receipt data — no simulation.

    Requires at least 2 completed loop/autopilot runs with receipts.  Run
    ``onmc loop`` or ``onmc autopilot`` to generate receipts first.

    Use ``--json`` for machine-readable output.
    """
    import dataclasses
    import json as _json

    try:
        _, report = _service().evolution()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        typer.echo(_json.dumps(dataclasses.asdict(report), indent=2))
        return

    render_evolution_card(report)


# ---------------------------------------------------------------------------
# Ledger — agent-work cost / ROI accounting over receipts
# ---------------------------------------------------------------------------


def _emit_ledger_summary(scope: str, *, json_output: bool) -> None:
    """Compute and render (or JSON-dump) a ledger summary for *scope*."""
    import dataclasses
    import json as _json

    try:
        _, summary = _service().ledger_summary(scope=scope)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        payload = dataclasses.asdict(summary)
        payload["cost_label"] = summary.cost_label
        typer.echo(_json.dumps(payload, indent=2))
        return

    render_ledger_summary(summary)


@ledger_app.command("today")
def ledger_today_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Account today's agent work: cost, wall-time, success-rate, breakdowns.

    Reads run receipts from ``.agent-memory/receipts/`` dated today (UTC).
    Cost is shown as ``n/a`` when no receipt reported it — never fabricated.
    """
    _emit_ledger_summary("today", json_output=json_output)


@ledger_app.command("project")
def ledger_project_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Account all agent work in this project across every run receipt.

    Aggregates cost, wall-time, success-rate, and per-model / per-agent
    breakdowns from every ``run-*.json`` receipt.  Honest about missing cost
    data via the summary note.
    """
    _emit_ledger_summary("project", json_output=json_output)


@ledger_app.command("roi")
def ledger_roi_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Show an honestly-labelled ROI *estimate* (est) over all receipts.

    Compares real agent wall-clock time against a transparent assumption of
    human minutes per run.  The result is explicitly marked ``est`` and carries
    its assumption — it is an estimate, not a measurement.
    """
    import dataclasses
    import json as _json

    from oh_no_my_claudecode.ledger.accounting import roi as _roi

    try:
        _, summary = _service().ledger_summary(scope="project")
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    estimate = _roi(summary)

    if json_output:
        typer.echo(_json.dumps(dataclasses.asdict(estimate), indent=2))
        return

    if summary.run_count == 0:
        console.print(
            "[yellow]No run receipts yet — run `onmc loop` or `onmc swarm` first.[/yellow]"
        )
        return

    saved = estimate.estimated_minutes_saved
    saved_color = "green" if saved > 0 else "yellow"
    console.print(
        f"[bold cyan]onmc ledger ROI [dim](est)[/dim][/bold cyan]  "
        f"over {summary.run_count} runs"
    )
    console.print(
        f"  Agent wall-time:     [bold]{estimate.agent_wall_minutes:g} min[/bold]"
    )
    console.print(
        f"  Est. human-time:     [bold]{estimate.estimated_human_minutes:g} min[/bold] "
        f"[dim]({estimate.assumed_human_minutes_per_run:g} min/run assumed)[/dim]"
    )
    console.print(
        f"  Est. time saved:     [{saved_color}]{saved:g} min[/{saved_color}] "
        "[dim](est)[/dim]"
    )
    if summary.total_cost_usd > 0:
        console.print(
            f"  Agent spend:         [bold]${summary.total_cost_usd:.4f}[/bold]"
        )
    console.print(f"  [dim]{estimate.assumption_note}[/dim]")


@fleet_app.command("status")
def fleet_status_command(
    swarm_id: Annotated[
        str | None,
        typer.Option("--swarm-id", help="Limit output to one swarm id."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Summarize local swarm, claim, and receipt state."""
    status = _service().fleet_status(swarm_id=swarm_id)
    if json_output:
        typer.echo(json.dumps(status.to_dict(), indent=2, sort_keys=True))
        return
    render_fleet_status(status)


@fleet_app.command("doctor")
def fleet_doctor_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Diagnose stuck local fleet state."""
    report = _service().fleet_doctor()
    if json_output:
        typer.echo(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return
    render_fleet_doctor(report)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("benchmark")
def benchmark_command(
    runs: Annotated[
        int,
        typer.Option(
            "--runs",
            help="Number of timing repetitions for timed benchmarks (default: 20).",
        ),
    ] = 20,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Run a reproducible benchmark suite against the current repo brain.

    Measures five benchmarks — each labelled MEASURED (live, reproducible) or
    SIM (deterministic model, no LLM):

    \b
    MEASURED:
      1. recall_latency      — compile_recall p50/p95 ms + hits/query
      2. terse_vs_verbose    — mean % char reduction (title+citation vs markdown)
      3. toon_vs_json        — % char reduction (TOON vs compact JSON)
      4. brain_composition   — memory count + per-kind breakdown

    SIM (deterministic, identical across runs):
      5. harness_sim         — repeated-failure delta, wasted-attempts saved,
                               context-token % reduction, tasks-resolved delta

    Use --json for machine-readable output.  --runs controls timing precision.
    """
    import dataclasses
    import json as _json

    try:
        _, report = _service().benchmark(runs=runs)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        typer.echo(
            _json.dumps(
                {
                    "brain_memory_count": report.brain_memory_count,
                    "generated_note": report.generated_note,
                    "metrics": [dataclasses.asdict(m) for m in report.metrics],
                },
                indent=2,
            )
        )
        return

    render_benchmark_report(report)


@app.command("plug")
def plug_command(
    target: Annotated[
        str,
        typer.Argument(
            help=(
                "Agent to wire onmc into. "
                "Choices: claude-code, codex, opencode, cursor, omc, omx, all."
            )
        ),
    ],
) -> None:
    """Wire onmc into a target coding agent (one-shot idempotent wizard).

    \b
    Targets
    -------
    claude-code   Install Claude Code hooks + .mcp.json (safe to re-run).
    codex         Write/refresh an AGENTS.md stanza so Codex runs onmc brief
                  and onmc guard at session start.
    opencode      Write/refresh an AGENTS.md stanza for OpenCode + export
                  onmc skills to .opencode/skills/.
    cursor        Write/refresh .cursor/rules/onmc.md (Cursor >=0.40 format).
    omc           Write docs/integrations/omc.md with a copy-paste OMC adapter.
    omx           Write docs/integrations/omx.md with a copy-paste OMX adapter.
    all           Apply claude-code + codex + opencode + cursor (safe subset).

    All writes are idempotent — running twice never duplicates stanzas.
    """
    from oh_no_my_claudecode.integrations.plug import SUPPORTED_TARGETS

    if target not in SUPPORTED_TARGETS:
        known = ", ".join(SUPPORTED_TARGETS)
        raise typer.Exit(code=_fatal(f"Unknown target {target!r}. Supported: {known}"))

    try:
        result = _service().plug(target)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    for path in result.files_written:
        console.print(f"[green]wrote:[/green] {path}")
    for path in result.files_skipped:
        console.print(f"[dim]skipped (already up to date):[/dim] {path}")
    for note in result.notes:
        console.print(f"  {note}")
    if not result.files_written and not result.files_skipped:
        console.print(f"[green]onmc plug {target}: done.[/green]")


# ---------------------------------------------------------------------------
# gh-aw group — memory-aware GitHub Actions agentic workflows
# ---------------------------------------------------------------------------


@gh_aw_app.command("init")
def gh_aw_init_command(
    path: Annotated[
        Path | None,
        typer.Argument(
            help=(
                "Target repo root. Defaults to the current directory (or nearest git root). "
                "The four workflows are written to PATH/.github/workflows/onmc-*.yml."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be written without writing anything."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing onmc-managed workflow files."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON."),
    ] = False,
) -> None:
    """Scaffold memory-aware GitHub Actions workflows into a target repo.

    \b
    Generates four workflow files in .github/workflows/:
      onmc-issue-context.yml   — post memory context on new issues
      onmc-pr-preflight.yml    — blast-radius + memories + audit on PR open
      onmc-pr-learn.yml        — record merged PR outcome for future agents
      onmc-weekly-audit.yml    — weekly stale-memory audit via scheduled issue

    All writes are idempotent — re-running skips already-managed files unless
    --force is passed.  Use --dry-run to preview without writing anything.
    """
    repo_root = path if path is not None else Path.cwd()

    try:
        result = _service().gh_aw_init(repo_root, dry_run=dry_run, force=force)
    except (FileNotFoundError, ValueError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        import json as _json

        console.print(
            _json.dumps(
                {
                    "written": result.written,
                    "skipped": result.skipped,
                    "dry_run": result.dry_run,
                },
                indent=2,
            )
        )
        return

    render_gh_aw_init_result(result)


@app.command("feedback")
def feedback_command(
    memory_id: Annotated[str, typer.Argument(help="Memory ID to apply feedback to.")],
    direction: Annotated[
        str,
        typer.Argument(help="Trust signal: 'up' (useful) or 'down' (wrong/misleading)."),
    ],
    note: Annotated[
        str | None,
        typer.Option("--note", help="Optional note appended to the memory details."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the updated memory as JSON instead of a rich panel."),
    ] = False,
) -> None:
    """Apply a human trust signal to a stored memory.

    Use 'up' when a recalled memory proved useful; use 'down' when it was
    wrong or misleading.  Positive feedback slows confidence decay so
    corroborated memories stay ranked higher for longer.  Negative feedback
    demotes but does not erase — the memory remains searchable at a lower
    rank.

    \b
    Examples
    --------
    onmc feedback mem_abc123 up
    onmc feedback mem_abc123 down --note "outdated after refactor"
    onmc feedback mem_abc123 up --json
    """
    if direction not in ("up", "down"):
        raise typer.Exit(
            code=_fatal(
                f"direction must be 'up' or 'down', got {direction!r}. "
                "Usage: onmc feedback <memory-id> <up|down>"
            )
        )
    try:
        updated = _service().feedback(memory_id, direction, note=note)
    except (FileNotFoundError, LookupError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "id": updated.id,
                    "direction": direction,
                    "feedback_score": round(updated.feedback_score, 4),
                    "confidence": round(updated.confidence, 4),
                    "updated_at": updated.updated_at.isoformat(),
                }
            )
        )
        return

    arrow = "[green]up[/green]" if direction == "up" else "[yellow]down[/yellow]"
    console.print(
        f"[bold]Feedback:[/bold] {arrow}  "
        f"feedback_score={updated.feedback_score:.2f}  "
        f"confidence={updated.confidence:.2f}  "
        f"id={updated.id}"
    )


# ---------------------------------------------------------------------------
# Notify / context firewall commands
# ---------------------------------------------------------------------------


@notify_app.command("status")
def notify_status_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the status as JSON instead of a rich panel."),
    ] = False,
) -> None:
    """Show the active context firewall sink configuration.

    Reads from config.yaml and env vars (env wins).  Displays the active sink
    type, log path, and masked webhook URLs when configured.

    Environment overrides:
    - ONMC_NOTIFY_ENABLED=0  disable the firewall entirely.
    - ONMC_NOTIFY_SINK       "file" | "discord" | "slack" | "none".
    - ONMC_DISCORD_WEBHOOK   Discord incoming webhook URL.
    - ONMC_SLACK_WEBHOOK     Slack incoming webhook URL.
    """
    status = _service().notify_status()
    if json_output:
        typer.echo(json.dumps(status, indent=2))
        return
    render_notify_status(status)


@notify_app.command("test")
def notify_test_command(
    message: Annotated[
        str,
        typer.Option("--message", "-m", help="Custom message for the test event."),
    ] = "test notification from onmc",
) -> None:
    """Emit a test event to the active sink and report where it went.

    Useful for verifying that the context firewall is correctly routed before
    connecting real hooks.  The test event has kind=generic and severity=routine.
    """
    result = _service().notify_test(message=message)
    console.print(f"[green]notify test:[/green] {result}")


@notify_app.command("tail")
def notify_tail_command(
    n: Annotated[
        int,
        typer.Option("-n", "--lines", min=1, help="Number of recent events to show."),
    ] = 20,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit events as a JSON array."),
    ] = False,
) -> None:
    """Show recent events from the context firewall log (.onmc/notify.log).

    Only the FileSink (the default) produces a readable local log.  Discord and
    Slack sinks route events to the webhook without storing them locally, but
    the FileSink always writes a local JSONL copy when enabled.
    """
    events = _service().notify_tail(n=n)
    if json_output:
        typer.echo(json.dumps(events, indent=2))
        return
    render_notify_tail(events)


@app.command("import")
def import_command(
    source: Annotated[
        str,
        typer.Argument(
            help=(
                "Source to import from. "
                "Use 'omc' for oh-my-claudecode skills, "
                "'hermes' for Nous hermes-agent context files, "
                "or a path to a .md file / directory."
            )
        ),
    ],
    path: Annotated[
        Path | None,
        typer.Argument(
            help=(
                "Optional path override. For 'omc': path to .omc/skills dir. "
                "For 'hermes': path to MEMORY.md / USER.md / containing directory. "
                "For generic markdown: the .md file or directory (use as 'source' instead)."
            )
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Parse and report without writing anything."),
    ] = False,
    as_kind: Annotated[
        str,
        typer.Option(
            "--as",
            help="Import generic markdown as 'skill' (default) or 'memory'.",
        ),
    ] = "skill",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the result as JSON instead of a rich table."),
    ] = False,
) -> None:
    """Import skills or memories from an external tool into the ONMC brain.

    \b
    Sources
    -------
    omc       oh-my-claudecode skill files (.omc/skills/*.md).
              Auto-detects project (.omc/skills) then user (~/.omc/skills).
              Pass a path to override: onmc import omc /path/to/skills/

    hermes    Nous hermes-agent context files (MEMORY.md, USER.md).
              Auto-detects in the current directory.
              Pass a path to a file or directory to override.

    <path>    Generic .md file or directory of .md files.
              Imported as skills by default; pass --as memory to import
              each ## section as a separate memory entry.

    \b
    Idempotent
    ----------
    Re-importing the same files is safe: items already present in the store
    (matched by stable content-derived id) are counted as skipped, never
    duplicated.  Use --dry-run to preview without writing.

    \b
    Examples
    --------
    onmc import omc
    onmc import omc ~/.omc/skills
    onmc import hermes
    onmc import hermes ./MEMORY.md
    onmc import ./docs/how-tos/
    onmc import ./RUNBOOK.md --as memory
    onmc import omc --dry-run
    onmc import hermes --json
    """
    if as_kind not in ("skill", "memory"):
        raise typer.Exit(
            code=_fatal(
                f"--as must be 'skill' or 'memory', got {as_kind!r}. "
                "Usage: onmc import <source> [path] [--as skill|memory]"
            )
        )
    try:
        result = _service().import_from(source, path, dry_run=dry_run, as_kind=as_kind)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc
    except ValueError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "source": result.source,
                    "as_kind": result.as_kind,
                    "imported": result.imported,
                    "skipped": result.skipped,
                    "dry_run": result.dry_run,
                    "items": result.items,
                },
                indent=2,
            )
        )
        return

    render_import_summary(result)

    if dry_run:
        console.print(
            "[yellow]Dry run — no changes written. "
            "Remove --dry-run to import.[/yellow]"
        )
    elif result.imported > 0:
        console.print(
            f"[green]Imported {result.imported} {result.as_kind}(s) "
            f"from {result.source}.[/green]"
        )
    else:
        console.print(
            f"[dim]Nothing new to import from {result.source} "
            f"({result.skipped} already present).[/dim]"
        )


@app.command("loop")
def loop_command(
    goal: Annotated[
        str | None,
        typer.Option("--goal", help="Goal text for the loop (inline)."),
    ] = None,
    spec: Annotated[
        str | None,
        typer.Option("--spec", help="Path to a file containing the goal text."),
    ] = None,
    template: Annotated[
        str | None,
        typer.Option(
            "--template",
            help=(
                "Use a built-in loop template to prefill goal, verify, and limits. "
                "Available: ci-healer, pr-babysitter, issue-to-pr. "
                "Explicit flags override template defaults. "
                "Use --list-templates to see all templates with descriptions."
            ),
        ),
    ] = None,
    list_templates: Annotated[
        bool,
        typer.Option(
            "--list-templates",
            help="Print available built-in loop templates and exit.",
        ),
    ] = False,
    agent: Annotated[
        str,
        typer.Option("--agent", help="Agent CLI to use: claude (default), codex, or opencode."),
    ] = "claude",
    max_iterations: Annotated[
        int | None,
        typer.Option("--max-iterations", min=1, help="Maximum loop iterations."),
    ] = None,
    budget_tokens: Annotated[
        int | None,
        typer.Option("--budget-tokens", min=1, help="Stop when total tokens exceed this budget."),
    ] = None,
    verify: Annotated[
        str | None,
        typer.Option("--verify", help="Shell command run after each iteration to verify success."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help=(
                "Build the prompt and recall dead-ends without invoking the agent or verify. "
                "Safe to run without any configured agent."
            ),
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the full result as JSON."),
    ] = False,
    max_cost_usd: Annotated[
        float | None,
        typer.Option(
            "--max-cost-usd",
            min=0.0,
            help="Stop before the next iteration when cumulative cost (USD) exceeds this value.",
        ),
    ] = None,
    max_wall_seconds: Annotated[
        int | None,
        typer.Option(
            "--max-wall-seconds",
            min=1,
            help="Stop before the next iteration when elapsed wall-clock seconds exceed this.",
        ),
    ] = None,
    isolate: Annotated[
        bool,
        typer.Option(
            "--isolate",
            help=(
                "Run the loop inside a fresh git worktree so changes are isolated. "
                "On success (converged) the worktree path is preserved; on failure "
                "the worktree is removed and no partial changes leak into the working "
                "tree. Degrades gracefully (warns + runs in-place) when git worktree "
                "add fails."
            ),
        ),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            help=(
                "Resume a previous run from its last checkpoint. "
                "Loads the checkpoint for the matching goal + verify pair "
                "and continues from the next iteration, preserving all prior "
                "contracts and counters. No-op when no matching checkpoint exists."
            ),
        ),
    ] = False,
) -> None:
    """Run a memory-grounded autonomous loop that avoids recorded dead-ends.

    Each iteration recalls FAILED_APPROACH memories so the agent cannot repeat
    known dead-ends.  Wins are recorded as DECISION memories; losses are
    recorded as FAILED_APPROACH memories so future iterations block them.

    A tamper-evident run receipt is written to .agent-memory/receipts/ after
    every non-dry-run invocation.  A checkpoint is saved to
    .onmc/loop-state/ after every iteration so runs can be resumed with
    --resume.

    \b
    Examples
    --------
    onmc loop --goal "fix the cache invalidation bug" --verify "pytest tests/"
    onmc loop --goal "fix the bug" --agent codex --verify "pytest tests/"
    onmc loop --goal "fix the bug" --agent opencode --verify "pytest tests/"
    onmc loop --spec goal.txt --max-iterations 5 --budget-tokens 50000
    onmc loop --goal "refactor auth module" --dry-run          # preview prompt only
    onmc loop --goal "fix flaky test" --json                   # machine-readable output
    onmc loop --goal "fix bug" --max-cost-usd 2.00             # stop at $2 spend
    onmc loop --goal "fix bug" --max-wall-seconds 300          # stop after 5 minutes
    onmc loop --goal "fix bug" --isolate                       # run in isolated worktree
    onmc loop --goal "fix bug" --max-wall-seconds 60 && onmc loop --goal "fix bug" --resume
    onmc loop --template ci-healer                             # use built-in template
    onmc loop --template issue-to-pr --goal "implement #42"   # template + custom goal
    onmc loop --list-templates                                 # show all templates
    """
    import dataclasses
    import json as _json

    from oh_no_my_claudecode.loop.templates import get_template
    from oh_no_my_claudecode.loop.templates import list_templates as _list_templates

    # --list-templates: print table and exit.
    if list_templates:
        console.print("[bold]Available loop templates:[/bold]")
        for name, desc in _list_templates():
            console.print(f"  [cyan]{name}[/cyan]  {desc}")
        raise typer.Exit(code=0)

    # Resolve template defaults first; explicit flags override.
    _tmpl_goal: str | None = None
    _tmpl_verify: str | None = None
    _tmpl_max_iterations: int = 10
    _tmpl_max_cost_usd: float | None = None
    _tmpl_max_wall_seconds: int | None = None

    if template is not None:
        try:
            tmpl = get_template(template)
        except ValueError as exc:
            raise typer.Exit(code=_fatal(str(exc))) from exc
        _tmpl_goal = tmpl.goal
        _tmpl_verify = tmpl.verify
        _tmpl_max_iterations = tmpl.max_iterations
        _tmpl_max_cost_usd = tmpl.max_cost_usd
        _tmpl_max_wall_seconds = tmpl.max_wall_seconds

    # Apply flag overrides on top of template defaults.
    _resolved_verify: str = verify if verify is not None else (_tmpl_verify or "pytest")
    _resolved_max_iterations: int = (
        max_iterations if max_iterations is not None else _tmpl_max_iterations
    )
    _resolved_max_cost_usd: float | None = (
        max_cost_usd if max_cost_usd is not None else _tmpl_max_cost_usd
    )
    _resolved_max_wall_seconds: int | None = (
        max_wall_seconds if max_wall_seconds is not None else _tmpl_max_wall_seconds
    )

    # Goal resolution: explicit --goal / --spec always win; fall back to template goal.
    if goal is not None and spec is not None:
        raise typer.Exit(code=_fatal("Provide either --goal or --spec, not both."))

    resolved_goal: str
    if spec is not None:
        spec_path = Path(spec)
        if not spec_path.exists():
            raise typer.Exit(code=_fatal(f"Spec file not found: {spec}"))
        resolved_goal = spec_path.read_text(encoding="utf-8").strip()
    elif goal is not None:
        resolved_goal = goal
    elif _tmpl_goal is not None:
        resolved_goal = _tmpl_goal
    else:
        raise typer.Exit(code=_fatal("Provide --goal, --spec, or --template."))

    if agent not in {"claude", "codex", "opencode"}:
        raise typer.Exit(
            code=_fatal(f"Unknown agent {agent!r}. Choose 'claude', 'codex', or 'opencode'.")
        )

    try:
        result, receipt_path = _service().loop(
            resolved_goal,
            agent=agent,
            max_iterations=_resolved_max_iterations,
            budget_tokens=budget_tokens,
            verify_command=_resolved_verify,
            dry_run=dry_run,
            max_cost_usd=_resolved_max_cost_usd,
            max_wall_seconds=_resolved_max_wall_seconds,
            isolate=isolate,
            resume=resume,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        from oh_no_my_claudecode.loop.receipt import RunReceipt

        payload: dict[str, object] = dataclasses.asdict(result)
        if receipt_path is not None:
            try:
                import json as _json2

                receipt_data = _json2.loads(receipt_path.read_text(encoding="utf-8"))
                payload["receipt"] = receipt_data
            except Exception:  # noqa: BLE001
                payload["receipt_path"] = str(receipt_path)
        _ = RunReceipt  # keep import alive for type checking
        console.print_json(_json.dumps(payload))
        raise typer.Exit(code=0)

    if dry_run:
        console.print("[bold]Dry-run: planned prompt (no agent invoked):[/bold]")
        if result.iterations:
            from rich.markdown import Markdown as _Markdown

            console.print(_Markdown(result.iterations[0].action_summary))
        raise typer.Exit(code=0)

    from oh_no_my_claudecode.rendering.console import render_loop_receipt_block

    render_loop_result(result)
    render_loop_receipt_block(result, receipt_path=receipt_path, verify_command=_resolved_verify)
    raise typer.Exit(code=0 if result.converged else 1)


@app.command("loop-templates")
def loop_templates_command() -> None:
    """List available built-in loop templates.

    Each template prefills goal, verify command, and iteration limits for
    common autonomous-agent workflows.  Pass a template name to
    ``onmc loop --template <name>`` to use it.

    \b
    Available templates
    -------------------
    ci-healer      Fix failing CI without changing public behaviour.
    pr-babysitter  Keep a pull request green (rebase, resolve conflicts).
    issue-to-pr    Implement a GitHub issue as a PR-ready change.
    """
    from oh_no_my_claudecode.loop.templates import list_templates as _list_templates

    console.print("[bold]Available loop templates:[/bold]")
    for name, desc in _list_templates():
        console.print(f"  [cyan]{name}[/cyan]  {desc}")
    raise typer.Exit(code=0)


@app.command("autopilot")
def autopilot_command(
    goal: Annotated[
        str,
        typer.Argument(help="Goal for the autopilot run."),
    ],
    agent: Annotated[
        str,
        typer.Option(
            "--agent", help="Agent CLI to use: claude (default), codex, or opencode."
        ),
    ] = "claude",
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help=(
                "Run only the KNOW phase (compile brief, guard, profile) without "
                "invoking any agent or verify subprocess.  No spend, no memory writes."
            ),
        ),
    ] = False,
    max_iterations: Annotated[
        int,
        typer.Option("--max-iterations", min=1, help="Maximum loop iterations."),
    ] = 10,
    budget_tokens: Annotated[
        int | None,
        typer.Option("--budget-tokens", min=1, help="Stop when total tokens exceed this budget."),
    ] = None,
    max_cost_usd: Annotated[
        float | None,
        typer.Option(
            "--max-cost-usd",
            min=0.0,
            help="Stop before the next iteration when cumulative cost (USD) exceeds this value.",
        ),
    ] = None,
    max_wall_seconds: Annotated[
        int | None,
        typer.Option(
            "--max-wall-seconds",
            min=1,
            help="Stop before the next iteration when elapsed wall-clock seconds exceed this.",
        ),
    ] = None,
    verify: Annotated[
        str,
        typer.Option("--verify", help="Shell command run after each iteration to verify success."),
    ] = "pytest",
    plan_with: Annotated[
        str | None,
        typer.Option(
            "--plan-with",
            help=(
                "Model name for the PLAN step (expensive model).  When set, a planning "
                "pass runs before ACT: the model produces a precise implementation plan "
                "that is injected into the ACT goal and recorded as a memory.  "
                "Example: --plan-with claude-opus-4-5"
            ),
        ),
    ] = None,
    execute_with: Annotated[
        str | None,
        typer.Option(
            "--execute-with",
            help=(
                "Model name for the ACT (execute) step (cheap model).  When set, the "
                "loop runs with this model instead of the agent default.  "
                "Example: --execute-with claude-haiku-4-5"
            ),
        ),
    ] = None,
    isolate: Annotated[
        bool,
        typer.Option(
            "--isolate/--no-isolate",
            help=(
                "Run ACT inside a fresh git worktree and keep it only on success. "
                "Default off for backward compatibility."
            ),
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the full result as JSON."),
    ] = False,
) -> None:
    """Run the full KNOW→(PLAN)→ACT→PROVE→LEARN autopilot cycle on a goal.

    Orchestrates every onmc command in one narrated run:

    \b
    🧠 KNOW  — compile_brief + guard (dead-ends) + user_profile (preferences).
    📋 PLAN  — optional; --plan-with <model> runs an expensive planning pass first.
    ⚙ ACT   — memory-grounded autonomous loop (avoids recorded dead-ends).
    ✅ PROVE  — receipt + verified/not-verified verdict + cost.
    📈 LEARN  — capture session memory + skill_promote + consolidate.

    Ends with a "Your brain grew" delta (+N memories · +N skills · N dead-ends).

    \b
    Examples
    --------
    onmc autopilot "fix the cache invalidation bug"
    onmc autopilot "add rate limiting" --verify "pytest tests/" --max-cost-usd 2.00
    onmc autopilot "refactor auth module" --dry-run   # KNOW only, no spend
    onmc autopilot "fix flaky test" --agent codex --max-iterations 5
    onmc autopilot "fix flaky test" --agent opencode --max-iterations 5
    onmc autopilot "fix bug" --json                   # machine-readable output
    onmc autopilot "add feature" --plan-with claude-opus-4-5 --execute-with claude-haiku-4-5
    onmc autopilot "fix CI" --isolate                  # safe worktree run
    """
    import dataclasses

    from oh_no_my_claudecode.autopilot.models import AutopilotResult
    from oh_no_my_claudecode.rendering.console import render_autopilot_result

    if agent not in {"claude", "codex", "opencode"}:
        raise typer.Exit(
            code=_fatal(
                f"Unknown agent {agent!r}. Choose 'claude', 'codex', or 'opencode'."
            )
        )

    try:
        result = _service().autopilot(
            goal,
            agent=agent,
            dry_run=dry_run,
            max_iterations=max_iterations,
            budget_tokens=budget_tokens,
            max_cost_usd=max_cost_usd,
            max_wall_seconds=max_wall_seconds,
            verify_command=verify,
            plan_model=plan_with,
            execute_model=execute_with,
            isolate=isolate,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        if isinstance(result, AutopilotResult):
            from oh_no_my_claudecode.loop.models import LoopResult

            payload: dict[str, object] = {
                "goal": result.goal,
                "verified": result.verified,
                "stop_reason": result.stop_reason,
                "tokens": result.tokens,
                "cost_usd": result.cost_usd,
                "know_brief_summary": result.know_brief_summary,
                "know_dead_ends_count": result.know_dead_ends_count,
                "know_profile_applied": result.know_profile_applied,
                "memories_added": result.memories_added,
                "skills_added": result.skills_added,
                "dead_ends_recorded": result.dead_ends_recorded,
                "skill_promoted_name": result.skill_promoted_name,
                "captured_count": result.captured_count,
                "consolidated_count": result.consolidated_count,
                "brain_before": dataclasses.asdict(result.brain_before),
                "brain_after": dataclasses.asdict(result.brain_after),
                "receipt_path": str(result.receipt_path) if result.receipt_path else None,
                "loop_result": (
                    dataclasses.asdict(result.loop_result)
                    if isinstance(result.loop_result, LoopResult)
                    else None
                ),
                "plan_model": result.plan_model,
                "execute_model": result.execute_model,
                "plan_used": result.plan_used,
                "plan_tokens": result.plan_tokens,
                "plan_cost": result.plan_cost,
            }
            console.print_json(json.dumps(payload))
        raise typer.Exit(code=0)

    render_autopilot_result(result)
    if isinstance(result, AutopilotResult):
        raise typer.Exit(code=0 if result.verified else 1)
    raise typer.Exit(code=0)


@app.command("nomistakes")
def nomistakes_command(
    goal: Annotated[
        str,
        typer.Argument(help="Goal for the PR/CI gate."),
    ],
    agent: Annotated[
        str,
        typer.Option(
            "--agent", help="Agent CLI to use: claude (default), codex, or opencode."
        ),
    ] = "claude",
    autonomy: Annotated[
        str,
        typer.Option(
            "--autonomy",
            help="Autonomy level: L0 observe, L1 advise, L2 act+prove, L3 extended, L4 reserved.",
        ),
    ] = "L2",
    verify: Annotated[
        str,
        typer.Option("--verify", help="Shell verifier required for approval."),
    ] = "pytest",
    max_iterations: Annotated[
        int,
        typer.Option("--max-iterations", min=1, help="Maximum loop iterations."),
    ] = 6,
    budget_tokens: Annotated[
        int | None,
        typer.Option("--budget-tokens", min=1, help="Stop when total tokens exceed this budget."),
    ] = 80_000,
    max_cost_usd: Annotated[
        float | None,
        typer.Option("--max-cost-usd", min=0.0, help="USD cost ceiling for the run."),
    ] = 3.0,
    max_wall_seconds: Annotated[
        int | None,
        typer.Option("--max-wall-seconds", min=1, help="Wall-clock ceiling in seconds."),
    ] = 900,
    audit_fail_on: Annotated[
        str,
        typer.Option(
            "--audit-fail-on",
            help="Block on audit findings at or above: critical, high, medium, low, info.",
        ),
    ] = "high",
    eval_fail_under: Annotated[
        float | None,
        typer.Option(
            "--eval-fail-under",
            min=0.0,
            max=100.0,
            help="Run eval gate and block when score is below this threshold.",
        ),
    ] = None,
    plan_with: Annotated[
        str | None,
        typer.Option("--plan-with", help="Model for optional PLAN step."),
    ] = None,
    execute_with: Annotated[
        str | None,
        typer.Option("--execute-with", help="Model for ACT step."),
    ] = None,
    isolate: Annotated[
        bool,
        typer.Option(
            "--isolate/--no-isolate",
            help="Run in an isolated git worktree by default.",
        ),
    ] = True,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Run gates and KNOW context without invoking the agent."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable gate result."),
    ] = False,
) -> None:
    """Run the No-Mistakes PR gate: audit + eval + autopilot + receipt verdict.

    Approval requires deterministic preflight gates to pass and a verified
    receipt from the underlying autopilot run.  L0/L1 are no-write modes. L2+
    can act, verify, learn, and emit a receipt.

    \b
    Examples
    --------
    onmc nomistakes "fix failing CI" --verify "pytest -q"
    onmc nomistakes "review this PR" --agent codex --eval-fail-under 80
    onmc nomistakes "stabilize flaky tests" \
      --plan-with claude-opus-4-5 --execute-with claude-haiku-4-5
    onmc nomistakes "inspect risk only" --autonomy L1 --dry-run
    """
    import dataclasses

    from oh_no_my_claudecode.audit.scanner import AuditSeverity
    from oh_no_my_claudecode.autopilot.models import AutopilotResult
    from oh_no_my_claudecode.loop.models import LoopResult
    from oh_no_my_claudecode.nomistakes import run_nomistakes
    from oh_no_my_claudecode.nomistakes.models import AutonomyLevel

    if agent not in {"claude", "codex", "opencode"}:
        raise typer.Exit(
            code=_fatal(
                f"Unknown agent {agent!r}. Choose 'claude', 'codex', or 'opencode'."
            )
        )
    if autonomy not in {"L0", "L1", "L2", "L3", "L4"}:
        raise typer.Exit(code=_fatal("Unknown autonomy. Choose L0, L1, L2, L3, or L4."))
    if audit_fail_on not in {"critical", "high", "medium", "low", "info"}:
        raise typer.Exit(
            code=_fatal(
                "--audit-fail-on must be one of: critical, high, medium, low, info."
            )
        )

    try:
        result = run_nomistakes(
            _service(),
            goal,
            agent=agent,
            autonomy=cast(AutonomyLevel, autonomy),
            dry_run=dry_run,
            max_iterations=max_iterations,
            budget_tokens=budget_tokens,
            max_cost_usd=max_cost_usd,
            max_wall_seconds=max_wall_seconds,
            verify_command=verify,
            audit_fail_on=cast(AuditSeverity, audit_fail_on),
            eval_fail_under=eval_fail_under,
            plan_model=plan_with,
            execute_model=execute_with,
            isolate=isolate,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        autopilot_payload: dict[str, object] | None = None
        if isinstance(result.autopilot_result, AutopilotResult):
            ap = result.autopilot_result
            autopilot_payload = {
                "verified": ap.verified,
                "stop_reason": ap.stop_reason,
                "tokens": ap.tokens,
                "cost_usd": ap.cost_usd,
                "receipt_path": str(ap.receipt_path) if ap.receipt_path else None,
                "loop_result": (
                    dataclasses.asdict(ap.loop_result)
                    if isinstance(ap.loop_result, LoopResult)
                    else None
                ),
            }
        payload = {
            "goal": result.goal,
            "approved": result.approved,
            "dry_run": result.dry_run,
            "agent": result.agent,
            "autonomy": result.autonomy,
            "verify_command": result.verify_command,
            "receipt_path": result.receipt_path,
            "gates": [dataclasses.asdict(gate) for gate in result.gates],
            "autopilot": autopilot_payload,
        }
        console.print_json(json.dumps(payload))
        raise typer.Exit(code=0 if result.approved else 1)

    render_nomistakes_result(result)
    raise typer.Exit(code=0 if result.approved else 1)


@conventions_app.command("capture")
def conventions_capture_command(
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite an existing .onmc/conventions.md."),
    ] = False,
) -> None:
    """Detect the repo's coding conventions and write .onmc/conventions.md.

    Parses pyproject.toml ([tool.ruff] line-length / select / target-version and
    [tool.mypy] strict) and attaches the fixed repo norms.  Deterministic and
    offline.  Idempotent: re-running is a no-op unless --force is passed.
    """
    conv, path = _service().conventions_capture(force=force)
    render_conventions(conv, path=path)


@conventions_app.command("show")
def conventions_show_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the conventions as JSON for agent injection."),
    ] = False,
) -> None:
    """Print the repo's coding conventions for injection into spawned agents.

    Detects conventions on the fly (does not require a prior capture) and emits
    them as a table, or as JSON with --json.  Deterministic and offline.
    """
    import dataclasses

    conv = _service().conventions_show()
    if as_json:
        sys.stdout.write(json.dumps(dataclasses.asdict(conv), indent=2) + "\n")
        return
    render_conventions(conv)


@app.command("release")
def release_command(
    write: Annotated[
        bool,
        typer.Option(
            "--write/--dry-run",
            help="Edit pyproject.toml + CHANGELOG.md (default: dry-run).",
        ),
    ] = False,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the drafted release as JSON."),
    ] = False,
    git_cliff: Annotated[
        bool,
        typer.Option(
            "--git-cliff/--no-git-cliff",
            help="Use git-cliff to render the CHANGELOG when its binary is on PATH "
            "(default: on; falls back to the built-in renderer when absent).",
        ),
    ] = True,
) -> None:
    """Draft the next release from conventional-commit history.

    Classifies commit subjects since the last tag into a semver bump (feat ->
    minor, fix -> patch, "!"/BREAKING -> major, otherwise patch), computes the
    next version, and renders a CHANGELOG entry in the repo's format.
    Deterministic and offline. When the external git-cliff binary is installed
    it renders the CHANGELOG entry (best-in-class); otherwise the built-in
    renderer is used — pass --no-git-cliff to force the built-in one. Dry-run by
    default — pass --write to bump pyproject.toml and prepend the entry to
    CHANGELOG.md. Never tags or pushes.
    """
    import dataclasses

    try:
        _, draft = _service().release_draft(write=write, use_git_cliff=git_cliff)
    except (FileNotFoundError, ValueError, RepoDiscoveryError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if as_json:
        sys.stdout.write(json.dumps(dataclasses.asdict(draft), indent=2) + "\n")
        return
    render_release_draft(draft, written=write)


def _fatal(message: str) -> int:
    console.print(f"[red]{message}[/red]")
    return 1


# ---------------------------------------------------------------------------
# Trace Observatory
# ---------------------------------------------------------------------------

trace_app = typer.Typer(
    help="Agent Trace Observatory — instrument a session and get a token-ROI report.",
    no_args_is_help=True,
)
app.add_typer(trace_app, name="trace")


@trace_app.command("start")
def trace_start_command(
    label: Annotated[
        str,
        typer.Option("--label", "-l", help="Human-readable label for this session."),
    ] = "",
) -> None:
    """Start a new trace session.

    Creates a JSONL session file under .onmc/traces/ and sets the active
    session pointer.  Run 'onmc trace stop' to close the session and then
    'onmc trace report' to view the results.
    """
    try:
        _, session_id = _service().trace_start(label=label)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if session_id is None:
        raise typer.Exit(code=_fatal("Failed to create trace session (I/O error)."))

    label_part = f"  label: {label}" if label else ""
    console.print(f"[green]Trace session started[/green]  session_id={session_id}{label_part}")
    console.print("[dim]Run 'onmc trace stop' when done, then 'onmc trace report'.[/dim]")


@trace_app.command("stop")
def trace_stop_command() -> None:
    """Close the current trace session."""
    try:
        _, ok = _service().trace_stop()
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if not ok:
        raise typer.Exit(
            code=_fatal("No active trace session found.  Run 'onmc trace start' first.")
        )

    console.print("[green]Trace session closed.[/green]  Run 'onmc trace report' to view results.")


@trace_app.command("report")
def trace_report_command(
    session_id: Annotated[
        str,
        typer.Argument(help="Session ID to report on.  Defaults to the current active session."),
    ] = "",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print machine-readable JSON to stdout."),
    ] = False,
    otel_output: Annotated[
        str,
        typer.Option(
            "--otel",
            help="Write OpenTelemetry GenAI span JSON to this file path.",
            metavar="FILE",
        ),
    ] = "",
) -> None:
    """Show the Agent Trace Observatory token-ROI card for a session.

    Renders a screenshot-worthy terminal card with: estimated token savings,
    repeated reads blocked, tool call stats, memory hit-rate, and loop signals.

    Token-savings estimates are labelled (est) — derived from the bench harness,
    not live LLM measurement.  Use --json for machine-readable output.
    Use --otel <file> to dump OpenTelemetry GenAI-convention span JSON.
    """
    import json as _json

    sid: str | None = session_id if session_id else None

    try:
        _, resolved_sid, report = _service().trace_report(sid)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if otel_output:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        spans = to_otel_spans(report, session_id=resolved_sid)
        otel_path = Path(otel_output)
        try:
            otel_path.write_text(_json.dumps(spans, indent=2), encoding="utf-8")
            console.print(f"[green]OTel spans written to[/green] {otel_path}")
        except OSError as exc:
            raise typer.Exit(code=_fatal(f"Failed to write OTel file: {exc}")) from exc
        if json_output:
            return

    if json_output:
        typer.echo(
            _json.dumps(
                {
                    "session_id": report.session_id,
                    "label": report.label,
                    "started_at": report.started_at,
                    "ended_at": report.ended_at,
                    "total_tokens": report.total_tokens,
                    "est_tokens_without_onmc": report.est_tokens_without_onmc,
                    "tokens_saved_pct": report.tokens_saved_pct,
                    "tool_calls": report.tool_calls,
                    "tool_failures": report.tool_failures,
                    "memory_hits": report.memory_hits,
                    "memory_misses": report.memory_misses,
                    "memory_hit_rate": report.memory_hit_rate,
                    "repeated_file_reads": [
                        {"target": r.target, "count": r.count}
                        for r in report.repeated_file_reads
                    ],
                    "repeated_search_queries": [
                        {"target": r.target, "count": r.count}
                        for r in report.repeated_search_queries
                    ],
                    "repeated_reads_blocked": report.repeated_reads_blocked,
                    "loops_detected": [
                        {"tool": lp.tool, "target": lp.target, "count": lp.count}
                        for lp in report.loops_detected
                    ],
                    "top_wasteful": [
                        {"target": r.target, "count": r.count} for r in report.top_wasteful
                    ],
                    "extra_notes": report.extra_notes,
                },
                indent=2,
            )
        )
        return

    from oh_no_my_claudecode.rendering.console import render_trace_card

    render_trace_card(report)


# ---------------------------------------------------------------------------
# onmc eval — memory evaluation and regression-gate harness
# ---------------------------------------------------------------------------

eval_app = typer.Typer(
    help="Measure and gate memory recall quality (offline, deterministic).",
    no_args_is_help=True,
)
app.add_typer(eval_app, name="eval")


@eval_app.command("create")
def eval_create_command(
    from_memory: Annotated[
        str,
        typer.Option("--from-memory", help="Derive eval case from existing memory ID."),
    ] = "",
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Query/task for the eval case (manual mode)."),
    ] = "",
    case_id: Annotated[
        str,
        typer.Option("--id", help="Custom case ID (optional, auto-derived when omitted)."),
    ] = "",
    expect_file: Annotated[
        list[str],
        typer.Option(
            "--expect-file",
            help=(
                "Expected file/memory ID to appear in recall results. "
                "Repeatable: --expect-file foo --expect-file bar"
            ),
        ),
    ] = [],  # noqa: B006
    expect_deadend: Annotated[
        list[str],
        typer.Option(
            "--expect-deadend",
            help=(
                "Substring expected in a guard dead-end entry. "
                "Repeatable: --expect-deadend 'tried X' --expect-deadend 'bad approach'"
            ),
        ),
    ] = [],  # noqa: B006
    note: Annotated[
        str,
        typer.Option("--note", help="Optional human-readable note about what this case tests."),
    ] = "",
) -> None:
    """Create a new eval case and persist it to .onmc/evals/<id>.json.

    Two modes:

      --from-memory <id>   Derive query + expectations from an existing memory entry.

      --query <text>       Manual mode: provide query + optional --expect-file / --expect-deadend.
    """
    try:
        _, case = _service().eval_create(
            from_memory_id=from_memory or None,
            case_id=case_id or None,
            query=query or None,
            expected_files=list(expect_file),
            expected_deadend_substrings=list(expect_deadend),
            note=note,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    console.print(f"[green]Eval case created:[/green] {case.id}")
    console.print(f"  Query: {case.query[:80]}")
    if case.expected_files:
        console.print(f"  Expected files: {', '.join(case.expected_files[:5])}")
    if case.expected_deadend_substrings:
        console.print(
            f"  Expected deadends: {', '.join(case.expected_deadend_substrings[:3])}"
        )


@eval_app.command("run")
def eval_run_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output results as JSON."),
    ] = False,
    fail_under: Annotated[
        float,
        typer.Option(
            "--fail-under",
            help=(
                "Exit non-zero when pass_rate (0–100) is below this threshold. "
                "Use in CI to gate on memory quality regression."
            ),
            min=0.0,
            max=100.0,
        ),
    ] = 0.0,
    without_memory: Annotated[
        bool,
        typer.Option(
            "--without-memory",
            help="Run the cold baseline (simulate no retrieval). Useful for delta comparison.",
        ),
    ] = False,
    recall_limit: Annotated[
        int,
        typer.Option("--recall-limit", help="Max recall entries per case."),
    ] = 8,
) -> None:
    """Run the eval suite and report memory recall quality.

    Loads all cases from .onmc/evals/ and scores them against the live brain.
    Use --fail-under to gate CI (exits 1 when pass_rate < threshold).

    Examples:

      onmc eval run

      onmc eval run --fail-under 80   # fail CI if <80% of cases pass

      onmc eval run --json            # machine-readable output
    """
    try:
        _, report = _service().eval_run(
            with_memory=not without_memory,
            recall_limit=recall_limit,
        )
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if as_json:
        console.print(
            json.dumps(
                {
                    "with_memory": report.with_memory,
                    "total_cases": report.total_cases,
                    "passed_cases": report.passed_cases,
                    "pass_rate": report.pass_rate,
                    "score": report.score,
                    "mean_injected_chars": report.mean_injected_chars,
                    "results": [
                        {
                            "case_id": r.case_id,
                            "files_hit": r.files_hit,
                            "deadend_hit": r.deadend_hit,
                            "recall_entries": r.recall_entries,
                            "injected_chars": r.injected_chars,
                            "passed": r.passed,
                        }
                        for r in report.results
                    ],
                },
                indent=2,
            )
        )
    else:
        from oh_no_my_claudecode.rendering.console import render_eval_result

        render_eval_result(report)

    if fail_under > 0 and report.score < fail_under:
        raise typer.Exit(code=1)


@eval_app.command("compare")
def eval_compare_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Output comparison as JSON."),
    ] = False,
    baseline: Annotated[
        float,
        typer.Option(
            "--baseline",
            help=(
                "Exit non-zero when the with-memory score delta (0–100) is below this value. "
                "Use in CI to gate on brain contribution regression."
            ),
            min=0.0,
            max=100.0,
        ),
    ] = 0.0,
    recall_limit: Annotated[
        int,
        typer.Option("--recall-limit", help="Max recall entries per case."),
    ] = 8,
) -> None:
    """Compare with-memory vs without-memory eval scores.

    Runs the suite twice and shows the delta.  A positive delta proves the brain
    is contributing.  Use --baseline to gate CI (exits 1 when score_delta < threshold).

    Examples:

      onmc eval compare

      onmc eval compare --baseline 10   # fail CI if brain contributes <10 points

      onmc eval compare --json          # machine-readable output
    """
    try:
        _, comparison = _service().eval_compare(recall_limit=recall_limit)
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if as_json:
        w = comparison.with_memory
        n = comparison.without_memory
        console.print(
            json.dumps(
                {
                    "with_memory": {
                        "score": w.score,
                        "pass_rate": w.pass_rate,
                        "passed_cases": w.passed_cases,
                        "total_cases": w.total_cases,
                        "mean_injected_chars": w.mean_injected_chars,
                    },
                    "without_memory": {
                        "score": n.score,
                        "pass_rate": n.pass_rate,
                        "passed_cases": n.passed_cases,
                        "total_cases": n.total_cases,
                        "mean_injected_chars": n.mean_injected_chars,
                    },
                    "deltas": {
                        "score_delta": comparison.score_delta,
                        "pass_rate_delta": comparison.pass_rate_delta,
                        "chars_delta": comparison.chars_delta,
                    },
                },
                indent=2,
            )
        )
    else:
        from oh_no_my_claudecode.rendering.console import render_eval_result

        render_eval_result(None, comparison=comparison)

    if baseline > 0 and comparison.score_delta < baseline:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# onmc replay — Replay Lab
# ---------------------------------------------------------------------------

replay_app = typer.Typer(
    help="Replay Lab — re-run a recorded session and produce a regression report.",
    no_args_is_help=True,
)
app.add_typer(replay_app, name="replay")


@replay_app.command("run")
def replay_run_command(
    session_id_or_path: Annotated[
        str,
        typer.Argument(
            help=(
                "Session ID (tr_…) to load from .onmc/traces/, "
                "or a direct path to a .jsonl session file."
            ),
        ),
    ],
    compare: Annotated[
        bool,
        typer.Option(
            "--compare",
            help=(
                "Run both with-memory and without-memory conditions and show a "
                "side-by-side delta table."
            ),
        ),
    ] = False,
    without_memory: Annotated[
        bool,
        typer.Option(
            "--without-memory",
            help="Run the cold (no-memory) baseline only. Ignored when --compare is used.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON to stdout."),
    ] = False,
) -> None:
    """Re-derive onmc memory hits over a recorded trace session.

    Loads a session from .onmc/traces/<session-id>.jsonl (or a direct JSONL path),
    then for each query-bearing event re-runs compile_recall and compile_guard
    against the current brain.  Produces a regression report showing which steps
    memory would have influenced.

    No LLM is called.  Deterministic and offline.

    Examples:

      onmc replay run tr_abc123def456

      onmc replay run tr_abc123def456 --compare

      onmc replay run /path/to/session.jsonl --json

      onmc replay run tr_abc123def456 --without-memory
    """
    import json as _json

    try:
        _, result = _service().replay(
            session_id_or_path,
            compare=compare,
            with_memory=not without_memory,
        )
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if json_output:
        from oh_no_my_claudecode.replay.models import ReplayComparison, ReplayReport

        if isinstance(result, ReplayComparison):
            w = result.with_memory
            n = result.without_memory
            data: dict[str, object] = {
                "kind": "comparison",
                "session_id": w.session_id,
                "total_steps": w.total_steps,
                "with_memory": {
                    "steps_with_recall": w.steps_with_recall,
                    "steps_with_deadend": w.steps_with_deadend,
                    "mean_injected_chars": w.mean_injected_chars,
                },
                "without_memory": {
                    "steps_with_recall": n.steps_with_recall,
                    "steps_with_deadend": n.steps_with_deadend,
                    "mean_injected_chars": n.mean_injected_chars,
                },
                "deltas": result.deltas,
                "steps": [
                    {
                        "index": s.index,
                        "query": s.query,
                        "recall_hits": s.recall_hits,
                        "deadend_hits": s.deadend_hits,
                        "injected_chars": s.injected_chars,
                    }
                    for s in w.steps
                ],
            }
        elif isinstance(result, ReplayReport):
            data = {
                "kind": "report",
                "session_id": result.session_id,
                "with_memory": result.with_memory,
                "total_steps": result.total_steps,
                "steps_with_recall": result.steps_with_recall,
                "steps_with_deadend": result.steps_with_deadend,
                "mean_injected_chars": result.mean_injected_chars,
                "steps": [
                    {
                        "index": s.index,
                        "query": s.query,
                        "recall_hits": s.recall_hits,
                        "deadend_hits": s.deadend_hits,
                        "injected_chars": s.injected_chars,
                    }
                    for s in result.steps
                ],
            }
        else:
            data = {"kind": "unknown"}
        typer.echo(_json.dumps(data, indent=2))
        return

    from oh_no_my_claudecode.rendering.console import render_replay_report
    from oh_no_my_claudecode.replay.models import ReplayComparison

    if isinstance(result, ReplayComparison):
        render_replay_report(None, comparison=result)
    else:
        render_replay_report(result)


# ---------------------------------------------------------------------------
# onmc swarm — parallel accountable agent loops
# ---------------------------------------------------------------------------


@swarm_app.command("run")
def swarm_run_command(
    task: Annotated[
        list[str] | None,
        typer.Option(
            "--task",
            help=(
                "Goal text for one swarm unit.  Repeat for multiple tasks.  "
                "Mutually exclusive with --file."
            ),
        ),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option(
            "--file",
            help=(
                "Path to a text file where each non-empty line is one task goal.  "
                "Mutually exclusive with --task."
            ),
        ),
    ] = None,
    agent: Annotated[
        str,
        typer.Option("--agent", help="Agent CLI: claude (default), codex, or opencode."),
    ] = "claude",
    concurrency: Annotated[
        int | None,
        typer.Option(
            "--concurrency",
            min=1,
            help=(
                "Max parallel workers.  Default min(cpu_count-1, 8).  "
                "HONEST: this is a bounded pool — not unlimited simultaneous agents."
            ),
        ),
    ] = None,
    max_cost_usd: Annotated[
        float | None,
        typer.Option("--max-cost-usd", min=0.0, help="Swarm-level total cost ceiling in USD."),
    ] = None,
    per_unit_max_iterations: Annotated[
        int | None,
        typer.Option("--per-unit-max-iterations", min=1, help="Per-unit max loop iterations."),
    ] = None,
    verify: Annotated[
        str | None,
        typer.Option("--verify", help="Verify command applied to all units (default: pytest)."),
    ] = None,
    isolate: Annotated[
        bool,
        typer.Option(
            "--isolate/--no-isolate",
            help="Run each unit in an isolated git worktree (default: True).",
        ),
    ] = True,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit full SwarmResult as JSON to stdout."),
    ] = False,
) -> None:
    """Run a parallel swarm of accountable agent loops.

    Each task is one run_loop unit with its own receipt.  Tasks are queued and
    drained by a bounded worker pool (default: min(cpu_count-1, 8) workers).

    HONEST CONCURRENCY: --concurrency N means at most N loops run at the same
    time, NOT N simultaneous agent processes per loop iteration.  API rate
    limits and RAM are the real bottleneck for large N.

    \b
    Examples
    --------
    onmc swarm run --task "fix import A" --task "fix import B" --agent claude
    onmc swarm run --file tasks.txt --concurrency 4 --max-cost-usd 5.00
    onmc swarm run --task "lint check" --agent codex --no-isolate --json
    """
    from oh_no_my_claudecode.swarm.models import SwarmConfig, SwarmUnit
    from oh_no_my_claudecode.swarm.orchestrator import run_swarm

    # Resolve task list.
    tasks: list[str] = []
    if task is not None and file is not None:
        raise typer.Exit(code=_fatal("Provide either --task or --file, not both."))
    if file is not None:
        if not file.exists():
            raise typer.Exit(code=_fatal(f"File not found: {file}"))
        tasks = [ln.strip() for ln in file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    elif task is not None:
        tasks = list(task)
    else:
        raise typer.Exit(code=_fatal("Provide at least one --task or a --file."))

    if not tasks:
        raise typer.Exit(code=_fatal("Task list is empty."))

    if agent not in {"claude", "codex", "opencode"}:
        raise typer.Exit(
            code=_fatal(f"Unknown agent {agent!r}. Choose 'claude', 'codex', or 'opencode'.")
        )

    from oh_no_my_claudecode.swarm.models import _default_concurrency

    cfg = SwarmConfig(
        concurrency=concurrency if concurrency is not None else _default_concurrency(),
        agent=agent,
        max_iterations=per_unit_max_iterations or 10,
        max_cost_usd=None,  # per-unit cost cap (not set via CLI here)
        swarm_max_cost_usd=max_cost_usd,
        isolate=isolate,
    )

    units = [
        SwarmUnit(
            id=f"unit-{i:04d}",
            goal=g,
            verify_command=verify,
        )
        for i, g in enumerate(tasks)
    ]

    try:
        repo_root, _, storage = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    console.print(
        f"[bold]onmc swarm run[/bold] — {len(units)} task(s), "
        f"concurrency={cfg.concurrency}, agent={cfg.agent}"
    )
    console.print(
        "[dim]Honest: tasks are queued; at most "
        f"{cfg.concurrency} run simultaneously.[/dim]"
    )

    result = run_swarm(storage, repo_root, units, cfg)

    if json_output:
        # Serialize SwarmResult to JSON (manually, since LoopResult isn't
        # dataclass-serializable cleanly).
        import sys as _sys

        from oh_no_my_claudecode.swarm.models import SwarmUnitResult

        def _unit_to_dict(ur: SwarmUnitResult) -> dict[str, object]:
            return {
                "unit_id": ur.unit_id,
                "status": ur.status,
                "cost_usd": ur.cost_usd,
                "receipt_path": str(ur.receipt_path) if ur.receipt_path else None,
                "error": ur.error,
                "loop_result": (
                    {
                        "converged": ur.loop_result.converged,
                        "stop_reason": ur.loop_result.stop_reason,
                        "total_tokens": ur.loop_result.total_tokens,
                        "iterations": len(ur.loop_result.iterations),
                    }
                    if ur.loop_result
                    else None
                ),
            }

        payload = {
            "swarm_id": result.swarm_id,
            "stop_reason": result.stop_reason,
            "total_cost_usd": result.total_cost_usd,
            "total_tokens": result.total_tokens,
            "units_done": result.units_done,
            "units_failed": result.units_failed,
            "units_aborted": result.units_aborted,
            "unit_results": [_unit_to_dict(ur) for ur in result.unit_results],
        }
        _sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        raise typer.Exit(code=0 if result.units_failed == 0 else 1)

    # Render summary table.
    from rich.table import Table

    table = Table(title=f"Swarm {result.swarm_id[:8]} — {result.stop_reason}")
    table.add_column("Unit", style="dim")
    table.add_column("Status")
    table.add_column("Cost USD")
    table.add_column("Receipt")

    for ur in result.unit_results:
        status_style = {
            "done": "[green]done[/green]",
            "failed": "[red]failed[/red]",
            "aborted": "[yellow]aborted[/yellow]",
        }.get(ur.status, ur.status)
        receipt_short = (
            ur.receipt_path.name[:24] if ur.receipt_path else "[dim]—[/dim]"
        )
        table.add_row(
            ur.unit_id,
            status_style,
            f"${ur.cost_usd:.4f}",
            receipt_short,
        )
    console.print(table)
    console.print(
        f"[bold]Totals:[/bold] done={result.units_done}  "
        f"failed={result.units_failed}  aborted={result.units_aborted}  "
        f"cost=${result.total_cost_usd:.4f}"
    )

    raise typer.Exit(code=0 if result.units_failed == 0 else 1)


@swarm_app.command("plan")
def swarm_plan_command(
    task: Annotated[
        list[str] | None,
        typer.Option("--task", help="Goal text for one unit.  Repeat for multiple."),
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", help="Text file: one task goal per non-empty line."),
    ] = None,
    concurrency: Annotated[
        int | None,
        typer.Option(
            "--concurrency",
            min=1,
            help="Recommended fan-out width (advisory; Claude Code caps ~10 subagents).",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the plan as JSON to stdout."),
    ] = False,
) -> None:
    """Allocate an IN-SESSION (subagent) swarm — token-free fan-out.

    This does NOT spawn any process or call any model.  It allocates a swarm id
    + manifest and returns the unit list and abort-sentinel path.  Claude Code
    then fans subagents out itself (the subagents inherit the session's auth, so
    NO API key/token is needed), and reports each unit back via
    ``onmc swarm record``.  Use ``onmc swarm status/list/abort`` exactly as for
    process swarms.

    \b
    Examples
    --------
    onmc swarm plan --file tasks.txt --json
    onmc swarm plan --task "audit module A" --task "audit module B" --json
    """
    tasks: list[str] = []
    if task is not None and file is not None:
        raise typer.Exit(code=_fatal("Provide either --task or --file, not both."))
    if file is not None:
        if not file.exists():
            raise typer.Exit(code=_fatal(f"File not found: {file}"))
        tasks = [ln.strip() for ln in file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    elif task is not None:
        tasks = list(task)
    else:
        raise typer.Exit(code=_fatal("Provide at least one --task or a --file."))

    if not tasks:
        raise typer.Exit(code=_fatal("Task list is empty."))

    try:
        repo_root, _, _ = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    from oh_no_my_claudecode.swarm.inline import plan_inline_swarm

    width = concurrency if concurrency is not None else min(8, len(tasks))
    plan = plan_inline_swarm(repo_root, tasks, concurrency=width)

    if json_output:
        sys.stdout.write(json.dumps(plan, indent=2) + "\n")
        raise typer.Exit(code=0)

    console.print(
        f"[bold]onmc swarm plan[/bold] — inline swarm "
        f"[cyan]{plan['swarm_id']}[/cyan] with {len(tasks)} unit(s)"
    )
    console.print(f"[dim]recommended fan-out: {width} · abort: {plan['abort_path']}[/dim]")
    for u in plan["units"]:
        console.print(f"  [dim]{u['id']}[/dim]  {u['goal'][:80]}")
    console.print(
        "[dim]Claude Code fans subagents out (token-free); "
        "report each with `onmc swarm record`.[/dim]"
    )


@swarm_app.command("record")
def swarm_record_command(
    swarm_id: Annotated[str, typer.Argument(help="Swarm ID returned by `swarm plan`.")],
    unit_id: Annotated[str, typer.Argument(help="Unit ID (e.g. unit-0000).")],
    goal: Annotated[
        str,
        typer.Option("--goal", help="The unit's goal text (for the receipt)."),
    ],
    summary: Annotated[
        str,
        typer.Option("--summary", help="What the subagent did (recorded in the receipt)."),
    ] = "",
    verified: Annotated[
        bool,
        typer.Option(
            "--verified/--not-verified",
            help="Did the unit meet its success criteria?  Defaults to NOT verified.",
        ),
    ] = False,
    aborted: Annotated[
        bool,
        typer.Option("--aborted", help="Mark the unit as aborted (cut short)."),
    ] = False,
    cost_usd: Annotated[
        float | None,
        typer.Option("--cost-usd", min=0.0, help="Optional USD cost for this unit."),
    ] = None,
    tokens: Annotated[
        int | None,
        typer.Option("--tokens", min=0, help="Optional token count for this unit."),
    ] = None,
    files: Annotated[
        str | None,
        typer.Option("--files", help="Comma-separated list of files the unit touched."),
    ] = None,
    auto_verify: Annotated[
        bool,
        typer.Option(
            "--auto-verify",
            help=(
                "Staff-engineer mode: IGNORE --verified and set the receipt's "
                "verified flag from the REAL quality gate run in --worktree."
            ),
        ),
    ] = False,
    worktree: Annotated[
        Path | None,
        typer.Option("--worktree", help="The unit's worktree (required with --auto-verify)."),
    ] = None,
    base: Annotated[
        str,
        typer.Option("--base", help="Base ref the unit's diff is taken against."),
    ] = "main",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the recorded result as JSON."),
    ] = False,
) -> None:
    """Record one finished inline unit: write a receipt + update the manifest.

    Honest by construction: a unit is ``done`` ONLY when verified; otherwise it
    is ``failed`` (a subagent that produced nothing useful can never be a
    verified success).  The receipt is as auditable as a process unit's (git
    tree/diff SHA, hash chain, reproducibility envelope).

    Without ``--auto-verify`` the caller's ``--verified`` attestation is used
    (back-compatible).  With ``--auto-verify`` the caller's flag is IGNORED and
    the receipt's verified flag reflects the REAL gate result in ``--worktree``
    (preflight + diff): a unit that did not really build or fails the gate is
    recorded ``failed`` even if ``--verified`` was passed.

    \b
    Example
    -------
    onmc swarm record ab12cd34 unit-0000 --goal "audit A" \\
        --summary "found 2 issues, fixed both" --verified --files src/a.py
    onmc swarm record ab12cd34 unit-0000 --goal "fix X" --summary "done" \\
        --auto-verify --worktree /tmp/wt-unit-0000 --base main
    """
    try:
        repo_root, _, _ = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    from oh_no_my_claudecode.swarm.inline import record_inline_unit

    verifier: Callable[[], bool] | None = None
    if auto_verify:
        if worktree is None:
            raise typer.Exit(code=_fatal("--auto-verify requires --worktree."))
        from oh_no_my_claudecode.swarm.staff import verify_unit

        _wt = worktree

        def verifier() -> bool:
            return verify_unit(repo_root, _wt, base, unit_id=unit_id).ok

    file_list = [f.strip() for f in files.split(",") if f.strip()] if files else None
    res = record_inline_unit(
        repo_root,
        swarm_id,
        unit_id,
        goal=goal,
        summary=summary,
        verified=verified,
        aborted=aborted,
        files_touched=file_list,
        tokens=tokens,
        cost_usd=cost_usd,
        verifier=verifier,
    )

    if json_output:
        sys.stdout.write(json.dumps(res, indent=2) + "\n")
        raise typer.Exit(code=0 if res["status"] != "failed" else 1)

    color = {"done": "green", "failed": "red", "aborted": "yellow"}.get(res["status"], "white")
    console.print(
        f"[{color}]{res['status']}[/{color}] {unit_id} — receipt {Path(res['receipt_path']).name}"
    )
    raise typer.Exit(code=0 if res["status"] != "failed" else 1)


@swarm_app.command("verify")
def swarm_verify_command(
    swarm_id: Annotated[str, typer.Argument(help="Swarm ID returned by `swarm plan`.")],
    unit_id: Annotated[str, typer.Argument(help="Unit ID (e.g. unit-0000).")],
    worktree: Annotated[
        Path,
        typer.Option("--worktree", help="The unit's worktree to run the quality gate in."),
    ],
    base: Annotated[
        str,
        typer.Option("--base", help="Base ref the unit's diff is taken against."),
    ] = "main",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the verdict as JSON."),
    ] = False,
) -> None:
    """Run the HONEST per-unit quality gate in the unit's OWN worktree.

    This is the trust gate: it runs preflight (ruff/mypy/cli-ref/pytest) in
    ``--worktree`` and verifies the unit's diff is real + lawful.  A unit that
    didn't really build (empty diff) or fails the gate CANNOT pass — the command
    exits nonzero when the verdict is not ``ok``.

    \b
    Example
    -------
    onmc swarm verify ab12cd34 unit-0000 --worktree /tmp/wt-unit-0000 --base main
    """
    try:
        repo_root, _, _ = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    from oh_no_my_claudecode.swarm.staff import verify_unit

    verdict = verify_unit(repo_root, worktree, base, unit_id=unit_id)

    if json_output:
        payload = {
            "unit_id": verdict.unit_id,
            "preflight_ok": verdict.preflight_ok,
            "diff_ok": verdict.diff_ok,
            "ok": verdict.ok,
            "details": verdict.details,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        raise typer.Exit(code=0 if verdict.ok else 1)

    color = "green" if verdict.ok else "red"
    console.print(
        f"[{color}]{'verified' if verdict.ok else 'NOT verified'}[/{color}] "
        f"{unit_id} — preflight={verdict.preflight_ok} diff={verdict.diff_ok}"
    )
    for line in verdict.details:
        console.print(f"  [dim]{line}[/dim]")
    raise typer.Exit(code=0 if verdict.ok else 1)


@swarm_app.command("pr")
def swarm_pr_command(
    swarm_id: Annotated[str, typer.Argument(help="Swarm ID returned by `swarm plan`.")],
    unit_id: Annotated[str, typer.Argument(help="Unit ID (e.g. unit-0000).")],
    worktree: Annotated[
        Path,
        typer.Option("--worktree", help="The unit's worktree whose branch is pushed."),
    ],
    base: Annotated[
        str,
        typer.Option("--base", help="Base branch the PR targets."),
    ] = "main",
    title: Annotated[
        str | None,
        typer.Option("--title", help="PR title (defaults to a unit-scoped title)."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the PR result as JSON."),
    ] = False,
) -> None:
    """Open the unit's OWN pull request (push branch + ``gh pr create``).

    REFUSES an unverified unit: the unit must be recorded ``done``/verified in
    the manifest first.  PR-and-stop — this never auto-merges.

    \b
    Example
    -------
    onmc swarm pr ab12cd34 unit-0000 --worktree /tmp/wt-unit-0000 --base main
    """
    try:
        repo_root, _, _ = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    from oh_no_my_claudecode.swarm.orchestrator import swarm_state
    from oh_no_my_claudecode.swarm.staff import open_unit_pr

    state = swarm_state(repo_root, swarm_id)
    unit = state.get("units", {}).get(unit_id) if state else None
    if unit is None:
        raise typer.Exit(code=_fatal(f"Unknown unit {unit_id} in swarm {swarm_id}."))
    if not (unit.get("status") == "done" and unit.get("verified")):
        raise typer.Exit(
            code=_fatal(
                f"Refusing to open a PR: {unit_id} is not verified "
                f"(status={unit.get('status')!r}, verified={unit.get('verified')!r}). "
                "Verify it first with `onmc swarm verify` / `record --auto-verify`."
            )
        )

    result = open_unit_pr(repo_root, worktree, base, unit_id=unit_id, title=title)

    if json_output:
        payload = {
            "unit_id": result.unit_id,
            "ok": result.ok,
            "branch": result.branch,
            "pr_url": result.pr_url,
            "details": result.details,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        raise typer.Exit(code=0 if result.ok else 1)

    if result.ok:
        console.print(f"[green]PR opened[/green] {unit_id} — {result.pr_url}")
    else:
        console.print(f"[red]PR failed[/red] {unit_id}")
    for line in result.details:
        console.print(f"  [dim]{line}[/dim]")
    raise typer.Exit(code=0 if result.ok else 1)


@swarm_app.command("status")
def swarm_status_command(
    swarm_id: Annotated[
        str | None,
        typer.Argument(help="Swarm ID to inspect.  Omit to list all swarms."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit status as JSON."),
    ] = False,
) -> None:
    """Show status of a swarm or all swarms."""
    import sys as _sys

    from oh_no_my_claudecode.swarm.orchestrator import swarm_state

    try:
        repo_root, _, _ = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    state = swarm_state(repo_root, swarm_id)

    if json_output:
        _sys.stdout.write(json.dumps(state, indent=2) + "\n")
        return

    if not state:
        console.print("[dim]No swarm state found.[/dim]")
        return

    if swarm_id is not None:
        # Single swarm.
        console.print(f"[bold]Swarm:[/bold] {swarm_id}")
        console.print(f"  agent: {state.get('agent', '?')}")
        console.print(f"  stop_reason: {state.get('stop_reason', 'running')}")
        units = state.get("units", {})
        for uid, udata in units.items():
            console.print(f"  {uid}: {udata.get('status', '?')}")
    else:
        # All swarms.
        for sid, sdata in state.items():
            units = sdata.get("units", {})
            done = sum(1 for u in units.values() if u.get("status") == "done")
            console.print(
                f"[bold]{sid[:12]}[/bold]  agent={sdata.get('agent', '?')}  "
                f"done={done}/{len(units)}  "
                f"stop={sdata.get('stop_reason', 'running')}"
            )


@swarm_app.command("list")
def swarm_list_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit list as JSON."),
    ] = False,
) -> None:
    """List all known swarm runs."""
    import sys as _sys

    from oh_no_my_claudecode.swarm.orchestrator import swarm_state

    try:
        repo_root, _, _ = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    state = swarm_state(repo_root, None)

    if json_output:
        summary = {
            sid: {
                "agent": sdata.get("agent"),
                "started_at": sdata.get("started_at"),
                "stop_reason": sdata.get("stop_reason"),
                "units": len(sdata.get("units", {})),
            }
            for sid, sdata in state.items()
        }
        _sys.stdout.write(json.dumps(summary, indent=2) + "\n")
        return

    if not state:
        console.print("[dim]No swarm runs found in .onmc/swarm/[/dim]")
        return

    from rich.table import Table

    table = Table(title="onmc swarm runs")
    table.add_column("ID (truncated)")
    table.add_column("Agent")
    table.add_column("Units")
    table.add_column("Stop reason")
    table.add_column("Started at")

    for sid, sdata in state.items():
        table.add_row(
            sid[:12],
            sdata.get("agent", "?"),
            str(len(sdata.get("units", {}))),
            sdata.get("stop_reason", "running"),
            (sdata.get("started_at") or "")[:19],
        )
    console.print(table)


@swarm_app.command("abort")
def swarm_abort_command(
    swarm_id: Annotated[
        str | None,
        typer.Argument(
            help="Swarm ID to abort.  Omit when using --all."
        ),
    ] = None,
    all_swarms: Annotated[
        bool,
        typer.Option("--all", help="Abort ALL running swarms by writing a global ABORT file."),
    ] = False,
) -> None:
    """Request graceful abort of a swarm or all swarms.

    Writes an ABORT sentinel file.  Running units finish their current
    iteration then stop; queued units never start.  This is graceful —
    in-progress agent subprocesses are not forcibly killed.

    \b
    Examples
    --------
    onmc swarm abort abc123ef
    onmc swarm abort --all
    """
    from oh_no_my_claudecode.swarm.orchestrator import request_abort

    try:
        repo_root, _, _ = _service()._load_context()  # noqa: SLF001
    except FileNotFoundError as exc:
        raise typer.Exit(code=_fatal(str(exc))) from exc

    if all_swarms and swarm_id is not None:
        raise typer.Exit(code=_fatal("Provide a SWARM_ID or --all, not both."))

    if not all_swarms and swarm_id is None:
        raise typer.Exit(code=_fatal("Provide a SWARM_ID or use --all."))

    if all_swarms:
        request_abort(repo_root, swarm_id=None)
        console.print("[yellow]Global ABORT written — all running swarms will stop.[/yellow]")
    else:
        request_abort(repo_root, swarm_id=swarm_id)
        console.print(f"[yellow]ABORT written for swarm {swarm_id}.[/yellow]")
    console.print(
        "[dim]Running units finish their current iteration then stop gracefully.[/dim]"
    )


# Additive command auto-discovery: features expose ``<feat>.commands.register(app)``
# and self-register here with zero further edits to this hub. See
# ``oh_no_my_claudecode.command_registry`` and CONTRIBUTING.md. ``strict=False``
# so a duplicate-name collision is logged loudly to stderr rather than crashing a
# user's CLI; CI asserts ``detect_duplicate_commands(app) == []`` to fail the build.
register_feature_commands(app, strict=False)
