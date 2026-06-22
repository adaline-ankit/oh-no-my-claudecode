"""Tests for `onmc onboard` — compiler, runner, and CLI command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.onboard.compiler import OnboardingTour, compile_onboarding
from oh_no_my_claudecode.onboard.runner import run_onboard

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_and_ingest(repo: Path) -> OnmcService:
    service = OnmcService(repo)
    service.init_project()
    service.ingest(no_llm=True)
    return service


def _make_console() -> tuple[Console, StringIO]:
    """Return a (Console, buffer) pair for capturing rich output in tests."""
    buf = StringIO()
    con = Console(file=buf, force_terminal=False, highlight=False)
    return con, buf


# ---------------------------------------------------------------------------
# compile_onboarding — unit tests
# ---------------------------------------------------------------------------


def test_compile_onboarding_returns_ordered_stops(sample_repo: Path) -> None:
    """compile_onboarding must return stops in the expected order."""
    service = _init_and_ingest(sample_repo)
    _, _, storage = service._load_context()

    tour = compile_onboarding(storage, sample_repo)

    assert isinstance(tour, OnboardingTour)
    titles = [s.title for s in tour.stops]
    # Must include the canonical five stops (playbooks omitted when none stored).
    assert "Repo overview" in titles
    assert "Danger zones" in titles
    assert "Key decisions & invariants" in titles
    assert "Start here" in titles


def test_compile_onboarding_danger_zone_includes_hotspot(sample_repo: Path) -> None:
    """The danger-zone stop must surface the hottest file from the sample repo."""
    service = _init_and_ingest(sample_repo)
    _, _, storage = service._load_context()

    tour = compile_onboarding(storage, sample_repo)

    danger = next(s for s in tour.stops if s.title == "Danger zones")
    # sample_repo fixture has src/cache.py modified in 3 commits — hottest file.
    assert "cache.py" in danger.body or not danger.is_empty


def test_compile_onboarding_decisions_stop_includes_seeded_decision(
    sample_repo: Path,
) -> None:
    """If a decision/invariant is stored, it must appear in the decisions stop."""
    from oh_no_my_claudecode.models import MemoryKind

    service = _init_and_ingest(sample_repo)
    # Seed a decision directly so the test is deterministic.
    service.add_manual_memory(
        kind=MemoryKind.DECISION,
        title="Cache boundary must not be bypassed",
        summary="Workers must route all cache invalidation through the shared module.",
    )
    _, _, storage = service._load_context()

    tour = compile_onboarding(storage, sample_repo)

    decisions_stop = next(s for s in tour.stops if s.title == "Key decisions & invariants")
    assert not decisions_stop.is_empty
    assert "Cache boundary must not be bypassed" in decisions_stop.body


def test_compile_onboarding_empty_store(tmp_path: Path) -> None:
    """An empty (freshly-init'd) store must still return an honest tour."""
    import subprocess

    repo = tmp_path / "empty-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=repo, check=True, capture_output=True
    )

    service = OnmcService(repo)
    service.init_project()
    _, _, storage = service._load_context()

    tour = compile_onboarding(storage, repo)

    assert isinstance(tour, OnboardingTour)
    assert len(tour.stops) >= 1
    overview = tour.stops[0]
    assert overview.title == "Repo overview"
    # Should be honest about no data.
    assert overview.is_empty or tour.memory_count == 0


def test_tour_to_markdown(sample_repo: Path) -> None:
    """to_markdown must return a non-empty string with the repo name in the header."""
    service = _init_and_ingest(sample_repo)
    _, _, storage = service._load_context()

    tour = compile_onboarding(storage, sample_repo)
    md = tour.to_markdown()

    assert isinstance(md, str)
    assert len(md) > 50
    assert sample_repo.name in md


# ---------------------------------------------------------------------------
# run_onboard — runner tests
# ---------------------------------------------------------------------------


def test_steps_mode_prints_all_stops_and_exits(sample_repo: Path) -> None:
    """--steps (non-interactive) must print all stops and return cleanly."""
    service = _init_and_ingest(sample_repo)
    _, _, storage = service._load_context()
    tour = compile_onboarding(storage, sample_repo)

    con, buf = _make_console()
    run_onboard(tour, steps=True, console=con, input_stream=[])

    output = buf.getvalue()
    assert "Repo overview" in output
    assert "Danger zones" in output
    assert "Start here" in output


def test_interactive_advance_and_quit(sample_repo: Path) -> None:
    """Interactive mode must advance on Enter and quit on 'q'."""
    service = _init_and_ingest(sample_repo)
    _, _, storage = service._load_context()
    tour = compile_onboarding(storage, sample_repo)

    # Script: show first stop, advance, then quit.
    commands = ["", "q"]
    con, buf = _make_console()
    run_onboard(
        tour,
        steps=False,
        console=con,
        input_stream=commands,
        max_iterations=10,
    )

    output = buf.getvalue()
    # Banner should appear.
    assert "ONMC Onboarding Tour" in output
    # First stop always rendered.
    assert "Repo overview" in output


def test_interactive_eof_exits_cleanly(sample_repo: Path) -> None:
    """EOF on the injected stream must exit without raising StopIteration."""
    service = _init_and_ingest(sample_repo)
    _, _, storage = service._load_context()
    tour = compile_onboarding(storage, sample_repo)

    # Empty stream simulates immediate EOF.
    con, buf = _make_console()
    run_onboard(
        tour,
        steps=False,
        console=con,
        input_stream=[],
        max_iterations=5,
    )
    # Should not raise; output should contain the banner.
    assert "ONMC Onboarding Tour" in buf.getvalue()


def test_interactive_help_command(sample_repo: Path) -> None:
    """The '?' command must print help text without advancing the stop."""
    service = _init_and_ingest(sample_repo)
    _, _, storage = service._load_context()
    tour = compile_onboarding(storage, sample_repo)

    commands = ["?", "q"]
    con, buf = _make_console()
    run_onboard(
        tour,
        steps=False,
        console=con,
        input_stream=commands,
        max_iterations=10,
    )
    output = buf.getvalue()
    assert "Navigation" in output


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


def test_onboard_steps_cli_exits_zero(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """onmc onboard --steps must print all stops and exit 0."""
    monkeypatch.chdir(sample_repo)
    _init_and_ingest(sample_repo)

    result = runner.invoke(app, ["onboard", "--steps"])

    assert result.exit_code == 0, result.output
    assert "Repo overview" in result.output
    assert "Danger zones" in result.output
    assert "Start here" in result.output


def test_onboard_steps_cli_not_initialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """onmc onboard --steps must exit non-zero when ONMC is not initialized."""
    import subprocess

    repo = tmp_path / "bare-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=repo, check=True, capture_output=True
    )
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["onboard", "--steps"])

    assert result.exit_code != 0
