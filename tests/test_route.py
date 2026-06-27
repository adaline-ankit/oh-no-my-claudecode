"""Tests for the deterministic ``route`` feature.

Coverage
--------
- Each rule class routes correctly: refactor/rename → cheap + max 1 iteration;
  security/architecture → strong model + nomistakes gate; test-fix → loop
  strategy; broad feature/build → swarm strategy; risky/migration → nomistakes.
- An unknown task falls back to the safe balanced default.
- Every decision carries a non-empty rationale.
- Routing is deterministic (same input → identical decision).
- The ``onmc route`` command is invokable via auto-discovery (exit 0, --json
  shape, both flags exercised).

No Rich ``--help`` text is asserted — the CLI is exercised via flags and the
JSON / exit-code outcomes instead.
"""

from __future__ import annotations

import json

import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app as real_app
from oh_no_my_claudecode.command_registry import register_feature_commands
from oh_no_my_claudecode.route import RouteDecision, route_task

runner = CliRunner()


# --------------------------------------------------------------------------- #
# Pure routing rules
# --------------------------------------------------------------------------- #
def test_refactor_routes_cheap_and_single_iteration() -> None:
    """Refactor/rename tasks get a cheap model and a single iteration."""
    decision = route_task("rename a prop across the component")
    assert decision.model_tier == "cheap"
    assert decision.max_iterations == 1
    assert decision.strategy == "single"


def test_search_routes_cheap() -> None:
    """Search/find tasks are also in the cheap class."""
    assert route_task("search the codebase for usages").model_tier == "cheap"


def test_security_routes_strong_with_nomistakes_gate() -> None:
    """Security/architecture tasks get a strong model behind the nomistakes gate."""
    decision = route_task("review the auth flow for security vulnerabilities")
    assert decision.model_tier == "strong"
    assert decision.gate == "nomistakes"


def test_architecture_routes_strong() -> None:
    """Architecture/design tasks route to the architect on a strong model."""
    decision = route_task("design the system architecture for the new service")
    assert decision.model_tier == "strong"
    assert decision.agent == "architect"


def test_testfix_routes_loop_strategy() -> None:
    """Test-fix/flaky tasks use the local loop strategy."""
    decision = route_task("fix the flaky failing test in the suite")
    assert decision.strategy == "loop"


def test_broad_feature_routes_swarm() -> None:
    """Broad feature/build tasks fan out with the swarm strategy."""
    decision = route_task("build an end-to-end feature for billing")
    assert decision.strategy == "swarm"


def test_risky_routes_nomistakes_gate() -> None:
    """Risky/migration/delete tasks are gated by nomistakes."""
    decision = route_task("write a database migration to delete old rows")
    assert decision.gate == "nomistakes"


def test_unknown_routes_safe_default() -> None:
    """An unrecognised task falls back to the balanced single-agent default."""
    decision = route_task("ponder the meaning of the universe")
    assert decision.model_tier == "balanced"
    assert decision.strategy == "single"
    assert decision.gate == "standard"
    assert decision.use_pack is None


def test_priority_risky_beats_architecture() -> None:
    """Risk signals win over architecture signals when both are present."""
    decision = route_task("design a risky production migration")
    assert decision.agent == "careful-executor"
    assert decision.gate == "nomistakes"


# --------------------------------------------------------------------------- #
# Invariants
# --------------------------------------------------------------------------- #
def test_rationale_always_non_empty() -> None:
    """Every rule class (and the default) yields a non-empty rationale."""
    tasks = [
        "rename a prop",
        "fix security vulnerability",
        "design the architecture",
        "fix the flaky test",
        "build a feature",
        "run a migration",
        "something unclassifiable",
        "",
    ]
    for task in tasks:
        assert route_task(task).rationale.strip(), f"empty rationale for {task!r}"


def test_deterministic() -> None:
    """The same task always produces an identical decision."""
    task = "implement the new search feature"
    assert route_task(task) == route_task(task)


def test_to_dict_round_trips_fields() -> None:
    """``to_dict`` exposes every dataclass field."""
    decision = route_task("rename a thing")
    payload = decision.to_dict()
    assert set(payload) == {
        "agent",
        "model_tier",
        "strategy",
        "use_pack",
        "max_iterations",
        "gate",
        "rationale",
    }
    assert isinstance(decision, RouteDecision)


# --------------------------------------------------------------------------- #
# CLI via auto-discovery
# --------------------------------------------------------------------------- #
def _multi_command_app() -> typer.Typer:
    """A fresh Typer app that keeps subcommand semantics (sentinel command)."""
    fresh = typer.Typer()

    @fresh.command("__sentinel__")
    def _sentinel() -> None:  # pragma: no cover - never invoked
        ...

    return fresh


def test_route_discovered_on_fresh_app() -> None:
    """Auto-discovery registers the ``route`` feature onto a fresh app."""
    fresh = _multi_command_app()
    registered = register_feature_commands(fresh)
    assert "route" in registered


def test_route_command_text_invokable() -> None:
    """The discovered ``route`` command runs and renders inline (exit 0)."""
    fresh = _multi_command_app()
    register_feature_commands(fresh)
    result = runner.invoke(fresh, ["route", "rename a prop"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_route_command_json_shape() -> None:
    """``--json`` emits the full decision payload."""
    fresh = _multi_command_app()
    register_feature_commands(fresh)
    result = runner.invoke(fresh, ["route", "rename a prop", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["model_tier"] == "cheap"
    assert payload["max_iterations"] == 1
    assert payload["rationale"]


def test_real_app_has_route_command() -> None:
    """The single discovery line in cli.py wired ``route`` onto the real app."""
    result = runner.invoke(real_app, ["route", "fix the flaky test", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["strategy"] == "loop"
