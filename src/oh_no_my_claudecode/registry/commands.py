"""CLI surface for the ``registry`` feature — auto-discovered.

Follows the auto-discovery convention: a top-level ``register(app)`` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time. No shared hub (``cli.py``, ``rendering/``, service
layer) is touched — rendering is inline (a local Rich table with a plain-text
fallback), mirroring ``roast``/``attest``.

Persistence: the ledger is a JSON file at ``<repo>/.onmc/registry.json`` holding
the raw attestation dicts that have been added. Reputation is *always* recomputed
from those raw attestations via the pure
:func:`oh_no_my_claudecode.registry.registry.build_registry`, so the ledger file
never drifts from the deterministic formula and the secret can change between
runs. The ``.onmc/`` state dir is git-ignored, so this ledger is local scratch —
the portable artifact remains the signed attestations themselves.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.registry.registry import (
    AgentReputation,
    Registry,
    build_registry,
    load_attestation,
    rank,
)

_LEDGER_NAME = "registry.json"


# ---------------------------------------------------------------------------
# Repo / ledger-file resolution
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Best-effort repo root; falls back to cwd when discovery is unavailable.

    Like ``attest``, the registry never *requires* an initialised onmc repo — it
    operates on attestation files and a local JSON ledger — so a discovery
    failure resolves the ledger against the current directory instead of aborting.
    """
    try:
        return discover_repo_root(Path.cwd())
    except RepoDiscoveryError:
        return Path.cwd()


def _ledger_path(repo_root: Path) -> Path:
    """Path to the persisted ledger under the repo's ``.onmc/`` state dir."""
    return repo_root / ".onmc" / _LEDGER_NAME


def _load_ledger_attestations(path: Path) -> list[dict[str, Any]]:
    """Load the raw attestation list from the ledger file (tolerant).

    A missing or malformed ledger yields an empty list — the registry then reads
    as freshly empty rather than raising.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(raw, dict):
        return []
    stored = raw.get("attestations")
    if not isinstance(stored, list):
        return []
    return [item for item in stored if isinstance(item, dict)]


def _save_ledger_attestations(path: Path, attestations: list[dict[str, Any]]) -> None:
    """Persist the raw attestation list to the ledger file (pretty JSON)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "attestations": attestations}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Rendering (inline; Rich with a plain-text fallback)
# ---------------------------------------------------------------------------


def _agent_line(rep: AgentReputation) -> str:
    """One-line summary of an agent's reputation (plain text)."""
    rate_pct = f"{rep.verified_rate * 100:.1f}%"
    return (
        f"  {rep.subject}: trust {rep.trust_score:.4f}  |  "
        f"{rep.verified}/{rep.attestations} verified ({rate_pct})  |  "
        f"{rep.distinct_goals} goals  |  {rep.invalid} invalid"
    )


def _render_rank_plain(agents: list[AgentReputation]) -> None:
    """Emit the leaderboard as plain text (no Rich dependency)."""
    if not agents:
        typer.echo(
            "\n  onmc registry — the trust ledger is empty.\n"
            "  Add attestations with `onmc registry add <attestation.json>`.\n"
        )
        return
    lines = ["", "  onmc registry — agent trust leaderboard", ""]
    lines.append(
        f"  {'#':<3} {'subject':<24} {'trust':>8} {'verified':>10} "
        f"{'rate':>7} {'goals':>6} {'invalid':>8}"
    )
    for idx, rep in enumerate(agents, start=1):
        rate_pct = f"{rep.verified_rate * 100:.0f}%"
        verified = f"{rep.verified}/{rep.attestations}"
        lines.append(
            f"  {idx:<3} {rep.subject[:24]:<24} {rep.trust_score:>8.4f} "
            f"{verified:>10} {rate_pct:>7} {rep.distinct_goals:>6} {rep.invalid:>8}"
        )
    lines.append("")
    typer.echo("\n".join(lines))


def _render_rank_rich(agents: list[AgentReputation]) -> bool:
    """Render the leaderboard as a Rich table; return False if Rich is absent."""
    try:
        from rich.console import Console
        from rich.table import Table
    except Exception:  # noqa: BLE001 - Rich is optional; fall back to plain text
        return False

    table = Table(title="onmc registry — agent trust leaderboard")
    table.add_column("#", justify="right", style="dim")
    table.add_column("subject", style="bold")
    table.add_column("trust", justify="right")
    table.add_column("verified", justify="right")
    table.add_column("rate", justify="right")
    table.add_column("goals", justify="right")
    table.add_column("invalid", justify="right")

    for idx, rep in enumerate(agents, start=1):
        trust_style = "bold green" if rep.trust_score > 0 else "dim"
        invalid_style = "red" if rep.invalid > 0 else "dim"
        rate_pct = f"{rep.verified_rate * 100:.0f}%"
        table.add_row(
            str(idx),
            rep.subject,
            f"[{trust_style}]{rep.trust_score:.4f}[/{trust_style}]",
            f"{rep.verified}/{rep.attestations}",
            rate_pct,
            str(rep.distinct_goals),
            f"[{invalid_style}]{rep.invalid}[/{invalid_style}]",
        )

    Console().print(table)
    return True


def _render_agent_plain(rep: AgentReputation, history: int) -> None:
    """Emit one agent's full reputation as plain text."""
    rate_pct = f"{rep.verified_rate * 100:.1f}%"
    lines = [
        "",
        f"  onmc registry — reputation for {rep.subject!r}",
        f"  trust score:    {rep.trust_score:.4f}",
        f"  attestations:   {rep.attestations}  (history entries: {history})",
        f"  verified:       {rep.verified}  ({rate_pct} verified-rate)",
        f"  invalid:        {rep.invalid}  (failed signature verification)",
        f"  distinct goals: {rep.distinct_goals}",
        f"  first seen:     {rep.first_seen or 'unknown'}",
        f"  last seen:      {rep.last_seen or 'unknown'}",
        "",
    ]
    typer.echo("\n".join(lines))


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``registry`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    registry_app = typer.Typer(
        no_args_is_help=True,
        help=(
            "Agent reputation trust ledger — aggregate signed attestations into "
            "a queryable, rankable track record."
        ),
    )

    @registry_app.command("add")
    def add_command(
        attestation_file: Annotated[
            str,
            typer.Argument(
                help="Path to an attestation JSON produced by `attest sign --json`."
            ),
        ],
        secret: Annotated[
            str | None,
            typer.Option(
                "--secret",
                help="Shared secret for HMAC verification (else ONMC_ATTEST_SECRET).",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the updated agent line as JSON."),
        ] = False,
    ) -> None:
        """Verify + ingest one attestation into the persisted trust ledger.

        Reads the attestation, verifies its signature (an unverifiable one is
        recorded and flagged, never counted toward trust), appends it to the
        ledger at ``.onmc/registry.json``, recomputes reputations, and prints
        the affected agent's updated line. Exits non-zero when the file cannot be
        read at all.
        """
        attestation = load_attestation(attestation_file)
        if not attestation:
            typer.echo(
                f"No readable attestation at {attestation_file!r}. "
                "Pass a JSON file produced by `onmc attest sign --json`.",
                err=True,
            )
            raise typer.Exit(code=1)

        repo_root = _repo_root()
        ledger_path = _ledger_path(repo_root)
        stored = _load_ledger_attestations(ledger_path)
        stored.append(attestation)
        _save_ledger_attestations(ledger_path, stored)

        registry = build_registry(stored, secret)
        subject = str(attestation.get("subject") or "onmc")
        rep = registry.agents.get(subject)
        if rep is None:  # pragma: no cover - subject is always ingested above
            rep = AgentReputation(subject=subject)

        if as_json:
            typer.echo(json.dumps(rep.to_dict()))
            return

        typer.echo(f"\n  Added attestation for {subject!r}.")
        typer.echo(_agent_line(rep))
        if rep.trust_score == 0 and rep.verified == 0:
            typer.echo(
                "  Note: no signature-verified work yet — trust stays 0.0 until a "
                "verified attestation is added (with the right secret).\n"
            )
        else:
            typer.echo("")

    @registry_app.command("rank")
    def rank_command(
        secret: Annotated[
            str | None,
            typer.Option(
                "--secret",
                help="Shared secret for HMAC verification (else ONMC_ATTEST_SECRET).",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the ranked leaderboard as JSON."),
        ] = False,
    ) -> None:
        """Show the trust leaderboard — agents ranked by trust score.

        Recomputes every agent's reputation from the persisted ledger and ranks
        them by ``trust_score`` (descending, stable tiebreak by subject). An
        empty ledger prints a friendly note.
        """
        repo_root = _repo_root()
        stored = _load_ledger_attestations(_ledger_path(repo_root))
        registry = build_registry(stored, secret)
        ranked = rank(registry)

        if as_json:
            typer.echo(json.dumps([rep.to_dict() for rep in ranked]))
            return
        if not _render_rank_rich(ranked):
            _render_rank_plain(ranked)

    @registry_app.command("agent")
    def agent_command(
        subject: Annotated[
            str,
            typer.Argument(help="The agent subject (identity) to look up."),
        ],
        secret: Annotated[
            str | None,
            typer.Option(
                "--secret",
                help="Shared secret for HMAC verification (else ONMC_ATTEST_SECRET).",
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option("--json", help="Emit the agent's reputation as JSON."),
        ] = False,
    ) -> None:
        """Show one agent's full reputation + its attestation history count.

        Exits non-zero when the subject has no attestations in the ledger.
        """
        repo_root = _repo_root()
        stored = _load_ledger_attestations(_ledger_path(repo_root))
        registry: Registry = build_registry(stored, secret)
        rep = registry.agents.get(subject)

        if rep is None:
            typer.echo(
                f"\n  onmc registry — no attestations recorded for {subject!r}.\n"
                "  Add some with `onmc registry add <attestation.json>`.\n",
                err=True,
            )
            raise typer.Exit(code=1)

        history = sum(
            1 for att in stored if str(att.get("subject") or "onmc") == subject
        )
        if as_json:
            typer.echo(json.dumps({**rep.to_dict(), "history": history}))
            return
        _render_agent_plain(rep, history)

    app.add_typer(registry_app, name="registry")
