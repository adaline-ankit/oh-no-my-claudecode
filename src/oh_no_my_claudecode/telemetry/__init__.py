"""Telemetry live event bus for onmc agent activity.

Exposes the public surface of the telemetry package.  Import from here
for a stable, versioned interface; implementation lives in ``bus.py``.
"""

from __future__ import annotations

from oh_no_my_claudecode.telemetry.bus import (
    Event,
    active_agents,
    emit,
    read_events,
)
from oh_no_my_claudecode.telemetry.exporter import (
    ExportResponse,
    ExportResult,
    OtlpHttpExporter,
)

__all__ = [
    "Event",
    "ExportResponse",
    "ExportResult",
    "OtlpHttpExporter",
    "active_agents",
    "emit",
    "read_events",
]
