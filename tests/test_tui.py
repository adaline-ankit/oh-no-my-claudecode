"""Tests for the onmc tui brain-browser REPL.

All tests drive ``run_tui`` with an injected input stream (list[str]) and a
``rich.Console(file=StringIO(), force_terminal=False)`` so they work without
any real TTY.  The ``sample_repo`` fixture is reused from conftest.py.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.tui import run_tui

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _console_and_buf() -> tuple[Console, StringIO]:
    """Return a (Console, StringIO) pair for capturing TUI output in tests."""
    buf = StringIO()
    con = Console(file=buf, force_terminal=False, highlight=False, markup=True)
    return con, buf


def _initialised_service(repo: Path) -> OnmcService:
    svc = OnmcService(repo)
    svc.init_project()
    return svc


# ---------------------------------------------------------------------------
# Banner / help
# ---------------------------------------------------------------------------


def test_banner_and_help_appear_on_start(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)
    con, buf = _console_and_buf()

    run_tui(svc, console=con, input_stream=["q"], max_iterations=5)

    output = buf.getvalue()
    assert "ONMC Brain Browser" in output
    assert "Memories" in output
    assert "Playbooks" in output


# ---------------------------------------------------------------------------
# View switching
# ---------------------------------------------------------------------------


def test_switch_to_playbooks_view(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)
    con, buf = _console_and_buf()

    run_tui(svc, console=con, input_stream=["p", "q"], max_iterations=5)

    output = buf.getvalue()
    # Either the "no playbooks" message or the playbooks table header
    assert "Playbooks" in output or "playbook generate" in output


def test_switch_to_tasks_view(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)
    con, buf = _console_and_buf()

    run_tui(svc, console=con, input_stream=["t", "q"], max_iterations=5)

    output = buf.getvalue()
    assert "Tasks" in output or "No tasks" in output


def test_switch_to_status_view(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)
    con, buf = _console_and_buf()

    run_tui(svc, console=con, input_stream=["s", "q"], max_iterations=5)

    output = buf.getvalue()
    assert "Status" in output or "memories" in output


def test_switch_back_to_memories_view(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)
    con, buf = _console_and_buf()

    run_tui(svc, console=con, input_stream=["p", "m", "q"], max_iterations=10)

    output = buf.getvalue()
    assert "Memories" in output


# ---------------------------------------------------------------------------
# Memory confirm / reject
# ---------------------------------------------------------------------------


def test_confirm_memory_updates_feedback_score(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)

    memory = svc.add_memory(
        kind=MemoryKind.INVARIANT,
        title="TUI test invariant",
        summary="Repository writes must go through the service layer.",
    )
    assert memory.feedback_score == 0.0

    con, buf = _console_and_buf()
    # Switch to memories view (default), confirm entry #1, then quit.
    run_tui(svc, console=con, input_stream=["m", "c 1", "q"], max_iterations=10)

    output = buf.getvalue()
    assert "Confirmed" in output

    updated = svc.get_memory(memory.id)
    assert updated is not None
    assert updated.feedback_score > 0.0


def test_reject_memory_updates_feedback_score(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)

    memory = svc.add_memory(
        kind=MemoryKind.GOTCHA,
        title="TUI test gotcha",
        summary="This approach did not work for cache invalidation.",
    )
    assert memory.feedback_score == 0.0

    con, buf = _console_and_buf()
    run_tui(svc, console=con, input_stream=["m", "r 1", "q"], max_iterations=10)

    output = buf.getvalue()
    assert "Rejected" in output

    updated = svc.get_memory(memory.id)
    assert updated is not None
    assert updated.feedback_score < 0.0


def test_confirm_and_reject_show_in_memory_list(sample_repo: Path, monkeypatch: object) -> None:
    """Feedback changes are visible in the memory table after action."""
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)

    svc.add_memory(
        kind=MemoryKind.DECISION,
        title="Cache invalidation strategy",
        summary="Invalidate on write, never on read.",
    )

    con, buf = _console_and_buf()
    # confirm #1 then switch back to memories to see indicator, then quit
    run_tui(svc, console=con, input_stream=["m", "c 1", "m", "q"], max_iterations=15)

    output = buf.getvalue()
    # The confirmed indicator should appear in the refreshed table
    assert "+0.30" in output or "Confirmed" in output


def test_confirm_out_of_range_shows_error(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)

    svc.add_memory(
        kind=MemoryKind.INVARIANT,
        title="Single memory",
        summary="Only one memory exists.",
    )

    con, buf = _console_and_buf()
    run_tui(svc, console=con, input_stream=["m", "c 99", "q"], max_iterations=10)

    output = buf.getvalue()
    assert "No memory #99" in output


def test_confirm_non_numeric_shows_error(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)

    svc.add_memory(
        kind=MemoryKind.INVARIANT,
        title="One memory",
        summary="Summary.",
    )

    con, buf = _console_and_buf()
    run_tui(svc, console=con, input_stream=["m", "c abc", "q"], max_iterations=10)

    output = buf.getvalue()
    assert "Expected a number" in output


# ---------------------------------------------------------------------------
# Not-initialized path
# ---------------------------------------------------------------------------


def test_not_initialized_raises_file_not_found(tmp_path: Path, monkeypatch: object) -> None:
    """When the repo is not initialised, _load_context raises FileNotFoundError."""
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    # tmp_path has no git repo; discover_repo_root will raise or config_exists returns False.
    # We just need run_tui itself to not hang — the CLI wraps FileNotFoundError before calling.
    # Test that a not-init'd service raises the expected error.
    import subprocess

    bare = tmp_path / "bare-repo"
    bare.mkdir()
    subprocess.run(["git", "init"], cwd=bare, capture_output=True, check=True)

    svc = OnmcService(bare)
    with pytest.raises(FileNotFoundError, match="not initialized"):
        svc.status()


# ---------------------------------------------------------------------------
# EOF / empty input exits cleanly
# ---------------------------------------------------------------------------


def test_eof_on_empty_input_exits_cleanly(sample_repo: Path, monkeypatch: object) -> None:
    """An empty input stream (immediate EOF) exits without hanging."""
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)
    con, buf = _console_and_buf()

    run_tui(svc, console=con, input_stream=[], max_iterations=5)

    # Should have printed the banner at minimum
    assert "ONMC" in buf.getvalue()


def test_immediate_quit_exits_cleanly(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)
    con, buf = _console_and_buf()

    run_tui(svc, console=con, input_stream=["q"], max_iterations=5)

    output = buf.getvalue()
    assert "Goodbye" in output


# ---------------------------------------------------------------------------
# Unknown command
# ---------------------------------------------------------------------------


def test_unknown_command_shows_help_hint(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)
    con, buf = _console_and_buf()

    run_tui(svc, console=con, input_stream=["z", "q"], max_iterations=10)

    output = buf.getvalue()
    assert "Unknown command" in output or "help" in output


# ---------------------------------------------------------------------------
# max_iterations safety cap
# ---------------------------------------------------------------------------


def test_max_iterations_cap_prevents_infinite_loop(
    sample_repo: Path, monkeypatch: object
) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)
    con, buf = _console_and_buf()

    # Feed an infinite stream; max_iterations=3 must stop it.
    import itertools

    run_tui(svc, console=con, input_stream=itertools.repeat("m"), max_iterations=3)

    # Should complete without hanging; banner should appear.
    assert "ONMC" in buf.getvalue()


# ---------------------------------------------------------------------------
# Memories view renders expected columns
# ---------------------------------------------------------------------------


def test_memories_view_shows_kind_and_title(sample_repo: Path, monkeypatch: object) -> None:
    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.chdir(sample_repo)
    svc = _initialised_service(sample_repo)

    svc.add_memory(
        kind=MemoryKind.INVARIANT,
        title="Unique invariant title for TUI test",
        summary="Summary text.",
        source_type=SourceType.MANUAL,
    )

    con, buf = _console_and_buf()
    run_tui(svc, console=con, input_stream=["m", "q"], max_iterations=5)

    output = buf.getvalue()
    assert "invariant" in output
    assert "Unique invariant title for TUI test" in output or "Unique invariant" in output
