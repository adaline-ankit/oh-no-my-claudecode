"""Pure, testable readers + renderers for the ``onmc missioncontrol`` dashboard.

Mission Control is a **read-only** live status view over a swarm's on-disk
state.  It reads exactly what the swarm orchestrator writes and NEVER mutates
it:

- ``.onmc/swarm/<id>/manifest.json`` — the per-unit status ledger
  (``status``/``verified``/``receipt_path``/``error``/``cost_usd`` per unit,
  written by :mod:`oh_no_my_claudecode.swarm.inline` /
  :mod:`~oh_no_my_claudecode.swarm.orchestrator`).
- ``.agent-memory/receipts/run-*.json`` — the tamper-evident receipt each unit
  points at via ``receipt_path`` (carries ``verified`` + ``diff_sha``).
- ``.onmc/swarm/<id>/ABORT`` — the abort sentinel (kill-switch).

The module deliberately re-derives paths through
:func:`oh_no_my_claudecode.swarm.orchestrator._swarm_dir` /
``_abort_path`` so it stays in lock-step with the writer.  All functions here
are side-effect free apart from reading files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from oh_no_my_claudecode.swarm.orchestrator import _abort_path, _swarm_dir

if TYPE_CHECKING:
    from rich.console import Console

# Canonical unit lifecycle states surfaced by the dashboard.  ``pending`` and
# ``queued`` are pre-run; ``running`` is in-flight; ``done``/``failed``/
# ``aborted`` are terminal.  Anything the manifest reports outside this set is
# passed through verbatim so a future writer state never gets silently dropped.
_KNOWN_STATES = ("pending", "queued", "running", "done", "failed", "aborted")


@dataclass
class UnitStatus:
    """Read-only status snapshot for one swarm unit.

    Parameters
    ----------
    unit_id:
        The unit key from the manifest (e.g. ``"unit-0000"``).
    goal:
        Truncated goal text as stored in the manifest.
    state:
        Lifecycle state string (see :data:`_KNOWN_STATES`).
    verified:
        The unit's ``verified`` flag from the manifest (``None`` until recorded).
    has_receipt:
        True when the manifest points at a receipt file that exists on disk.
    diff_sha:
        The receipt's ``diff_sha`` when a receipt was read; ``None`` otherwise.
    cost_usd:
        Cost recorded for the unit (0.0 when unknown).
    error:
        Error message for a failed unit; ``None`` otherwise.
    receipt_path:
        The receipt path recorded in the manifest (may be missing on disk).
    """

    unit_id: str
    goal: str
    state: str
    verified: bool | None
    has_receipt: bool
    diff_sha: str | None
    cost_usd: float
    error: str | None
    receipt_path: str | None


@dataclass
class DashboardModel:
    """Aggregated read-only view of a single swarm.

    ``exists`` is False (and ``units`` empty) when no manifest was found for the
    requested swarm id — callers render a graceful "not found" message.
    """

    swarm_id: str
    exists: bool
    mode: str | None = None
    agent: str | None = None
    concurrency: int | None = None
    started_at: str | None = None
    aborted: bool = False
    units: list[UnitStatus] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.units)

    @property
    def state_counts(self) -> dict[str, int]:
        """Return a count per lifecycle state, in :data:`_KNOWN_STATES` order.

        Unknown states (should not happen) are appended after the known ones so
        they remain visible rather than silently discarded.
        """
        counts: dict[str, int] = dict.fromkeys(_KNOWN_STATES, 0)
        for unit in self.units:
            counts[unit.state] = counts.get(unit.state, 0) + 1
        # Drop known-but-zero buckets is intentionally NOT done: callers want a
        # stable set of keys.  Preserve insertion order (known first).
        return counts

    @property
    def verified_count(self) -> int:
        return sum(1 for u in self.units if u.verified is True)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the model to a JSON-safe dict (used by ``--json``)."""
        return {
            "swarm_id": self.swarm_id,
            "exists": self.exists,
            "mode": self.mode,
            "agent": self.agent,
            "concurrency": self.concurrency,
            "started_at": self.started_at,
            "aborted": self.aborted,
            "total": self.total,
            "verified_count": self.verified_count,
            "state_counts": self.state_counts,
            "units": [
                {
                    "unit_id": u.unit_id,
                    "goal": u.goal,
                    "state": u.state,
                    "verified": u.verified,
                    "has_receipt": u.has_receipt,
                    "diff_sha": u.diff_sha,
                    "cost_usd": u.cost_usd,
                    "error": u.error,
                    "receipt_path": u.receipt_path,
                }
                for u in self.units
            ],
        }


def _safe_float(value: object, default: float = 0.0) -> float:
    """Coerce *value* to float, tolerant of corrupt/unexpected manifest data.

    Returns *default* on ``None`` or any non-numeric value so a bad ``cost_usd``
    never breaks dashboard construction (all other fields are read defensively).
    """
    if value is None:
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict[str, Any] | None:
    """Best-effort JSON read; ``None`` on any missing/malformed file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _resolve_receipt_path(state_dir: Path, receipt_path: str | None) -> Path | None:
    """Resolve a manifest ``receipt_path`` to a filesystem path.

    Receipts are written under ``.agent-memory/receipts/`` with an absolute or
    repo-relative path recorded in the manifest.  Absolute paths are used as-is;
    a relative path is resolved against the repo root (the swarm state dir's
    grandparent's parent — ``.onmc/swarm/<id>`` → repo root).
    """
    if not receipt_path:
        return None
    p = Path(receipt_path)
    if p.is_absolute():
        return p
    # state_dir == <repo>/.onmc/swarm/<id>  →  repo root is three parents up.
    repo_root = state_dir.parent.parent.parent
    return repo_root / p


def _unit_from_manifest(
    unit_id: str, raw: dict[str, Any], state_dir: Path
) -> UnitStatus:
    """Build a :class:`UnitStatus` from one manifest unit entry + its receipt."""
    receipt_path = raw.get("receipt_path")
    resolved = _resolve_receipt_path(state_dir, receipt_path)
    has_receipt = resolved is not None and resolved.exists()

    diff_sha: str | None = None
    if has_receipt and resolved is not None:
        receipt = _read_json(resolved)
        if receipt is not None:
            diff_sha = receipt.get("diff_sha")

    return UnitStatus(
        unit_id=unit_id,
        goal=str(raw.get("goal", "")),
        state=str(raw.get("status", "pending")),
        verified=raw.get("verified"),
        has_receipt=has_receipt,
        diff_sha=diff_sha,
        cost_usd=_safe_float(raw.get("cost_usd", 0.0)),
        error=raw.get("error"),
        receipt_path=receipt_path,
    )


def build_dashboard(state_dir: Path, swarm_id: str) -> DashboardModel:
    """Build a read-only :class:`DashboardModel` for one swarm.

    Parameters
    ----------
    state_dir:
        The repo's swarm base — ``<repo>/.onmc/swarm``.  Passing the base (not a
        specific swarm's dir) keeps this symmetric with :func:`list_swarm_ids`.
    swarm_id:
        The swarm to view.

    Returns
    -------
    DashboardModel
        With ``exists=False`` and no units when the manifest is missing or
        unreadable — never raises for missing state.
    """
    repo_root = state_dir.parent.parent  # <repo>/.onmc/swarm → <repo>
    swarm_dir = _swarm_dir(repo_root, swarm_id)
    manifest = _read_json(swarm_dir / "manifest.json")
    if manifest is None:
        return DashboardModel(swarm_id=swarm_id, exists=False)

    aborted = _abort_path(repo_root, swarm_id).exists()
    units_raw = manifest.get("units", {})
    units: list[UnitStatus] = []
    if isinstance(units_raw, dict):
        for unit_id in sorted(units_raw):
            entry = units_raw[unit_id]
            if isinstance(entry, dict):
                units.append(_unit_from_manifest(unit_id, entry, swarm_dir))

    return DashboardModel(
        swarm_id=str(manifest.get("swarm_id", swarm_id)),
        exists=True,
        mode=manifest.get("mode"),
        agent=manifest.get("agent"),
        concurrency=manifest.get("concurrency"),
        started_at=manifest.get("started_at"),
        aborted=aborted,
        units=units,
    )


def list_swarm_ids(state_dir: Path) -> list[str]:
    """Return sorted swarm ids that have a manifest under ``state_dir``.

    ``state_dir`` is the swarm base (``<repo>/.onmc/swarm``).  Returns an empty
    list when the base does not exist.
    """
    if not state_dir.exists() or not state_dir.is_dir():
        return []
    ids: list[str] = []
    for child in sorted(state_dir.iterdir()):
        if child.is_dir() and (child / "manifest.json").exists():
            ids.append(child.name)
    return ids


def _state_style(state: str) -> str:
    """Map a lifecycle state to a Rich style."""
    return {
        "pending": "dim",
        "queued": "cyan",
        "running": "bold yellow",
        "done": "bold green",
        "failed": "bold red",
        "aborted": "magenta",
    }.get(state, "white")


def _verified_glyph(unit: UnitStatus) -> str:
    if unit.verified is True:
        return "[green]✓[/green]"
    if unit.verified is False:
        return "[red]✗[/red]"
    return "[dim]—[/dim]"


def render_dashboard(model: DashboardModel, console: Console) -> None:
    """Render a :class:`DashboardModel` to ``console`` as a Rich table.

    Read-only presentation only — no state is touched.  A missing swarm renders
    a clear one-line message instead of a table.
    """
    from rich.table import Table

    if not model.exists:
        console.print(
            f"[yellow]No swarm found with id[/yellow] [bold]{model.swarm_id}[/bold]. "
            "Run [cyan]onmc missioncontrol --all[/cyan] to list swarms."
        )
        return

    counts = model.state_counts
    # Iterate the full count map (known states first, unknown states appended by
    # state_counts) so any unexpected lifecycle value still surfaces in the
    # summary rather than being silently dropped.
    summary = "  ".join(
        f"[{_state_style(s)}]{s}[/]: {n}" for s, n in counts.items() if n
    ) or "[dim]no units[/dim]"
    abort_note = "  [magenta]● ABORT requested[/magenta]" if model.aborted else ""

    console.print(
        f"[bold]Mission Control[/bold] — swarm [bold cyan]{model.swarm_id}[/bold cyan]  "
        f"([dim]{model.mode or '?'} · {model.agent or '?'} · "
        f"concurrency {model.concurrency if model.concurrency is not None else '?'}[/dim])"
        f"{abort_note}"
    )
    console.print(
        f"units: {model.total}   verified: {model.verified_count}/{model.total}   {summary}"
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("unit", no_wrap=True)
    table.add_column("state", no_wrap=True)
    table.add_column("verified", justify="center", no_wrap=True)
    table.add_column("receipt", justify="center", no_wrap=True)
    table.add_column("diff_sha", no_wrap=True)
    table.add_column("goal")

    for unit in model.units:
        receipt_cell = "[green]yes[/green]" if unit.has_receipt else "[dim]—[/dim]"
        diff_cell = unit.diff_sha[:12] if unit.diff_sha else "[dim]—[/dim]"
        goal = unit.goal if len(unit.goal) <= 60 else unit.goal[:57] + "..."
        if unit.state == "failed" and unit.error:
            goal = f"{goal}  [red]({unit.error[:40]})[/red]"
        table.add_row(
            unit.unit_id,
            f"[{_state_style(unit.state)}]{unit.state}[/]",
            _verified_glyph(unit),
            receipt_cell,
            diff_cell,
            goal,
        )

    console.print(table)


def render_swarm_list(ids: list[str], console: Console) -> None:
    """Render the ``--all`` swarm listing to ``console``."""
    if not ids:
        console.print("[yellow]No swarms found[/yellow] under .onmc/swarm.")
        return
    console.print(f"[bold]{len(ids)} swarm(s):[/bold]")
    for sid in ids:
        console.print(f"  [cyan]{sid}[/cyan]")
