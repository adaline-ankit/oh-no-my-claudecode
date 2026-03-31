from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.llm.providers import validate_provider_api_key
from oh_no_my_claudecode.models import IngestResult, LLMProviderType, MemoryKind, SourceType
from oh_no_my_claudecode.rendering.console import console
from oh_no_my_claudecode.setup.detector import EnvironmentDetection, detect_environment

DEFAULT_MODEL = "claude-sonnet-4-5"


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
    _render_detection(detection)
    service.init_project()
    provider_name: str | None = None
    model_name: str | None = None
    if not no_llm:
        provider_name, model_name = _provider_phase(service, yes=yes)
    ingest_result = _scan_phase(service, yes=yes, no_llm=no_llm)
    if should_seed_interactively(ingest_result.memory_count, yes=yes):
        seeded = interactive_seed(console, service)
        ingest_result.memory_count += seeded
    claude_md_generated = _claude_md_phase(service, yes=yes, no_llm=no_llm)
    hooks_installed, mcp_registered, auto_sync_enabled = _integration_phase(
        service,
        detection=detection,
        yes=yes,
    )
    _render_summary(
        detection,
        ingest_result.memory_count,
        claude_md_generated=claude_md_generated,
        hooks_installed=hooks_installed,
        mcp_registered=mcp_registered,
        auto_sync_enabled=auto_sync_enabled,
    )
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


def _render_banner() -> None:
    console.print(
        Panel.fit(
            "╔═══════════════════════════════════════════════════════╗\n"
            "║           oh-no-my-claudecode  (onmc)                ║\n"
            "║      repo-native memory for AI coding agents         ║\n"
            "╚═══════════════════════════════════════════════════════╝",
            border_style="cyan",
        )
    )


def _render_detection(detection: EnvironmentDetection) -> None:
    console.print(
        f"  Detected: git repo · {detection.commit_count} commits · "
        f"{detection.project_type} · "
        f"{'docs/ present' if detection.doc_count else 'no docs/'}"
    )


def _provider_phase(service: OnmcService, *, yes: bool) -> tuple[str | None, str | None]:
    _, status = service.llm_status()
    if status.configured:
        console.print(
            Panel.fit(
                f"Provider already configured: {status.provider.value if status.provider else '-'} "
                f"({status.model or '-'})",
                title="LLM Provider",
            )
        )
        return (
            status.provider.value if status.provider else None,
            status.model,
        )
    console.print(
        Panel.fit(
            "ONMC uses an LLM to extract knowledge from your repo. "
            "The core workflow works without one, but intelligence extraction requires a provider.",
            title="LLM Provider",
        )
    )
    provider = "skip" if not yes else "anthropic"
    if not yes:
        provider = Prompt.ask(
            "Provider?",
            choices=["anthropic", "openai", "skip"],
            default="anthropic",
        )
    if provider == "skip":
        console.print("Skipping LLM setup. Continuing with heuristic-only mode.")
        return None, None
    model = DEFAULT_MODEL if provider == "anthropic" else "gpt-4.1-mini"
    if not yes:
        model = Prompt.ask("Model?", default=model)
    api_key_env_var = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    if not yes:
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
            console.print("✓ valid")
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
                "Enter the environment variable name "
                f"(for example {default}), not the key itself."
            )
            continue
        return value or default


def _looks_like_api_key(value: str) -> bool:
    """Return whether the provided value resembles a raw provider secret."""
    return len(value) > 30 and value.startswith("sk-")


def _scan_phase(service: OnmcService, *, yes: bool, no_llm: bool) -> IngestResult:
    console.print(Panel.fit("Scanning your repo", title="Repo Scan"))
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}"),
        console=console,
    ) as progress:
        commits = progress.add_task("Commits", total=100)
        files = progress.add_task("Files", total=100)
        ingest_task = progress.add_task("Hotspots", total=100)
        progress.update(commits, completed=25)
        progress.update(files, completed=55)
        result = service.ingest(no_llm=no_llm)[1]
        progress.update(commits, completed=100)
        progress.update(files, completed=100)
        progress.update(ingest_task, completed=100)
    console.print(
        Panel.fit(
            "\n".join(
                [
                    "Reading commit history...",
                    f"✓ Extracted {result.memory_count} memory records",
                    f"✓ LLM-added records: {result.llm_new_memory_count}",
                    f"✓ Deduplicated overlaps: {result.llm_deduped_count}",
                    *result.notes[:4],
                ]
            ),
            title="Extracting repo knowledge",
        )
    )
    return result


def should_seed_interactively(memory_count: int, *, yes: bool) -> bool:
    """Return whether the setup wizard should offer manual memory seeding."""
    return not yes and memory_count < 5


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
                    f"{path} was manually identified as high-risk. "
                    "Understand it before editing."
                ),
                source_type=SourceType.MANUAL_SEED,
                source_ref="manual_seed:setup",
                confidence=0.9,
            )
    return 3


def _claude_md_phase(service: OnmcService, *, yes: bool, no_llm: bool) -> bool:
    generate = yes or Confirm.ask("Generate CLAUDE.md from extracted memory?", default=True)
    if not generate:
        return False
    markdown = service.generate_claude_md(no_llm=no_llm)
    console.print("Writing CLAUDE.md... ✓")
    preview = "\n".join(markdown.splitlines()[:10])
    console.print(Panel.fit(Syntax(preview, "markdown", word_wrap=True), title="Preview"))
    return True


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
            "Claude Code not detected. You can integrate later:\n"
            "  onmc hooks install       -> compaction hooks\n"
            "  onmc serve --mcp         -> MCP server\n"
            "  onmc ingest --install-hook -> auto-sync"
        )
        return hooks_installed, mcp_registered, auto_sync_enabled
    console.print("Claude Code detected on this machine.")
    if yes or Confirm.ask("Install compaction hooks?", default=True):
        service.install_hooks(add_mcp_server=False)
        console.print("✓ Hooks installed -> ~/.claude/settings.json")
        hooks_installed = True
    if yes or Confirm.ask("Add ONMC as MCP server?", default=True):
        service.install_hooks(add_mcp_server=True)
        console.print("✓ MCP server registered -> ~/.claude/settings.json")
        mcp_registered = True
    if yes or Confirm.ask("Install auto-sync on commit?", default=True):
        service.install_ingest_hook()
        console.print("✓ Post-commit hook installed -> .git/hooks/post-commit")
        auto_sync_enabled = True
    return hooks_installed, mcp_registered, auto_sync_enabled


def _render_summary(
    detection: EnvironmentDetection,
    extracted_records: int,
    *,
    claude_md_generated: bool,
    hooks_installed: bool,
    mcp_registered: bool,
    auto_sync_enabled: bool,
) -> None:
    console.print(
        Panel.fit(
            "\n".join(
                [
                    (
                        "Memory store    "
                        f"{detection.commit_count} commits · {extracted_records} records extracted"
                    ),
                    (
                        "CLAUDE.md       "
                        f"{'generated and ready' if claude_md_generated else 'skipped'}"
                    ),
                    (
                        "Claude Code     "
                        f"{'hooks + MCP connected' if hooks_installed and mcp_registered else ''}"
                        f"{'' if hooks_installed and mcp_registered else 'not fully connected'}"
                    ),
                    (
                        "Auto-sync       "
                        f"{'enabled on commit' if auto_sync_enabled else 'not enabled'}"
                    ),
                    "",
                    "What just happened:",
                    "Your repo's engineering history has been extracted into structured memory.",
                    "",
                    "Next steps:",
                    '  onmc brief --task "what you\'re working on"',
                    '  onmc task start --title "your current task"',
                    '  onmc teach --task "explain any part of the repo"',
                ]
            ),
            title="ONMC is ready",
        )
    )
    console.print("Share your setup: github.com/adaline-ankit/oh-no-my-claudecode")
