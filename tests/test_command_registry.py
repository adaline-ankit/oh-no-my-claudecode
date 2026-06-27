"""Tests for the additive command auto-discovery registry.

Coverage
--------
- ``register_feature_commands`` discovers the bundled ``registrydemo`` feature
  and reports it among the registered feature names.
- Registering against a fresh Typer app wires up the ``registry-demo`` command
  (invokable, exit 0, both text and ``--json`` outputs).
- A broken feature module is skipped without crashing the CLI (simulated by
  monkeypatching ``importlib.import_module`` to raise for one feature).
- Discovery + registration is idempotent — a second call against the same app
  re-registers nothing.
- The real ``onmc registry-demo`` command (already wired on the shared ``app``
  via the single discovery line in ``cli.py``) is invokable.

No Rich ``--help`` text is asserted — the CLI is exercised via flags and the
JSON / exit-code outcomes instead.
"""

from __future__ import annotations

import importlib
import json

import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app as real_app
from oh_no_my_claudecode.command_registry import register_feature_commands

runner = CliRunner()


def test_discovery_finds_demo_feature() -> None:
    """A fresh app discovers + registers the bundled demo feature by name."""
    fresh = typer.Typer()
    registered = register_feature_commands(fresh)
    assert "registrydemo" in registered


def _multi_command_app() -> typer.Typer:
    """A fresh Typer app that keeps subcommand semantics.

    Typer collapses an app holding exactly one command into a single-command CLI
    (the command becomes the program itself, with no subcommand name). The real
    ``onmc`` app has 70+ commands so this never bites it; in tests we add a
    sentinel command so the auto-discovered ``registry-demo`` is reachable as a
    proper subcommand.
    """
    fresh = typer.Typer()

    @fresh.command("__sentinel__")
    def _sentinel() -> None:  # pragma: no cover - never invoked
        ...

    return fresh


def test_demo_command_invokable_on_fresh_app() -> None:
    """The demo command is wired onto a fresh app and runs (text + JSON)."""
    fresh = _multi_command_app()
    register_feature_commands(fresh)

    text_result = runner.invoke(fresh, ["registry-demo"])
    assert text_result.exit_code == 0
    assert "self-registered" in text_result.stdout

    json_result = runner.invoke(fresh, ["registry-demo", "--json"])
    assert json_result.exit_code == 0
    payload = json.loads(json_result.stdout)
    assert payload["feature"] == "registrydemo"


def test_broken_feature_is_skipped(monkeypatch: object) -> None:
    """A feature whose import raises is skipped without crashing discovery."""
    real_import = importlib.import_module

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name.endswith("registrydemo.commands"):
            raise RuntimeError("simulated broken feature")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(  # type: ignore[attr-defined]
        importlib, "import_module", fake_import
    )

    fresh = typer.Typer()  # fresh app — per-app idempotency guard starts empty
    registered = register_feature_commands(fresh)  # must not raise
    assert "registrydemo" not in registered


def test_idempotent() -> None:
    """A second call against the same app registers nothing new."""
    fresh = typer.Typer()

    first = register_feature_commands(fresh)
    assert "registrydemo" in first

    second = register_feature_commands(fresh)
    assert "registrydemo" not in second


def test_real_app_has_registry_demo() -> None:
    """The single discovery line in cli.py wired the demo onto the real app."""
    result = runner.invoke(real_app, ["registry-demo", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["feature"] == "registrydemo"
