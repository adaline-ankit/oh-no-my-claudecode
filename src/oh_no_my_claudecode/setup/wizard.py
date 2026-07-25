from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress as RichProgress
from rich.progress import SpinnerColumn, TaskID, TextColumn
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.llm.providers import validate_provider_api_key
from oh_no_my_claudecode.models import IngestResult, LLMProviderType, MemoryKind, SourceType
from oh_no_my_claudecode.rendering.console import console
from oh_no_my_claudecode.setup.detector import EnvironmentDetection, detect_environment

DEFAULT_MODEL = "claude-sonnet-4-5"


def _is_interactive(yes: bool) -> bool:
    """Return True only when we have a real TTY and --yes was not passed.

    Prevents the wizard from blocking on prompts when stdin is a pipe (e.g.
    ``curl ... | bash``) or when the caller passed ``--yes`` / ``-y``.
    """
    return not yes and sys.stdin.isatty()


# ---------------------------------------------------------------------------
# Step tracker — define the ordered wizard steps once
# ---------------------------------------------------------------------------

_STEPS = [
    "Detect",
    "Provider",
    "Scan",
    "CLAUDE.md",
    "Integrate",
    "Done",
]
_TOTAL_STEPS = len(_STEPS)


def _step_header(index: int, name: str, *, done: bool = False) -> None:
    """Print a step header.  *index* is 1-based."""
    status = "[bold green]✓[/]" if done else "[bold cyan]→[/]"
    console.print(f"\n{status}  [bold cyan]Step {index}/{_TOTAL_STEPS}[/]  [bold]{name}[/]")


@dataclass(slots=True)
class SetupResult:
    repo_root: str
    extracted_records: int
    claude_md_generated: bool
    hooks_installed: bool
    mcp_registered: bool
    auto_sync_enabled: bool
    provider: str | None
    model: str | None


def run_setup_wizard(
    *,
    cwd: Path | str = ".",
    yes: bool = False,
    no_llm: bool = False,
) -> SetupResult:
    """Run the ONMC setup wizard for the current repository."""
    detection = detect_environment(cwd)
    service = OnmcService(Path(cwd))
    console.clear()
    _render_banner()

    # Step 1 — Detect
    _step_header(1, _STEPS[0])
    _render_detection(detection)
    service.init_project()
    _step_header(1, _STEPS[0], done=True)

    # Step 2 — Provider
    provider_name: str | None = None
    model_name: str | None = None
    _step_header(2, _STEPS[1])
    if not no_llm:
        provider_name, model_name = _provider_phase(service, yes=yes)
    else:
        console.print("  [dim]--no-llm: skipping provider configuration.[/dim]")
    _step_header(2, _STEPS[1], done=True)

    # Step 3 — Scan
    _step_header(3, _STEPS[2])
    ingest_result = _scan_phase(service, yes=yes, no_llm=no_llm)
    if should_seed_interactively(ingest_result.memory_count, yes=yes):
        seeded = interactive_seed(console, service)
        ingest_result.memory_count += seeded
    _step_header(3, _STEPS[2], done=True)

    # Step 4 — CLAUDE.md
    _step_header(4, _STEPS[3])
    claude_md_generated = _claude_md_phase(service, yes=yes, no_llm=no_llm)
    _step_header(4, _STEPS[3], done=True)

    # Step 5 — Integrate
    _step_header(5, _STEPS[4])
    hooks_installed, mcp_registered, auto_sync_enabled = _integration_phase(
        service,
        detection=detection,
        yes=yes,
    )
    _step_header(5, _STEPS[4], done=True)

    # First-win moment — live recall demo
    _render_first_win(service, detection)

    # Step 6 — Done
    _step_header(6, _STEPS[5])
    _render_summary(
        detection,
        ingest_result.memory_count,
        claude_md_generated=claude_md_generated,
        hooks_installed=hooks_installed,
        mcp_registered=mcp_registered,
        auto_sync_enabled=auto_sync_enabled,
    )

    # UI handoff — interactive only, never in yes/non-interactive mode
    _ui_handoff(yes=yes)

    return SetupResult(
        repo_root=detection.repo_root.as_posix(),
        extracted_records=ingest_result.memory_count,
        claude_md_generated=claude_md_generated,
        hooks_installed=hooks_installed,
        mcp_registered=mcp_registered,
        auto_sync_enabled=auto_sync_enabled,
        provider=provider_name,
        model=model_name,
    )


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

_WORDMARK_LINES = [
    (" ██████╗ ███╗   ██╗███╗   ███╗ ██████╗", "cyan"),
    ("██╔═══██╗████╗  ██║████╗ ████║██╔════╝", "cyan"),
    ("██║   ██║██╔██╗ ██║██╔████╔██║██║     ", "bright_cyan"),
    ("██║   ██║██║╚██╗██║██║╚██╔╝██║██║     ", "bright_cyan"),
    ("╚██████╔╝██║ ╚████║██║ ╚═╝ ██║╚██████╗", "magenta"),
    (" ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝ ╚═════╝", "magenta"),
]


def _render_banner() -> None:
    """Render the branded onmc splash with wordmark, tagline, and version."""
    try:
        import importlib.metadata as _meta

        version = _meta.version("oh-no-my-claudecode")
    except Exception:
        from oh_no_my_claudecode import __version__ as version

    art = Text()
    for i, (line, color) in enumerate(_WORDMARK_LINES):
        art.append(line, style=color)
        if i < len(_WORDMARK_LINES) - 1:
            art.append("\n")

    content = Text()
    content.append_text(art)
    content.append("\n\n")
    content.append("repo-native memory for AI coding agents", style="bold dim")
    content.append(f"  v{version}", style="dim")

    console.print(
        Panel(
            Align.center(content),
            border_style="cyan",
            padding=(1, 4),
        )
    )
    console.print(Rule(style="dim cyan"))


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _render_detection(detection: EnvironmentDetection) -> None:
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim")
    t.add_column()
    t.add_row("repo root", str(detection.repo_root))
    t.add_row("commits", str(detection.commit_count))
    t.add_row("project type", detection.project_type)
    t.add_row("docs", f"{detection.doc_count} found" if detection.doc_count else "none")
    t.add_row("claude code", "detected" if detection.claude_code_detected else "not found")
    console.print(t)


# ---------------------------------------------------------------------------
# Provider phase
# ---------------------------------------------------------------------------


def _provider_phase(service: OnmcService, *, yes: bool) -> tuple[str | None, str | None]:
    _, status = service.llm_status()
    if status.configured:
        console.print(
            Panel.fit(
                f"[green]Already configured:[/green]  "
                f"[bold]{status.provider.value if status.provider else '-'}[/bold]"
                f"  ({status.model or '-'})",
                title="LLM Provider",
                border_style="green",
            )
        )
        return (
            status.provider.value if status.provider else None,
            status.model,
        )
    console.print(
        Panel.fit(
            "ONMC uses an LLM to extract knowledge from your repo.\n"
            "The core workflow works without one, but intelligence extraction requires a provider.",
            title="LLM Provider",
            border_style="cyan",
        )
    )
    interactive = _is_interactive(yes)
    if interactive:
        provider = Prompt.ask(
            "Provider?",
            choices=["anthropic", "openai", "skip"],
            default="anthropic",
        )
    else:
        provider = "anthropic"
    if provider == "skip":
        console.print("  [dim]Skipping LLM setup. Continuing with heuristic-only mode.[/dim]")
        return None, None
    model = DEFAULT_MODEL if provider == "anthropic" else "gpt-4.1-mini"
    if interactive:
        model = Prompt.ask("Model?", default=model)
    api_key_env_var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    if interactive:
        api_key_env_var = _prompt_api_key_env_var_name(default=api_key_env_var)
    _, settings = service.configure_llm(
        provider=LLMProviderType(provider),
        model=model,
        api_key_env_var=api_key_env_var,
        temperature=0.0,
        max_tokens=1600,
    )
    actual_key = os.environ.get(api_key_env_var)
    if not actual_key:
        console.print(f"  [yellow]⚠  {api_key_env_var} is not set in your environment.[/yellow]")
        console.print("  Set it before running ONMC commands:")
        console.print(f"  [bold]export {api_key_env_var}=your-key-here[/bold]")
        console.print("  Continuing — you can set this later.")
    else:
        console.print(f"  Checking {api_key_env_var}... ", end="")
        valid, message = validate_provider_api_key(
            settings.provider or LLMProviderType(provider),
            actual_key,
        )
        if valid:
            console.print("[green]✓ valid[/green]")
        else:
            console.print(f"[red]✗ {message}[/red]")
    return settings.provider.value if settings.provider else None, settings.model


def _prompt_api_key_env_var_name(*, default: str) -> str:
    """Prompt for an environment variable name and reject raw API key input."""
    while True:
        value = Prompt.ask("  API key env var name", default=default).strip()
        if _looks_like_api_key(value):
            console.print("[red]⚠  That looks like an API key, not a variable name.[/red]")
            console.print(
                f"Enter the environment variable name (for example {default}), not the key itself."
            )
            continue
        return value or default


def _looks_like_api_key(value: str) -> bool:
    """Return whether the provided value resembles a raw provider secret."""
    return len(value) > 30 and value.startswith("sk-")


# ---------------------------------------------------------------------------
# Scan phase — honest progress via staged spinners
# ---------------------------------------------------------------------------


def _scan_phase(service: OnmcService, *, yes: bool, no_llm: bool) -> IngestResult:  # noqa: ARG001
    console.print(
        Panel.fit("Reading your repository history", title="Repo Scan", border_style="cyan")
    )
    # Three honest stages: the ingest call is one synchronous operation, so we
    # use a single indeterminate spinner that advances through labeled stages
    # before/after the call instead of fake bar values.
    _stages: list[tuple[str, TaskID | None]] = [
        ("Discovering commits & files", None),
        ("Extracting hotspots & patterns", None),
        ("Indexing memory records", None),
    ]
    result: IngestResult | None = None
    with RichProgress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(_stages[0][0], total=None)
        # Stage 1: pre-ingest — already running just by displaying spinner
        progress.update(task, description=_stages[1][0])
        result = service.ingest(no_llm=no_llm)[1]
        # Stage 3: post-ingest indexing
        progress.update(task, description=_stages[2][0])
        # mark complete — spinner stops
        progress.update(task, total=1, completed=1)

    assert result is not None  # noqa: S101 — kept for type narrowing
    lines = [
        f"[green]✓[/green] Extracted [bold]{result.memory_count}[/bold] memory records",
        f"[green]✓[/green] Commits analysed: [bold]{result.commit_count}[/bold]",
        f"[green]✓[/green] Files indexed: [bold]{result.repo_file_count}[/bold]",
    ]
    if result.llm_new_memory_count:
        lines.append(
            f"[green]✓[/green] LLM-enhanced records: [bold]{result.llm_new_memory_count}[/bold]"
        )
    if result.llm_deduped_count:
        lines.append(f"  [dim]Deduplicated overlaps: {result.llm_deduped_count}[/dim]")
    for note in result.notes[:4]:
        lines.append(f"  [dim]{note}[/dim]")
    console.print(
        Panel.fit(
            "\n".join(lines),
            title="Repo knowledge extracted",
            border_style="green",
        )
    )
    return result


# ---------------------------------------------------------------------------
# Interactive seed (cold-start repos)
# ---------------------------------------------------------------------------


def should_seed_interactively(memory_count: int, *, yes: bool) -> bool:
    """Return whether the setup wizard should offer manual memory seeding."""
    return _is_interactive(yes) and memory_count < 5


def interactive_seed(console: Console, service: OnmcService) -> int:
    """Ask three targeted questions and seed durable memory for cold-start repos."""
    console.print(
        Panel(
            "Your repo has limited history to extract from.\n"
            "Answer 3 quick questions to seed your memory — takes 2 minutes.",
            style="yellow",
        )
    )
    q1 = Prompt.ask(
        "\n  What is the most important rule anyone editing this codebase must know",
        default="",
    )
    if q1.strip():
        service.add_memory(
            kind=MemoryKind.INVARIANT,
            title="Manually seeded invariant",
            summary=q1.strip(),
            source_type=SourceType.MANUAL_SEED,
            source_ref="manual_seed:setup",
            confidence=0.9,
        )
    q2 = Prompt.ask(
        "\n  What is one approach that looks right but does NOT work here",
        default="",
    )
    if q2.strip():
        service.add_memory(
            kind=MemoryKind.FAILED_APPROACH,
            title="Manually seeded anti-pattern",
            summary=q2.strip(),
            source_type=SourceType.MANUAL_SEED,
            source_ref="manual_seed:setup",
            confidence=0.9,
        )
    q3 = Prompt.ask(
        (
            "\n  Which files are most dangerous to change without understanding first "
            "(comma-separated)"
        ),
        default="",
    )
    if q3.strip():
        for raw_path in q3.split(","):
            path = raw_path.strip()
            if not path:
                continue
            service.add_memory(
                kind=MemoryKind.HOTSPOT,
                title=f"Manually flagged hotspot: {path}",
                summary=(
                    f"{path} was manually identified as high-risk. Understand it before editing."
                ),
                source_type=SourceType.MANUAL_SEED,
                source_ref="manual_seed:setup",
                confidence=0.9,
            )
    return 3


# ---------------------------------------------------------------------------
# CLAUDE.md phase
# ---------------------------------------------------------------------------


def _claude_md_phase(service: OnmcService, *, yes: bool, no_llm: bool) -> bool:
    generate = not _is_interactive(yes) or Confirm.ask(
        "Generate CLAUDE.md from extracted memory?", default=True
    )
    if not generate:
        return False
    # Never clobber a user-authored CLAUDE.md: setup_claude_md generates fresh
    # only when none exists, otherwise merges (preserving user sections) and
    # backs up any non-onmc file to CLAUDE.md.onmc-backup first.
    action, backup_path = service.setup_claude_md(no_llm=no_llm)
    if action == "generated":
        console.print("  [green]✓[/green] CLAUDE.md written")
    elif action == "merged":
        backup_name = backup_path.name if backup_path else "CLAUDE.md.onmc-backup"
        console.print(
            "  [green]✓[/green] CLAUDE.md updated "
            f"[dim](your original preserved at {backup_name})[/dim]"
        )
    else:
        console.print("  [green]✓[/green] CLAUDE.md refreshed [dim](user sections preserved)[/dim]")
    return True


# ---------------------------------------------------------------------------
# Integration phase
# ---------------------------------------------------------------------------


def _integration_phase(
    service: OnmcService,
    *,
    detection: EnvironmentDetection,
    yes: bool,
) -> tuple[bool, bool, bool]:
    hooks_installed = detection.hooks_installed
    mcp_registered = detection.mcp_registered
    auto_sync_enabled = False
    if not detection.claude_code_detected:
        console.print(
            Panel.fit(
                "Claude Code not detected. You can integrate later:\n\n"
                "  [bold]onmc hooks install[/bold]        compaction hooks\n"
                "  [bold]onmc serve --mcp[/bold]          MCP server\n"
                "  [bold]onmc ingest --install-hook[/bold]  auto-sync on commit",
                title="Claude Code Integration",
                border_style="dim",
            )
        )
        return hooks_installed, mcp_registered, auto_sync_enabled
    console.print("  [green]✓[/green] Claude Code detected on this machine.")
    interactive = _is_interactive(yes)
    if not interactive or Confirm.ask("Install compaction hooks for this repo?", default=True):
        service.install_hooks(add_mcp_server=False)
        console.print("  [green]✓[/green] Hooks installed → .claude/settings.json")
        hooks_installed = True
    if not interactive or Confirm.ask("Register ONMC as a project MCP server?", default=True):
        service.install_hooks(add_mcp_server=True)
        console.print("  [green]✓[/green] MCP server registered → .mcp.json")
        mcp_registered = True
    if not interactive or Confirm.ask("Install auto-sync on commit?", default=True):
        service.install_ingest_hook()
        console.print("  [green]✓[/green] Post-commit hook installed → .git/hooks/post-commit")
        auto_sync_enabled = True
    return hooks_installed, mcp_registered, auto_sync_enabled


# ---------------------------------------------------------------------------
# First-win: live recall demo
# ---------------------------------------------------------------------------

_FIRST_WIN_QUERIES = [
    "architecture decisions and invariants",
    "hotspots and dangerous files",
    "how this project is structured",
]


def _render_first_win(service: OnmcService, detection: EnvironmentDetection) -> None:
    """Show a live recall result to demonstrate immediate value.

    Gracefully skipped if the brain is empty or any error occurs — this must
    never crash or look broken.
    """
    try:
        # Pick a query that references something concrete from the detection
        query = _FIRST_WIN_QUERIES[0]
        if detection.commit_count > 0:
            query = f"architecture decisions in {detection.project_type.lower()}"

        _, result = service.recall(query, limit=3)
        if not result.has_matches:
            return  # cold brain — skip silently

        console.print()
        console.print(
            Rule("[bold magenta]First win — your repo already knows things[/]", style="magenta")
        )

        rows: list[str] = []
        for entry in result.entries[:3]:
            provenance = f"[dim]({entry.citation})[/dim]" if entry.citation else ""
            title_line = f"[bold cyan]{entry.title}[/bold cyan]  {provenance}"
            summary_line = f"  [dim]{entry.what_happened[:120]}[/dim]"
            rows.append(f"{title_line}\n{summary_line}")

        console.print(
            Panel(
                "\n\n".join(rows),
                title="[magenta]Ask your repo anything — here's what onmc already knows[/magenta]",
                border_style="magenta",
                padding=(1, 2),
            )
        )
        console.print(f'  [dim]Query: "{query}" · {len(result.entries)} match(es)[/dim]')
    except Exception:
        # Never crash the wizard for the first-win flourish
        return


# ---------------------------------------------------------------------------
# Summary (gorgeous finish card)
# ---------------------------------------------------------------------------


def _check(flag: bool) -> str:
    return "[bold green]✓[/bold green]" if flag else "[dim]○[/dim]"


def _render_summary(
    detection: EnvironmentDetection,
    extracted_records: int,
    *,
    claude_md_generated: bool,
    hooks_installed: bool,
    mcp_registered: bool,
    auto_sync_enabled: bool,
) -> None:
    console.print()
    console.print(Rule("[bold green]ONMC is ready[/bold green]", style="green"))

    # Capability checklist
    cap_table = Table.grid(padding=(0, 2))
    cap_table.add_column(justify="center", no_wrap=True)
    cap_table.add_column()
    cap_table.add_column(style="dim")

    cap_table.add_row(
        "[bold green]✓[/bold green]",
        "Memory store",
        f"{detection.commit_count} commits · {extracted_records} records",
    )
    cap_table.add_row(
        _check(claude_md_generated),
        "CLAUDE.md",
        "generated and ready" if claude_md_generated else "skipped",
    )
    cap_table.add_row(
        _check(hooks_installed),
        "Compaction hooks",
        "installed" if hooks_installed else "not installed",
    )
    cap_table.add_row(
        _check(mcp_registered),
        "MCP server",
        "registered" if mcp_registered else "not registered",
    )
    cap_table.add_row(
        _check(auto_sync_enabled),
        "Auto-sync",
        "enabled on commit" if auto_sync_enabled else "not enabled",
    )

    # What you can do now
    cmd_table = Table.grid(padding=(0, 2))
    cmd_table.add_column(style="bold cyan", no_wrap=True)
    cmd_table.add_column(style="dim")
    cmd_table.add_row('onmc brief --task "…"', "get a contextual briefing for your next task")
    cmd_table.add_row('onmc loop --goal "…"', "run an autonomous coding loop with memory")
    cmd_table.add_row("onmc why <file>", "explain why a file is structured the way it is")
    cmd_table.add_row("onmc ui", "open your visual memory dashboard")

    content = Text()
    content.append("Setup complete\n\n", style="bold green")

    console.print(
        Panel(
            cap_table,
            title="[bold]Capabilities[/bold]",
            border_style="green",
            padding=(0, 2),
        )
    )
    console.print(
        Panel(
            cmd_table,
            title="[bold]What you can do now[/bold]",
            border_style="cyan",
            padding=(0, 2),
        )
    )
    console.print("  [dim]Share: github.com/adaline-ankit/oh-no-my-claudecode[/dim]")


# ---------------------------------------------------------------------------
# UI handoff
# ---------------------------------------------------------------------------


def _ui_handoff(*, yes: bool) -> None:
    """Offer to open the visual dashboard.

    In interactive mode (yes=False): prompt and launch non-blocking if agreed.
    In non-interactive / yes=True / CI mode: print a tip only, never launch.
    """
    if not _is_interactive(yes):
        # Non-interactive path (--yes or no TTY) — never prompt, never spawn a server.
        console.print(
            "\n  [dim]Tip: run [bold]onmc ui[/bold] to open your visual memory dashboard.[/dim]"
        )
        return

    # Interactive path
    launch = Confirm.ask("\nOpen your visual memory dashboard now?", default=False)
    if not launch:
        console.print("  [dim]Run [bold]onmc ui[/bold] when you're ready.[/dim]")
        return

    try:
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "oh_no_my_claudecode", "ui"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        console.print("  [green]✓[/green] Dashboard launched — check your browser.")
    except Exception as exc:
        console.print(f"  [yellow]Could not launch dashboard: {exc}[/yellow]")
        console.print("  Run [bold]onmc ui[/bold] manually.")
