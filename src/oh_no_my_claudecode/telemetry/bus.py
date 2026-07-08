"""Pure live event bus — append-only JSONL log of agent activity.

Design contract
---------------
- Pure and testable: ``emit``/``read_events``/``active_agents`` take injected
  paths + caller-supplied timestamps — no wallclock, no I/O other than the
  declared file.
- No new dependencies: stdlib only (``dataclasses``, ``json``, ``pathlib``).
- Atomic-ish append: ``open("a")`` + single ``write`` call; each line is one
  complete JSON object so a partial write at process death leaves all prior
  lines readable.
- Injectable ``live_dir``: callers that know the repo root pass it explicitly;
  the default is relative to process cwd for convenience only.

Event kinds (open-ended; add new ones without breaking existing consumers)
-------------------------------------------------------------------------
``swarm_planned``     — a new inline swarm was planned.
``unit_queued``       — a swarm unit was enqueued (pending).
``unit_done``         — a swarm unit completed successfully.
``unit_failed``       — a swarm unit completed with a failure.
``unit_aborted``      — a swarm unit was aborted.
``tool_call``         — a PostToolUse hook fired (tool name + brief target).
``subagent_stop``     — a SubagentStop or Stop hook fired.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

LIVE_DIR_DEFAULT = Path(".onmc") / "live"
EVENTS_FILENAME = "events.jsonl"

# Kinds that represent "a unit started / is running"
_START_KINDS: frozenset[str] = frozenset({"unit_queued", "unit_running", "swarm_planned"})
# Kinds that represent "a unit finished"
_STOP_KINDS: frozenset[str] = frozenset({"unit_done", "unit_failed", "unit_aborted"})


@dataclasses.dataclass(slots=True)
class Event:
    """A single recorded agent activity event.

    All fields except ``ts`` and ``kind`` are optional so callers only set
    what they know.  ``ts`` is a Unix timestamp float supplied by the caller;
    the bus never reads the system clock.
    """

    ts: float
    kind: str
    swarm_id: str | None = None
    unit: str | None = None
    agent: str | None = None
    tool: str | None = None
    detail: str | None = None
    session_id: str | None = None


def emit(event: Event, *, live_dir: Path | None = None) -> None:
    """Append *event* as one JSON line to ``<live_dir>/events.jsonl``.

    Creates the directory tree if it does not exist.  Uses ``open("a")``
    so concurrent writers each get their own ``write`` call; on POSIX,
    appends to a regular file are atomic for payloads below PIPE_BUF.
    """
    dir_path = live_dir if live_dir is not None else LIVE_DIR_DEFAULT
    dir_path.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dataclasses.asdict(event), ensure_ascii=False) + "\n"
    with open(dir_path / EVENTS_FILENAME, "a", encoding="utf-8") as fh:
        fh.write(line)


def read_events(
    live_dir: Path,
    *,
    since_ts: float | None = None,
    kinds: list[str] | None = None,
) -> list[Event]:
    """Read all events from *live_dir*, with optional filters.

    Parameters
    ----------
    live_dir:
        Directory containing ``events.jsonl``.
    since_ts:
        When set, only events with ``ts > since_ts`` are returned.
    kinds:
        When set, only events whose ``kind`` is in this list are returned.

    Returns an empty list when the events file does not exist or is empty.
    Malformed lines are silently skipped.
    """
    path = live_dir / EVENTS_FILENAME
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    events: list[Event] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        try:
            ev = Event(
                ts=float(d.get("ts", 0.0)),
                kind=str(d.get("kind", "")),
                swarm_id=d.get("swarm_id") or None,
                unit=d.get("unit") or None,
                agent=d.get("agent") or None,
                tool=d.get("tool") or None,
                detail=d.get("detail") or None,
                session_id=d.get("session_id") or None,
            )
        except (TypeError, ValueError):
            continue
        if since_ts is not None and ev.ts <= since_ts:
            continue
        if kinds is not None and ev.kind not in kinds:
            continue
        events.append(ev)
    return events


def active_agents(events: list[Event]) -> list[dict[str, object]]:
    """Derive currently-running units/agents by folding start/stop events.

    A unit is considered "active" when a ``unit_queued``/``unit_running``
    event exists but no subsequent ``unit_done``/``unit_failed``/
    ``unit_aborted`` event follows it.

    Parameters
    ----------
    events:
        All events, already loaded via :func:`read_events`.  Order matters
        (earlier events first); the list is processed sequentially.

    Returns
    -------
    list of dicts sorted by ``since_ts`` (ascending), each with keys
    ``unit``, ``agent``, ``swarm_id``, ``since_ts``, ``kind``.
    """
    # (swarm_id, unit) → most recent start event
    started: dict[tuple[str | None, str | None], Event] = {}
    stopped: set[tuple[str | None, str | None]] = set()

    for ev in events:
        key = (ev.swarm_id, ev.unit)
        if ev.unit is not None and ev.kind in _START_KINDS:
            started[key] = ev
        elif ev.unit is not None and ev.kind in _STOP_KINDS:
            stopped.add(key)

    result: list[dict[str, object]] = []
    for key, ev in started.items():
        if key not in stopped:
            result.append(
                {
                    "unit": ev.unit,
                    "agent": ev.agent,
                    "swarm_id": ev.swarm_id,
                    "since_ts": ev.ts,
                    "kind": ev.kind,
                }
            )
    result.sort(key=lambda x: float(x["since_ts"]))  # type: ignore[arg-type]
    return result
