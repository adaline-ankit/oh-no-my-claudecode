"""Typed event dataclass for the context firewall notification subsystem."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class EventKind(StrEnum):
    """Coarse category of an operational notification."""

    MEMORY_CAPTURED = "memory_captured"
    SKILL_PROMOTED = "skill_promoted"
    RECALL_SURFACED = "recall_surfaced"
    STALENESS_WARNING = "staleness_warning"
    DANGER_BLOCKED = "danger_blocked"
    GENERIC = "generic"


class EventSeverity(StrEnum):
    """Routing urgency.

    ``routine`` events may be batched / coalesced inside the sink.
    ``failure`` and ``approval`` events are always emitted immediately.
    """

    ROUTINE = "routine"
    FAILURE = "failure"
    APPROVAL = "approval"


@dataclass
class NotifyEvent:
    """A single operational notification produced by an onmc hook or command.

    Parameters
    ----------
    kind:
        Coarse category — use ``EventKind`` values.
    title:
        Short human-readable title (one line).
    severity:
        Routing urgency; ``routine`` may be coalesced, ``failure`` /
        ``approval`` always emit immediately.
    detail:
        Optional long-form body (markdown OK for webhook sinks).
    ts:
        Unix timestamp (seconds).  Defaults to ``time.time()`` at
        construction so callers rarely need to set this explicitly.
    """

    kind: EventKind | str
    title: str
    severity: EventSeverity | str = EventSeverity.ROUTINE
    detail: str = ""
    ts: float = field(default_factory=time.time)
