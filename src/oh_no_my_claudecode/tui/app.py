"""Numbered-menu REPL brain-browser for ONMC memory curation.

Design rationale: uses rich tables + input() (a numbered-menu REPL) rather than
raw-keypress handling.  Raw single-keypress reads are fragile cross-platform
(termios/tty), break headless tests, and require no extra dependencies.  A
numbered-menu REPL gives the same interactive feel, is 100% testable by injecting
a stream of command strings, and exits cleanly on EOF or "q".

Interaction model
-----------------
- Views: m=Memories, p=Playbooks, t=Tasks, s=Status
- From Memories view: type "c <N>" to confirm memory N, "r <N>" to reject it.
- Type "q" to quit.  EOF (Ctrl-D) also exits cleanly (exit 0).
- All output goes through a provided rich.Console, so tests can capture it via
  Console(file=StringIO, force_terminal=False).

Entry point
-----------
    run_tui(service, *, input_stream=None, max_iterations=None)

- input_stream: any iterable of str (or None → sys.stdin).  Tests pass a list.
- max_iterations: optional int cap for safety in tests (None = unlimited).
- Returns normally on quit/EOF, never hangs.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.models.playbook import Playbook
from oh_no_my_claudecode.models.task import TaskRecord
from oh_no_my_claudecode.utils.text import shorten

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_DEFAULT_CONSOLE = Console()

_HELP_TEXT = (
    "[bold]Views:[/bold]  m=Memories  p=Playbooks  t=Tasks  s=Status\n"
    "[bold]Actions (Memories view):[/bold]  c <N>=confirm  r <N>=reject\n"
    "[bold]Quit:[/bold]  q  (or Ctrl-D)"
)

_VIEW_NAMES = {
    "m": "memories",
    "p": "playbooks",
    "t": "tasks",
    "s": "status",
}


def run_tui(
    service: OnmcService,
    *,
    console: Console | None = None,
    input_stream: Iterable[str] | None = None,
    max_iterations: int | None = None,
) -> None:
    """Run the interactive brain-browser REPL.

    Parameters
    ----------
    service:
        Initialised ``OnmcService`` instance.
    console:
        rich Console to render to.  Defaults to a stdout Console.
        Pass ``Console(file=StringIO(), force_terminal=False)`` for tests.
    input_stream:
        Iterable of command strings.  ``None`` → reads from ``sys.stdin``.
        Tests pass a ``list[str]`` to drive the session headlessly.
    max_iterations:
        Safety cap on the number of REPL loops.  ``None`` = unlimited.
    """
    con = console or _DEFAULT_CONSOLE
    itr: Iterator[str] = _make_iterator(input_stream)

    _render_banner(con)
    _render_help(con)

    current_view = "memories"
    memories: list[MemoryEntry] = []
    iteration = 0

    while True:
        if max_iterations is not None and iteration >= max_iterations:
            break
        iteration += 1

        # Refresh the current view's data each loop so confirm/reject updates show.
        if current_view == "memories":
            try:
                memories = service.list_memories()
            except Exception:  # noqa: BLE001
                memories = []
            _render_memories(con, memories)
        elif current_view == "playbooks":
            try:
                playbooks = service.list_playbooks()
            except Exception:  # noqa: BLE001
                playbooks = []
            _render_playbooks(con, playbooks)
        elif current_view == "tasks":
            try:
                tasks = service.list_tasks()
            except Exception:  # noqa: BLE001
                tasks = []
            _render_tasks(con, tasks)
        elif current_view == "status":
            try:
                status_data = service.status()
            except Exception:  # noqa: BLE001
                status_data = {}
            _render_status(con, status_data)

        # Prompt for next command.
        con.print("[dim]onmc tui>[/dim] ", end="")

        try:
            raw = next(itr)
        except StopIteration:
            # EOF on injected stream or stdin — exit cleanly.
            con.print("")
            break

        cmd = raw.strip()
        if not cmd:
            continue

        if cmd == "q":
            con.print("[dim]Goodbye.[/dim]")
            break

        if cmd == "?":
            _render_help(con)
            continue

        # View switches.
        if cmd in _VIEW_NAMES:
            current_view = _VIEW_NAMES[cmd]
            continue

        # Actions: c <N> or r <N> (only valid in memories view).
        parts = cmd.split(None, 1)
        if len(parts) == 2 and parts[0] in ("c", "r") and current_view == "memories":
            _handle_feedback(con, service, memories, action=parts[0], arg=parts[1])
            continue

        con.print(f"[yellow]Unknown command: {cmd!r}  (type ? for help)[/yellow]")


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def _make_iterator(input_stream: Iterable[str] | None) -> Iterator[str]:
    """Return an iterator over command strings.

    When ``input_stream`` is ``None``, reads lines from ``sys.stdin``.
    Handles EOF gracefully by raising ``StopIteration``.
    """
    if input_stream is not None:
        return iter(input_stream)
    return _stdin_lines()


def _stdin_lines() -> Iterator[str]:
    """Yield lines from stdin, stopping cleanly on EOF."""
    try:
        yield from sys.stdin
    except (EOFError, KeyboardInterrupt):
        return


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _render_banner(con: Console) -> None:
    con.print(Panel.fit("[bold]ONMC Brain Browser[/bold]", subtitle="onmc tui"))


def _render_help(con: Console) -> None:
    con.print(_HELP_TEXT)


def _render_memories(con: Console, memories: list[MemoryEntry]) -> None:
    if not memories:
        con.print("[yellow]No memories stored. Run `onmc ingest` first.[/yellow]")
        return
    table = Table(title=f"Memories ({len(memories)})", show_lines=False)
    table.add_column("#", width=3, justify="right", no_wrap=True)
    table.add_column("", width=2, no_wrap=True)
    table.add_column("Kind", width=16, no_wrap=True)
    table.add_column("Title", min_width=24, no_wrap=False)
    table.add_column("Staleness", width=11, no_wrap=True)
    table.add_column("Feedback", width=8, justify="right", no_wrap=True)
    for idx, mem in enumerate(memories, 1):
        feedback_indicator = _feedback_indicator(mem.feedback_score)
        staleness = mem.staleness or "—"
        staleness_style = _staleness_style(staleness)
        table.add_row(
            str(idx),
            feedback_indicator,
            mem.kind.value,
            shorten(mem.title, max_length=40),
            f"[{staleness_style}]{staleness}[/{staleness_style}]",
            f"{mem.feedback_score:+.2f}",
        )
    con.print(table)


def _render_playbooks(con: Console, playbooks: list[Playbook]) -> None:
    if not playbooks:
        con.print(
            "[yellow]No playbooks found. Run `onmc playbook generate` first.[/yellow]"
        )
        return
    table = Table(title=f"Playbooks ({len(playbooks)})", show_lines=False)
    table.add_column("#", width=3, justify="right", no_wrap=True)
    table.add_column("Title", min_width=32, no_wrap=False)
    table.add_column("Steps", width=5, justify="right", no_wrap=True)
    table.add_column("Conf", width=5, justify="right", no_wrap=True)
    for idx, pb in enumerate(playbooks, 1):
        table.add_row(
            str(idx),
            shorten(pb.title, max_length=44),
            str(len(pb.steps)),
            f"{pb.confidence:.2f}",
        )
    con.print(table)


def _render_tasks(con: Console, tasks: list[TaskRecord]) -> None:
    if not tasks:
        con.print("[yellow]No tasks found for this repository.[/yellow]")
        return
    table = Table(title=f"Tasks ({len(tasks)})", show_lines=False)
    table.add_column("#", width=3, justify="right", no_wrap=True)
    table.add_column("Status", width=10, no_wrap=True)
    table.add_column("Title", min_width=32, no_wrap=False)
    table.add_column("Branch", width=20, no_wrap=True, style="dim")
    for idx, task in enumerate(tasks, 1):
        status_label = _task_status_label(task.status.value)
        table.add_row(
            str(idx),
            status_label,
            shorten(task.title, max_length=44),
            task.branch,
        )
    con.print(table)


def _render_status(con: Console, status_data: dict[str, str]) -> None:
    table = Table(title="ONMC Status", show_lines=False)
    table.add_column("Field", no_wrap=True)
    table.add_column("Value", no_wrap=False)
    for key, value in status_data.items():
        table.add_row(key, value)
    con.print(table)


# ---------------------------------------------------------------------------
# Action handler
# ---------------------------------------------------------------------------


def _handle_feedback(
    con: Console,
    service: OnmcService,
    memories: list[MemoryEntry],
    *,
    action: str,
    arg: str,
) -> None:
    try:
        idx = int(arg.strip())
    except ValueError:
        con.print(f"[red]Expected a number, got: {arg!r}[/red]")
        return

    if idx < 1 or idx > len(memories):
        con.print(f"[red]No memory #{idx}. Choose 1–{len(memories)}.[/red]")
        return

    memory = memories[idx - 1]
    try:
        if action == "c":
            updated = service.confirm_memory(memory.id)
            con.print(
                f"[green]Confirmed[/green] [{memory.kind.value}] "
                f"[bold]{shorten(memory.title, max_length=44)}[/bold]  "
                f"feedback={updated.feedback_score:+.2f}"
            )
        else:
            updated = service.reject_memory(memory.id)
            con.print(
                f"[red]Rejected[/red] [{memory.kind.value}] "
                f"[bold]{shorten(memory.title, max_length=44)}[/bold]  "
                f"feedback={updated.feedback_score:+.2f}"
            )
    except LookupError as exc:
        con.print(f"[red]{exc}[/red]")


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------


def _feedback_indicator(score: float) -> str:
    if score > 0:
        return "[green]✓[/green]"
    if score < 0:
        return "[red]✗[/red]"
    return ""


def _staleness_style(staleness: str) -> str:
    styles = {
        "fresh": "green",
        "stale": "yellow",
        "orphaned": "red",
        "unanchored": "dim",
    }
    return styles.get(staleness, "dim")


def _task_status_label(status: str) -> str:
    styles = {
        "open": "[white]open[/white]",
        "active": "[green]active[/green]",
        "blocked": "[yellow]blocked[/yellow]",
        "solved": "[blue]solved[/blue]",
        "abandoned": "[red]abandoned[/red]",
    }
    return styles.get(status, status)
