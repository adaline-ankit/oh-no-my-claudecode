"""Agent Trace Observatory — session-scoped token-ROI tracing.

Public surface
--------------
- ``TraceEvent`` / ``TraceSession`` / ``TraceReport`` — data models.
- ``start_session`` / ``stop_session`` / ``record_trace_event`` — recorder API.
- ``compile_trace_report`` — pure report compiler (no I/O).
- ``render_trace_card`` — Rich terminal rendering.

All I/O is exception-safe and never blocks.
"""

from __future__ import annotations

from oh_no_my_claudecode.trace.models import TraceEvent, TraceReport, TraceSession
from oh_no_my_claudecode.trace.recorder import (
    current_span_id,
    record_trace_event,
    start_session,
    stop_session,
    trace_parent,
    trace_span,
)
from oh_no_my_claudecode.trace.report import compile_trace_report

__all__ = [
    "TraceEvent",
    "TraceReport",
    "TraceSession",
    "compile_trace_report",
    "current_span_id",
    "record_trace_event",
    "start_session",
    "stop_session",
    "trace_parent",
    "trace_span",
]
