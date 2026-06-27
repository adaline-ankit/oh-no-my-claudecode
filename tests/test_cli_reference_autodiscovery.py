"""Tests for the auto-discovery in ``scripts/generate-cli-reference.py``.

The generator used to carry a hardcoded ``COMMANDS`` list — the last shared
"hub" that every parallel feature PR had to edit. It now introspects the fully
built Typer ``app`` instead. These tests pin the behaviour that makes that safe:

- the discovery function enumerates known top-level commands,
- it walks into sub-groups so nested subcommands (e.g. ``swarm plan``) appear,
- recently auto-discovered feature commands (e.g. ``route``, ``pack``) appear
  WITHOUT the generator being edited,
- the output is deterministic (sorted), and
- the root program is always emitted first.

We deliberately never assert on the Rich ``--help`` text — only on the command
*topology* — so these tests are immune to Typer/Rich rendering changes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate-cli-reference.py"


def _load_generator() -> ModuleType:
    """Import the hyphenated generator script as a module by file path."""
    module_name = "_genref_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _titles() -> list[str]:
    genref = _load_generator()
    return [title for title, _ in genref.discover_commands(genref.app)]


def test_root_program_emitted_first() -> None:
    genref = _load_generator()
    discovered = genref.discover_commands(genref.app)
    assert discovered[0] == ("onmc", [])


def test_args_path_matches_title() -> None:
    genref = _load_generator()
    for title, args in genref.discover_commands(genref.app):
        assert title == ("onmc " + " ".join(args)).rstrip()


def test_enumerates_known_top_level_commands() -> None:
    titles = _titles()
    # A representative spread of long-standing top-level commands.
    for name in ("init", "ingest", "brief", "recall", "swarm", "claim"):
        assert f"onmc {name}" in titles


def test_enumerates_nested_subcommand() -> None:
    # The headline win: a nested subcommand is discovered by recursing into the
    # ``swarm`` group, not by being listed by hand.
    titles = _titles()
    assert "onmc swarm" in titles
    assert "onmc swarm plan" in titles


def test_includes_recently_autodiscovered_feature_commands() -> None:
    # ``route`` and ``pack`` were added via the command-registry auto-discovery
    # (their own ``<feat>/commands.py``). They must surface in the reference
    # WITHOUT any edit to the generator — that is the property under test.
    titles = _titles()
    assert "onmc route" in titles
    assert "onmc pack" in titles


def test_deterministic_ordering() -> None:
    genref = _load_generator()
    first = genref.discover_commands(genref.app)
    second = genref.discover_commands(genref.app)
    assert first == second
    # Children are emitted in sorted order. Verify within the ``swarm`` group.
    swarm_subs = [
        title.split(" ", 2)[2]
        for title, args in first
        if len(args) == 2 and args[0] == "swarm"
    ]
    assert swarm_subs == sorted(swarm_subs)


def test_no_hardcoded_commands_list() -> None:
    # Guard against a regression that reintroduces the shared hub: the module
    # must not expose a module-level ``COMMANDS`` constant any longer.
    genref = _load_generator()
    assert not hasattr(genref, "COMMANDS")
