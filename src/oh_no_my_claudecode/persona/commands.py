"""CLI surface for the ``persona`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): this module exposes a top-level
``register(app)`` that the registry invokes at CLI build time, so ``onmc persona``
ships with **zero edits** to ``cli.py`` or any other shared hub.

``onmc persona`` lets users pick a personality preset that flavours how the fun
layer talks.  The active persona is persisted to
``.onmc/persona/active.json`` inside the current git repository.

Subcommands
-----------
``onmc persona list``          — print available presets + descriptions
``onmc persona set <name>``    — set the active persona
``onmc persona show``          — show the current persona + sample lines
``onmc persona say <event>``   — emit a line for an event in the active voice
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.persona.presets import (
    PRESETS,
    PersonaSpec,
    UnknownPersonaError,
    get_persona,
    line,
)

persona_app = typer.Typer(
    help=(
        "Selectable agent personality presets. "
        "Pick a voice (drill-sergeant, hype-beast, zen-master, pirate, professional) "
        "that flavours how the fun layer talks. "
        "Active persona is persisted per repository."
    ),
    no_args_is_help=True,
)

# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

_ACTIVE_FILE = Path(".onmc") / "persona" / "active.json"
_DEFAULT_PERSONA_NAME = "professional"


def _resolve_repo_root() -> Path:
    """Return the git repo root, or raise typer.Exit(1)."""
    from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root

    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        typer.echo("error: no git repository found from the current directory.", err=True)
        raise typer.Exit(code=1) from None


def _active_path(repo_root: Path) -> Path:
    return repo_root / _ACTIVE_FILE


def _load_active_name(repo_root: Path) -> str:
    """Return the active persona name, or the default when none is set."""
    path = _active_path(repo_root)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                name = data.get("name")
                if isinstance(name, str) and name in PRESETS:
                    return name
        except Exception:  # noqa: BLE001, S110 - corrupt file → use default
            pass
    return _DEFAULT_PERSONA_NAME


def _save_active_name(repo_root: Path, name: str) -> None:
    """Persist the active persona name to disk."""
    path = _active_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": name}, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@persona_app.command("list")
def list_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the preset list as JSON."),
    ] = False,
) -> None:
    """List all available personality presets.

    Shows each preset's name, tone, and description.  Use ``onmc persona set``
    to activate one.

    Examples:

        onmc persona list

        onmc persona list --json
    """
    presets = [spec.to_dict() for spec in PRESETS.values()]

    if as_json:
        typer.echo(
            json.dumps({"kind": "persona_list", "presets": presets}, indent=2)
        )
        return

    typer.echo("")
    for spec in PRESETS.values():
        typer.echo(f"  {spec.name:<20}  [{spec.tone}]  {spec.description}")
    typer.echo("")


@persona_app.command("set")
def set_command(
    name: Annotated[
        str,
        typer.Argument(
            help=(
                "Persona name to activate. "
                "Available: "
                + ", ".join(sorted(PRESETS))
                + "."
            ),
        ),
    ],
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the result as JSON."),
    ] = False,
) -> None:
    """Set the active personality preset for this repository.

    The chosen persona is persisted to ``.onmc/persona/active.json``.
    Other ``onmc persona`` subcommands and any modules that call
    ``onmc persona`` will reflect the new choice immediately.

    Examples:

        onmc persona set zen-master

        onmc persona set hype-beast --json
    """
    try:
        spec = get_persona(name)
    except UnknownPersonaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None

    repo_root = _resolve_repo_root()
    _save_active_name(repo_root, spec.name)

    if as_json:
        typer.echo(
            json.dumps(
                {"kind": "persona_set", "persona": spec.to_dict()},
                indent=2,
            )
        )
        return

    typer.echo(f"\n  Persona set to: {spec.name}  [{spec.tone}]\n")


@persona_app.command("show")
def show_command(
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the persona details as JSON."),
    ] = False,
) -> None:
    """Show the current active persona and sample lines.

    When no persona has been set, the default (``professional``) is shown.

    Examples:

        onmc persona show

        onmc persona show --json
    """
    repo_root = _resolve_repo_root()
    active_name = _load_active_name(repo_root)
    spec: PersonaSpec = get_persona(active_name)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "persona_show",
                    "persona": spec.to_dict(),
                },
                indent=2,
            )
        )
        return

    typer.echo(f"\n  Active persona : {spec.name}")
    typer.echo(f"  Tone           : {spec.tone}")
    typer.echo(f"  Description    : {spec.description}")
    typer.echo("\n  Sample lines:")
    for sample in spec.sample_lines:
        typer.echo(f"    • {sample}")
    typer.echo("")


@persona_app.command("say")
def say_command(
    event: Annotated[
        str,
        typer.Argument(
            help=(
                "Event kind to speak to. "
                "Recognised: test_pass, test_fail, pr_merged, build_pass, "
                "build_break, commit, generic. "
                "Unknown events fall through to the generic bank."
            ),
        ),
    ],
    seed: Annotated[
        int,
        typer.Option(
            "--seed",
            help=(
                "Deterministic selection seed. "
                "The same (persona, event, seed) triple always produces the same line."
            ),
        ),
    ] = 0,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the result as JSON."),
    ] = False,
) -> None:
    """Emit a line for EVENT in the active persona's voice.

    Selection is deterministic: the same persona + event + seed always
    produces the same line.  No LLM, no network, no randomness.

    Examples:

        onmc persona say test_pass

        onmc persona say pr_merged --seed 3

        onmc persona say build_break --json
    """
    repo_root = _resolve_repo_root()
    active_name = _load_active_name(repo_root)
    spec: PersonaSpec = get_persona(active_name)

    result = line(spec, event, seed=seed)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "persona_say",
                    "persona": spec.name,
                    "event": event,
                    "seed": seed,
                    "line": result,
                },
                indent=2,
            )
        )
        return

    typer.echo(f"\n  [{spec.name}]  {result}\n")


# ---------------------------------------------------------------------------
# Auto-discovery entry point
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``onmc persona`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(persona_app, name="persona")
