"""Session recorder for the Agent Trace Observatory.

Responsibilities
----------------
- ``start_session(repo_root, label)`` — create a new trace session JSONL file
  and write the session envelope as the first line.  Sets the "current" pointer
  so subsequent calls don't need to track the session_id manually.
- ``stop_session(repo_root)`` — close the current session (write ``ended_at``
  tombstone, remove the ``current`` pointer file).
- ``record_trace_event(repo_root, event)`` — append a ``TraceEvent`` to the
  current session's JSONL file.  No-op (never raises) if no session is active.

All I/O is exception-safe — these functions MUST never raise.  They are
designed to be called from hooks / CLI without disrupting the agent.

File layout
-----------
::

    .onmc/traces/
        current               <- one-line text file: session_id of active session
        <session_id>.jsonl    <- JSONL: first line is session envelope, rest are events
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.trace.models import TraceEvent, TraceSession

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_TRACES_DIR_NAME = "traces"
_CURRENT_FILE_NAME = "current"
_CURRENT_SPAN_ID: ContextVar[str | None] = ContextVar(
    "onmc_current_trace_span_id",
    default=None,
)


def _traces_dir(repo_root: Path) -> Path:
    return repo_root / ".onmc" / _TRACES_DIR_NAME


def _current_file(repo_root: Path) -> Path:
    return _traces_dir(repo_root) / _CURRENT_FILE_NAME


def _session_file(repo_root: Path, session_id: str) -> Path:
    return _traces_dir(repo_root) / f"{session_id}.jsonl"


def _new_session_id() -> str:
    """Generate a short random session identifier."""
    return "tr_" + secrets.token_hex(8)


def _new_span_id() -> str:
    """Generate a process-local logical span identifier."""
    return "sp_" + secrets.token_hex(8)


@dataclass(slots=True)
class TraceSpan:
    """Mutable handle for adding measured metadata before a span closes."""

    span_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    def set_attribute(self, key: str, value: object) -> None:
        """Attach one observed attribute to the eventual trace event."""
        self.payload[key] = value

    def set_usage(
        self,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cache_read_input_tokens: int | None = None,
        cache_creation_input_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> None:
        """Attach provider-reported usage without deriving missing values."""
        observed = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
            "cost_usd": cost_usd,
        }
        self.payload.update({key: value for key, value in observed.items() if value is not None})


def current_span_id() -> str | None:
    """Return the logical parent span active in this execution context."""
    return _CURRENT_SPAN_ID.get()


@contextmanager
def trace_parent(span_id: str) -> Iterator[None]:
    """Make *span_id* the parent for trace events recorded in this context."""
    token = _CURRENT_SPAN_ID.set(span_id)
    try:
        yield
    finally:
        _CURRENT_SPAN_ID.reset(token)


@contextmanager
def trace_span(
    repo_root: Path,
    kind: str,
    *,
    payload: dict[str, Any] | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
) -> Iterator[TraceSpan]:
    """Record a real-duration nested span around a synchronous operation.

    The helper never estimates timing or usage.  Callers attach only values
    observed from the provider or operation through the yielded handle.
    """
    started_at = time.time()
    logical_span_id = span_id or _new_span_id()
    resolved_parent = parent_span_id or current_span_id()
    handle = TraceSpan(span_id=logical_span_id, payload=dict(payload or {}))
    try:
        with trace_parent(logical_span_id):
            yield handle
    except Exception as exc:
        handle.payload.setdefault("error_type", type(exc).__name__)
        handle.payload.setdefault("status", "error")
        raise
    finally:
        ended_at = time.time()
        handle.payload["end_ts"] = ended_at
        handle.payload["duration_seconds"] = max(0.0, ended_at - started_at)
        record_trace_event(
            repo_root,
            TraceEvent(
                kind=kind,
                ts=started_at,
                payload=handle.payload,
                span_id=logical_span_id,
                parent_span_id=resolved_parent,
            ),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_session(repo_root: Path, *, label: str = "") -> str | None:
    """Start a new trace session for *repo_root*.

    Creates ``.onmc/traces/<session_id>.jsonl`` with the session envelope as
    the first line and writes ``session_id`` to ``.onmc/traces/current``.

    Parameters
    ----------
    repo_root:
        Repository root.
    label:
        Optional human-readable label for the session (e.g. "Codex task: add
        timeout param").

    Returns
    -------
    str | None
        The new session_id, or ``None`` on I/O failure.
    """
    try:
        traces = _traces_dir(repo_root)
        traces.mkdir(parents=True, exist_ok=True)

        session_id = _new_session_id()
        session = TraceSession(
            session_id=session_id,
            started_at=time.time(),
            ended_at=None,
            label=label,
        )

        session_path = _session_file(repo_root, session_id)
        with session_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(session.to_record()) + "\n")

        _current_file(repo_root).write_text(session_id + "\n", encoding="utf-8")
        return session_id
    except Exception:  # noqa: BLE001
        return None


def stop_session(repo_root: Path, *, session_id: str | None = None) -> bool:
    """Close the current (or specified) trace session.

    Appends a tombstone record with ``ended_at``, then removes the ``current``
    pointer file.

    Parameters
    ----------
    repo_root:
        Repository root.
    session_id:
        If ``None``, uses the session from the ``current`` pointer file.

    Returns
    -------
    bool
        ``True`` if the session was found and closed successfully.
    """
    try:
        if session_id is None:
            curr = _current_file(repo_root)
            if not curr.exists():
                return False
            session_id = curr.read_text(encoding="utf-8").strip()

        session_path = _session_file(repo_root, session_id)
        if not session_path.exists():
            return False

        tombstone = {"_type": "session_end", "session_id": session_id, "ended_at": time.time()}
        with session_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(tombstone) + "\n")

        curr_file = _current_file(repo_root)
        if curr_file.exists():
            curr_file.unlink(missing_ok=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def record_trace_event(repo_root: Path, event: TraceEvent) -> None:
    """Append *event* to the active session's JSONL file.

    No-op (never raises) if no session is active or on any I/O error.

    Parameters
    ----------
    repo_root:
        Repository root.
    event:
        The ``TraceEvent`` to append.
    """
    try:
        if event.parent_span_id is None and current_span_id() is not None:
            event = replace(event, parent_span_id=current_span_id())
        curr_file = _current_file(repo_root)
        if not curr_file.exists():
            return
        session_id = curr_file.read_text(encoding="utf-8").strip()
        if not session_id:
            return
        session_path = _session_file(repo_root, session_id)
        with session_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_record()) + "\n")
    except Exception:  # noqa: BLE001
        return


def current_session_id(repo_root: Path) -> str | None:
    """Return the active session_id, or ``None`` if no session is open."""
    try:
        curr = _current_file(repo_root)
        if not curr.exists():
            return None
        value = curr.read_text(encoding="utf-8").strip()
        return value or None
    except Exception:  # noqa: BLE001
        return None


def load_session_events(
    repo_root: Path,
    session_id: str,
    *,
    include_notify_window: bool = True,
) -> tuple[TraceSession | None, list[TraceEvent]]:
    """Load a session's envelope and events from disk.

    Also merges notify.log events that fall within the session time window
    when *include_notify_window* is ``True``.

    Parameters
    ----------
    repo_root:
        Repository root.
    session_id:
        The session to load.
    include_notify_window:
        If ``True``, read ``.onmc/notify.log`` and include events whose
        timestamp falls within ``[session.started_at, session.ended_at]``
        (or to now if still open).

    Returns
    -------
    tuple[TraceSession | None, list[TraceEvent]]
        ``(session, events)`` — ``session`` is ``None`` if the file is missing
        or corrupt.  ``events`` is sorted by timestamp ascending.
    """
    from oh_no_my_claudecode.trace.models import TraceEvent  # local import for clarity

    session_path = _session_file(repo_root, session_id)
    if not session_path.exists():
        return None, []

    session: TraceSession | None = None
    events: list[TraceEvent] = []

    try:
        for raw_line in session_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            record = json.loads(line)
            rec_type = record.get("_type", "")

            if rec_type == "session":
                session = TraceSession.from_record(record)
            elif rec_type == "session_end":
                # Update ended_at from the tombstone.
                if session is not None:
                    session.ended_at = float(record.get("ended_at", session.ended_at or 0))
            else:
                # Regular event record.
                events.append(TraceEvent.from_record(record))
    except Exception:  # noqa: BLE001
        return session, events

    if session is None:
        return None, events

    # Merge notify.log window.
    if include_notify_window:
        notify_log = repo_root / ".onmc" / "notify.log"
        if notify_log.exists():
            since = session.started_at
            until = session.ended_at if session.ended_at is not None else time.time()
            try:
                for raw_line in notify_log.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    ts = float(record.get("ts", 0))
                    if since <= ts <= until:
                        events.append(TraceEvent.from_notify_record(record))
            except Exception:  # noqa: BLE001, S110
                pass  # notify.log parse errors must never disrupt the trace report

    events.sort(key=lambda e: e.ts)
    return session, events
