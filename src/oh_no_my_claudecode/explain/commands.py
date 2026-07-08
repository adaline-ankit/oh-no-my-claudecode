"""CLI surface for ``onmc explain`` — auto-discovered.

Follows the auto-discovery convention: a top-level :func:`register` callable
that :func:`oh_no_my_claudecode.command_registry.register_feature_commands`
invokes at CLI build time, so ``onmc explain`` ships with **zero edits** to
``cli.py`` or any other shared hub.

``onmc explain`` reads the latest (or a specified) tamper-evident run receipt
from ``.agent-memory/receipts/`` and prints a clear human verdict: whether the
run verified, why it stopped, and key accounting figures.

Examples::

    onmc explain                        # newest receipt
    onmc explain run-abc12345-def67890.json  # by path
    onmc explain abc12345               # by short hash (stem match)
    onmc explain --json                 # machine-readable envelope
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from oh_no_my_claudecode.core.repo import RepoDiscoveryError, discover_repo_root
from oh_no_my_claudecode.explain.analyze import ExplainResult, _format_cost, explain_receipt

# ---------------------------------------------------------------------------
# Receipt discovery helpers
# ---------------------------------------------------------------------------


def _receipts_dir(repo_root: Path) -> Path:
    """Return the receipts directory path (may not exist yet)."""
    return repo_root / ".agent-memory" / "receipts"


def _all_receipt_paths(receipts_dir: Path) -> list[Path]:
    """Return all ``run-*.json`` paths under *receipts_dir*, sorted by name."""
    if not (receipts_dir.exists() and receipts_dir.is_dir()):
        return []
    return sorted(
        p for p in receipts_dir.iterdir() if p.name.startswith("run-") and p.suffix == ".json"
    )


def _latest_receipt_path(receipts_dir: Path) -> Path | None:
    """Return the most-recently-modified receipt path, or ``None``."""
    paths = _all_receipt_paths(receipts_dir)
    if not paths:
        return None
    # Sort by mtime descending; fall back to name order on equal mtime.
    return max(paths, key=lambda p: (p.stat().st_mtime, p.name))


def _find_receipt_by_ref(receipts_dir: Path, ref: str) -> Path | None:
    """Find a receipt by full path, filename, or short hash (stem substring match).

    Resolution order:
    1. If *ref* is a valid absolute path pointing to a file, use it directly.
    2. If *ref* is a bare filename (no directory component) inside *receipts_dir*, use it.
    3. Otherwise, find the receipt whose filename stem contains *ref* as a substring.
       Return the lexicographically last match (most recent deterministic tie-break).
    """
    # Absolute path
    abs_ref = Path(ref)
    if abs_ref.is_absolute() and abs_ref.is_file():
        return abs_ref

    # Bare filename inside receipts_dir
    candidate = receipts_dir / ref
    if candidate.is_file():
        return candidate

    # Short hash / stem substring
    paths = _all_receipt_paths(receipts_dir)
    matches = [p for p in paths if ref in p.stem]
    if matches:
        return max(matches, key=lambda p: p.name)

    return None


def _load_receipt_json(path: Path) -> dict[str, object]:
    """Read and parse a receipt JSON file; raises ``ValueError`` on failure."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Could not read receipt file: {exc}"
        raise ValueError(msg) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Receipt is not valid JSON: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(data, dict):
        msg = "Receipt JSON is not an object."
        raise ValueError(msg)
    result: dict[str, object] = data
    return result


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _render_rich(result: ExplainResult, receipt_path: Path) -> bool:
    """Render the verdict via Rich; return False if Rich is unavailable."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except Exception:  # noqa: BLE001
        return False

    console = Console()

    # --- Header line ---
    if result.verified:
        glyph = "[bold green]✓ VERIFIED[/bold green]"
    else:
        glyph = "[bold red]✗ NOT VERIFIED[/bold red]"

    goal_display = result.goal if result.goal else "(no goal recorded)"
    header = Text.from_markup(f"{glyph}  —  {goal_display}")

    # --- Explanation panel ---
    console.print()
    console.print(Panel(result.explanation, title=header, expand=False))

    # --- Footer table ---
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("key", style="dim")
    table.add_column("value")

    table.add_row("iterations", str(result.iterations))
    table.add_row("tokens", f"{result.tokens:,}")
    table.add_row("cost", _format_cost(result.cost_usd))
    table.add_row("agent", result.agent)
    if result.ended_at:
        table.add_row("ended_at", result.ended_at)
    if result.receipt_hash_short:
        table.add_row("receipt", result.receipt_hash_short)
    table.add_row("file", str(receipt_path.name))

    console.print(table)
    console.print()
    return True


def _render_plain(result: ExplainResult, receipt_path: Path) -> None:
    """Render the verdict as plain text (no Rich dependency)."""
    typer.echo("")
    if result.verified:
        typer.echo(f"  ✓ VERIFIED  —  {result.goal or '(no goal)'}")
    else:
        typer.echo(f"  ✗ NOT VERIFIED  —  {result.goal or '(no goal)'}")
    typer.echo("")
    typer.echo(f"  {result.explanation}")
    typer.echo("")
    typer.echo(f"  iterations : {result.iterations}")
    typer.echo(f"  tokens     : {result.tokens:,}")
    typer.echo(f"  cost       : {_format_cost(result.cost_usd)}")
    typer.echo(f"  agent      : {result.agent}")
    if result.ended_at:
        typer.echo(f"  ended_at   : {result.ended_at}")
    if result.receipt_hash_short:
        typer.echo(f"  receipt    : {result.receipt_hash_short}")
    typer.echo(f"  file       : {receipt_path.name}")
    typer.echo("")


# ---------------------------------------------------------------------------
# Auto-discovery entry point
# ---------------------------------------------------------------------------


def register(app: typer.Typer) -> None:
    """Register the ``onmc explain`` command onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """

    @app.command("explain")
    def explain_command(
        receipt_ref: Annotated[
            str | None,
            typer.Argument(
                help=(
                    "Path to a receipt file, its filename, or a short hash"
                    " (substring of the filename stem). Omit to use the newest receipt."
                ),
            ),
        ] = None,
        as_json: Annotated[
            bool,
            typer.Option(
                "--json",
                help=(
                    'Emit a machine-readable JSON envelope '
                    '{"kind":"explain","verified":bool,"stop_reason":str,'
                    '"verdict":str,"explanation":str,"goal":str,"iterations":int,'
                    '"cost_usd":float|null,"tokens":int,"receipt":str}.'
                ),
            ),
        ] = False,
    ) -> None:
        """Plain-English verdict of a run receipt.

        Reads the latest (or a specified) tamper-evident receipt from
        ``.agent-memory/receipts/`` and explains what happened: whether the run
        verified, why it stopped, and key cost/token figures.

        Never calls an LLM. Never mutates any file. Safe to run at any time.

        Resolution of RECEIPT_REF (optional):
        - Full absolute path → used directly.
        - Bare filename → looked up inside ``.agent-memory/receipts/``.
        - Short hash → matches the first receipt whose stem contains the string.
        - Omitted → picks the newest receipt by modification time.

        Special stop_reasons:

        ``no-changes``:  The verify command exited 0 but the agent made NO changes
        to the working tree — a vacuous pass.  Marked NOT VERIFIED.

        ``max-iterations``:  Hit the iteration cap before converging.

        ``budget``/``cost``:  Ran out of token budget or cost limit.

        ``wall-time``:  Exceeded the maximum allowed wall-clock duration.

        ``duplicate-action``:  The agent repeated the same action — stuck in a loop.

        ``repeated-error``:  The verifier kept returning the same error output.

        ``aborted``:  Manually interrupted (Ctrl-C or signal).

        ``agent-error``:  Adapter-level error (API failure, auth problem, etc.).

        Examples:

            onmc explain

            onmc explain run-abc12345-def67890.json

            onmc explain abc12345

            onmc explain --json
        """
        # --- Discover repo root (best-effort; fall back to cwd) ---
        try:
            repo_root: Path = discover_repo_root(Path.cwd())
        except RepoDiscoveryError:
            repo_root = Path.cwd().resolve()

        receipts_dir = _receipts_dir(repo_root)

        # --- Resolve the receipt path ---
        if receipt_ref is None:
            receipt_path = _latest_receipt_path(receipts_dir)
            if receipt_path is None:
                typer.echo(
                    'No run receipts yet — run `onmc autopilot "<goal>"` first.',
                )
                raise typer.Exit(code=0)
        else:
            receipt_path = _find_receipt_by_ref(receipts_dir, receipt_ref)
            if receipt_path is None:
                typer.echo(
                    f"Receipt not found: {receipt_ref!r}",
                    err=True,
                )
                raise typer.Exit(code=1)

        # --- Load receipt ---
        try:
            receipt_data = _load_receipt_json(receipt_path)
        except ValueError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from None

        # --- Analyse ---
        result: ExplainResult = explain_receipt(receipt_data)

        # --- Emit ---
        if as_json:
            payload = result.to_dict()
            typer.echo(json.dumps(payload, indent=2))
            return

        if not _render_rich(result, receipt_path):
            _render_plain(result, receipt_path)

        # Exit 1 when the run was not verified (useful in scripts).
        if not result.verified:
            raise typer.Exit(code=1)
