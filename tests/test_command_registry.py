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

import contextlib
import importlib
import io
import json

import pytest
import typer
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app as real_app
from oh_no_my_claudecode.command_registry import (
    DuplicateCommandError,
    detect_duplicate_commands,
    register_feature_commands,
)

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


# --- duplicate command-name detection ------------------------------------


def _force_two_colliding_features(monkeypatch: object) -> None:
    """Make discovery yield two synthetic features that both add ``dup-cmd``.

    Neither lives in the real package (so we never ship a duplicate); we patch
    discovery + import so ``register_feature_commands`` walks two registrars that
    both register the same top-level command name.
    """
    from oh_no_my_claudecode import command_registry

    def fake_discover() -> list[str]:
        return ["feat_a", "feat_b"]

    def make_register(_feat: str) -> object:
        def register(app: typer.Typer) -> None:
            @app.command("dup-cmd")
            def _dup() -> None:  # pragma: no cover - never invoked
                ...

        return register

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        feat = name.split(".")[1]

        class _Mod:
            register = staticmethod(make_register(feat))

        return _Mod

    monkeypatch.setattr(  # type: ignore[attr-defined]
        command_registry, "_discover_feature_names", fake_discover
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        command_registry.importlib, "import_module", fake_import
    )


def test_strict_raises_on_duplicate(monkeypatch: object) -> None:
    """Two features adding the same command name raise in strict mode."""
    _force_two_colliding_features(monkeypatch)

    fresh = typer.Typer()
    with pytest.raises(DuplicateCommandError) as excinfo:
        register_feature_commands(fresh, strict=True)
    assert "dup-cmd" in str(excinfo.value)


def test_non_strict_warns_and_detects_duplicate(monkeypatch: object) -> None:
    """In non-strict mode the collision is warned to stderr and still detectable."""
    _force_two_colliding_features(monkeypatch)

    fresh = typer.Typer()
    # The project disables pytest's capture plugin, so redirect stderr explicitly.
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        register_feature_commands(fresh, strict=False)  # must not raise

    assert "dup-cmd" in err.getvalue()
    assert detect_duplicate_commands(fresh) == ["dup-cmd"]


def test_detect_duplicate_commands_on_clean_app() -> None:
    """A freshly built app with distinct names reports no duplicates."""
    fresh = typer.Typer()

    @fresh.command("alpha")
    def _alpha() -> None:  # pragma: no cover - never invoked
        ...

    @fresh.command("beta")
    def _beta() -> None:  # pragma: no cover - never invoked
        ...

    assert detect_duplicate_commands(fresh) == []


def test_real_app_has_no_duplicate_commands() -> None:
    """CI guard: the shipped ``onmc`` app has no shadowed top-level names.

    This would have caught the legacy ``pack`` shadow, where two features both
    registered ``onmc pack`` and one silently won.
    """
    assert detect_duplicate_commands(real_app) == []
