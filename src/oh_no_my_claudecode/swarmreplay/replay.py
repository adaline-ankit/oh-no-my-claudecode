"""Pure, testable timeline reconstruction for ``onmc swarmreplay``.

``swarmreplay`` answers "what happened, in what order, during this swarm run?"
by reading the same on-disk state Mission Control reads
(``.onmc/swarm/<id>/manifest.json`` + each unit's tamper-evident receipt at
``.agent-memory/receipts/run-*.json``) and flattening it into a single,
globally ordered list of :class:`ReplayStep` entries — one per iteration,
across all units.

This is the CLI foundation for a future UI scrubber ("time-travel" through a
swarm run), so the JSON shape (:meth:`Replay.to_dict`) is meant to be stable:
additive changes only.

Note on naming: the ``onmc replay`` command name is already taken by the
"Replay Lab" feature (:mod:`oh_no_my_claudecode.replay` — re-derives memory
recall/guard hits over a recorded trace session). This is a different feature
entirely (swarm-run timeline reconstruction from receipts), so it ships under
a distinct name, ``onmc swarmreplay``, to avoid a top-level command collision.

Design notes
------------
- **Read-only.** No swarm state is ever mutated; this module only reads
  ``manifest.json`` and receipt JSON files.
- **Pure core.** :func:`build_replay` resolves paths the same way
  :mod:`oh_no_my_claudecode.missioncontrol.dashboard` does (so behaviour stays
  in lock-step with the swarm writer) and returns a deterministic
  :class:`Replay`. No clock reads, no randomness — the same on-disk state
  always replays identically.
- **Ordering.** Units are ordered by the receipt's ``started_at`` (falling
  back to the unit id when a receipt is missing/unparsable, so unreceipted
  units still get a stable, deterministic position). Within a unit, one step
  per iteration, taken from ``iteration_hashes`` (index order == iteration
  order). A unit with no receipt or no ``iteration_hashes`` contributes zero
  steps but is not an error — the run is simply "no iterations recorded" for
  that unit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ReplayStep:
    """One reconstructed timeline step: a single iteration of a single unit.

    Fields
    ------
    index:
        0-based position in the global, cross-unit ordered timeline.
    unit_id:
        The manifest unit key (e.g. ``"unit-0000"``).
    unit_goal:
        Truncated goal text for the unit, as recorded in the manifest.
    iteration:
        1-based iteration number within the unit.
    iteration_hash:
        The hash-chain link for this iteration (from the receipt's
        ``iteration_hashes``).
    verified:
        The unit's *final* ``verified`` flag from its receipt (not per-
        iteration — receipts do not carry per-iteration verification, only a
        final chain head). ``None`` when unknown.
    wall_seconds:
        The unit's total wall-clock seconds (receipt-level, not per-
        iteration — receipts do not split wall time per iteration).
    ended_at:
        The unit's receipt ``ended_at`` timestamp (ISO-8601 string, or
        ``None`` when the receipt does not carry one).
    """

    index: int
    unit_id: str
    unit_goal: str
    iteration: int
    iteration_hash: str
    verified: bool | None
    wall_seconds: float | None
    ended_at: str | None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain JSON-safe dict — the stable UI-facing shape."""
        return {
            "index": self.index,
            "unit_id": self.unit_id,
            "unit_goal": self.unit_goal,
            "iteration": self.iteration,
            "iteration_hash": self.iteration_hash,
            "verified": self.verified,
            "wall_seconds": self.wall_seconds,
            "ended_at": self.ended_at,
        }


@dataclass
class Replay:
    """Aggregated, ordered reconstruction of one swarm run.

    ``exists`` is False (and ``steps`` empty) when no manifest was found for
    the requested swarm id — callers render a graceful "not found" message.
    """

    swarm_id: str
    exists: bool
    steps: list[ReplayStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.steps)

    def step_at(self, index: int) -> ReplayStep | None:
        """Return the step at 0-based *index*, or ``None`` if out of range."""
        if 0 <= index < len(self.steps):
            return self.steps[index]
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain JSON-safe dict (stable schema for a UI)."""
        return {
            "swarm_id": self.swarm_id,
            "exists": self.exists,
            "total": self.total,
            "steps": [s.to_dict() for s in self.steps],
            "notes": list(self.notes),
        }


def _read_json(path: Path) -> dict[str, Any] | None:
    """Best-effort JSON object read; ``None`` on any missing/malformed file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _resolve_receipt_path(state_dir: Path, receipt_path: str | None) -> Path | None:
    """Resolve a manifest ``receipt_path`` to a filesystem path.

    Mirrors :func:`oh_no_my_claudecode.missioncontrol.dashboard._resolve_receipt_path`:
    an absolute path is used as-is; a relative path is resolved against the
    repo root (``<repo>/.onmc/swarm/<id>`` → repo root is three parents up).
    """
    if not receipt_path:
        return None
    p = Path(receipt_path)
    if p.is_absolute():
        return p
    repo_root = state_dir.parent.parent.parent
    return repo_root / p


def _safe_float(value: object) -> float | None:
    """Coerce *value* to float, tolerant of missing/corrupt receipt data."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _sort_key(entry: tuple[str, dict[str, Any], dict[str, Any] | None]) -> tuple[str, str]:
    """Deterministic cross-unit ordering key: ``(started_at, unit_id)``.

    Units without a usable ``started_at`` sort first (empty string sorts
    before any real timestamp) but remain deterministically ordered relative
    to each other via the ``unit_id`` tiebreaker.
    """
    unit_id, _unit_raw, receipt = entry
    started_at = ""
    if receipt is not None:
        raw_started = receipt.get("started_at")
        if isinstance(raw_started, str):
            started_at = raw_started
    return (started_at, unit_id)


def build_replay(state_dir: Path, swarm_id: str) -> Replay:
    """Build a read-only, ordered :class:`Replay` for one swarm run.

    Parameters
    ----------
    state_dir:
        The repo's swarm base — ``<repo>/.onmc/swarm``. Passing the base (not
        a specific swarm's dir) keeps this symmetric with
        :func:`oh_no_my_claudecode.missioncontrol.dashboard.list_swarm_ids`.
    swarm_id:
        The swarm to reconstruct.

    Returns
    -------
    Replay
        With ``exists=False`` and no steps when the manifest is missing or
        unreadable — never raises for missing state. When the manifest exists
        but no unit has recorded iterations, ``exists`` is True, ``steps`` is
        empty, and a note explains why.
    """
    repo_root = state_dir.parent.parent  # <repo>/.onmc/swarm → <repo>
    swarm_dir = repo_root / ".onmc" / "swarm" / swarm_id
    manifest = _read_json(swarm_dir / "manifest.json")
    if manifest is None:
        return Replay(swarm_id=swarm_id, exists=False)

    units_raw = manifest.get("units", {})
    entries: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
    if isinstance(units_raw, dict):
        for unit_id in sorted(units_raw):
            unit_entry = units_raw[unit_id]
            if not isinstance(unit_entry, dict):
                continue
            resolved = _resolve_receipt_path(swarm_dir, unit_entry.get("receipt_path"))
            receipt = _read_json(resolved) if resolved is not None else None
            entries.append((unit_id, unit_entry, receipt))

    entries.sort(key=_sort_key)

    steps: list[ReplayStep] = []
    notes: list[str] = []
    index = 0
    for unit_id, unit_raw, receipt in entries:
        goal = str(unit_raw.get("goal", ""))
        if receipt is None:
            notes.append(f"{unit_id}: no receipt — no iterations recorded")
            continue

        hashes = receipt.get("iteration_hashes")
        if not isinstance(hashes, list) or not hashes:
            notes.append(f"{unit_id}: receipt has no iteration_hashes — no iterations recorded")
            continue

        verified = receipt.get("verified")
        verified_flag = bool(verified) if isinstance(verified, bool) else None
        wall_seconds = _safe_float(receipt.get("wall_seconds"))
        ended_at = receipt.get("ended_at")
        ended_at_str = ended_at if isinstance(ended_at, str) else None

        for i, raw_hash in enumerate(hashes):
            steps.append(
                ReplayStep(
                    index=index,
                    unit_id=unit_id,
                    unit_goal=goal,
                    iteration=i + 1,
                    iteration_hash=str(raw_hash),
                    verified=verified_flag,
                    wall_seconds=wall_seconds,
                    ended_at=ended_at_str,
                )
            )
            index += 1

    if not entries:
        notes.append("no units recorded in manifest")
    elif not steps:
        notes.append("no iterations recorded")

    resolved_swarm_id = str(manifest.get("swarm_id", swarm_id))
    return Replay(swarm_id=resolved_swarm_id, exists=True, steps=steps, notes=notes)


def render_text(replay: Replay) -> str:
    """Render a human-readable, ordered timeline as plain text.

    Deterministic given *replay* — no I/O, no clock.
    """
    if not replay.exists:
        return (
            f"No swarm found with id {replay.swarm_id}. "
            "Run `onmc missioncontrol --all` to list swarms."
        )

    lines = [f"onmc swarmreplay — swarm {replay.swarm_id} ({replay.total} step(s))", ""]
    if not replay.steps:
        for note in replay.notes:
            lines.append(f"  ({note})")
        if not replay.notes:
            lines.append("  (no iterations recorded)")
        return "\n".join(lines)

    for step in replay.steps:
        verified_glyph = "✓" if step.verified is True else ("✗" if step.verified is False else "—")
        hash_short = step.iteration_hash[:12] if step.iteration_hash else "unknown"
        lines.append(
            f"  [{step.index:>3}] {step.unit_id}  iter {step.iteration}  "
            f"hash {hash_short}  verified {verified_glyph}  {step.unit_goal}"
        )
    for note in replay.notes:
        lines.append(f"  ({note})")
    return "\n".join(lines)


def render_step_text(replay: Replay, index: int) -> str:
    """Render a single step's full detail as plain text, or a not-found message."""
    if not replay.exists:
        return (
            f"No swarm found with id {replay.swarm_id}. "
            "Run `onmc missioncontrol --all` to list swarms."
        )

    step = replay.step_at(index)
    if step is None:
        last_index = max(replay.total - 1, 0)
        return (
            f"Step {index} not found — swarm {replay.swarm_id} has "
            f"{replay.total} step(s) (0-{last_index})."
        )

    lines = [
        f"Step {step.index} — swarm {replay.swarm_id}",
        f"  unit:           {step.unit_id}",
        f"  goal:           {step.unit_goal}",
        f"  iteration:      {step.iteration}",
        f"  iteration_hash: {step.iteration_hash}",
        f"  verified:       {step.verified}",
        f"  wall_seconds:   {step.wall_seconds}",
        f"  ended_at:       {step.ended_at}",
    ]
    return "\n".join(lines)


__all__ = [
    "Replay",
    "ReplayStep",
    "build_replay",
    "render_step_text",
    "render_text",
]
