"""Interactive paginated REPL for the onboarding tour.

Design mirrors tui/app.py:

- ``run_onboard()`` accepts an injected ``input_stream`` + ``max_iterations``
  so it is fully headless-testable without blocking on stdin.
- ``--steps`` / non-interactive callers bypass the REPL and print all stops
  sequentially, then return (used for piping, CI, and tests).
- EOF (Ctrl-D) or "q" exits cleanly (exit 0).
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from oh_no_my_claudecode.onboard.compiler import OnboardingTour, TourStop

_DEFAULT_CONSOLE = Console()

_STOP_PROMPT = (
    "[dim]onmc onboard> [enter]=next  q=quit  ?=help[/dim]"
)
_HELP_TEXT = (
    "[bold]Navigation:[/bold]  Enter or n = next stop  "
    "p = previous stop  q = quit  ? = this help"
)


def run_onboard(
    tour: OnboardingTour,
    *,
    steps: bool = False,
    console: Console | None = None,
    input_stream: Iterable[str] | None = None,
    max_iterations: int | None = None,
) -> None:
    """Display the onboarding tour.

    Parameters
    ----------
    tour:
        Compiled :class:`~oh_no_my_claudecode.onboard.compiler.OnboardingTour`.
    steps:
        When *True*, print all stops at once and return immediately (non-interactive).
    console:
        Rich Console to render to.  Defaults to a stdout Console.
        Pass ``Console(file=StringIO(), force_terminal=False)`` for tests.
    input_stream:
        Iterable of command strings for headless testing.  ``None`` reads from stdin.
    max_iterations:
        Safety cap on REPL iterations.  ``None`` = unlimited.
    """
    con = console or _DEFAULT_CONSOLE
    repo_name = tour.repo_root.split("/")[-1] or tour.repo_root

    if steps:
        _print_all_stops(con, tour, repo_name)
        return

    _interactive_tour(
        con, tour, repo_name, input_stream=input_stream, max_iterations=max_iterations
    )


# ---------------------------------------------------------------------------
# Non-interactive (--steps) mode
# ---------------------------------------------------------------------------


def _print_all_stops(con: Console, tour: OnboardingTour, repo_name: str) -> None:
    con.print(
        Panel.fit(
            f"[bold]ONMC Onboarding Tour[/bold]  —  [cyan]{repo_name}[/cyan]\n"
            f"[dim]{tour.memory_count} memories · "
            f"{tour.file_stat_count} files indexed · "
            f"{tour.playbook_count} playbooks[/dim]",
            title="onmc onboard",
        )
    )
    con.print()
    for i, stop in enumerate(tour.stops, 1):
        con.print(Rule(f"[bold]{i}. {stop.title}[/bold]", style="blue"))
        con.print()
        from rich.markdown import Markdown

        con.print(Markdown(stop.body))
        con.print()


# ---------------------------------------------------------------------------
# Interactive REPL
# ---------------------------------------------------------------------------


def _interactive_tour(
    con: Console,
    tour: OnboardingTour,
    repo_name: str,
    *,
    input_stream: Iterable[str] | None,
    max_iterations: int | None,
) -> None:
    stops = tour.stops
    if not stops:
        con.print("[yellow]No tour stops to display.[/yellow]")
        return

    itr: Iterator[str] = _make_iterator(input_stream)
    current = 0
    iteration = 0

    _render_banner(con, tour, repo_name)

    while True:
        if max_iterations is not None and iteration >= max_iterations:
            break
        iteration += 1

        _render_stop(con, stops[current], current + 1, len(stops))
        con.print(_STOP_PROMPT)

        try:
            raw = next(itr)
        except StopIteration:
            con.print()
            break

        cmd = raw.strip().lower()
        if not cmd or cmd in ("n", ""):
            # Advance to next stop.
            if current < len(stops) - 1:
                current += 1
            else:
                con.print("[green]Tour complete.[/green]  All stops covered.")
                break
        elif cmd == "q":
            con.print("[dim]Tour ended.[/dim]")
            break
        elif cmd == "p":
            if current > 0:
                current -= 1
            else:
                con.print("[yellow]Already at the first stop.[/yellow]")
        elif cmd == "?":
            con.print(_HELP_TEXT)
        else:
            con.print(f"[yellow]Unknown command: {cmd!r}  (type ? for help)[/yellow]")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_banner(con: Console, tour: OnboardingTour, repo_name: str) -> None:
    con.print(
        Panel.fit(
            f"[bold]ONMC Onboarding Tour[/bold]  —  [cyan]{repo_name}[/cyan]\n"
            f"[dim]{tour.memory_count} memories · "
            f"{tour.file_stat_count} files indexed · "
            f"{tour.playbook_count} playbooks[/dim]\n"
            f"[dim]Press Enter to advance, q to quit, ? for help.[/dim]",
            title="onmc onboard",
        )
    )
    con.print()


def _render_stop(con: Console, stop: TourStop, index: int, total: int) -> None:
    from rich.markdown import Markdown

    con.print(Rule(f"[bold]{index}/{total} — {stop.title}[/bold]", style="blue"))
    con.print()
    con.print(Markdown(stop.body))
    con.print()


# ---------------------------------------------------------------------------
# Input helpers  (mirrors tui/app.py)
# ---------------------------------------------------------------------------


def _make_iterator(input_stream: Iterable[str] | None) -> Iterator[str]:
    if input_stream is not None:
        return iter(input_stream)
    return _stdin_lines()


def _stdin_lines() -> Iterator[str]:
    try:
        yield from sys.stdin
    except (EOFError, KeyboardInterrupt):
        return
