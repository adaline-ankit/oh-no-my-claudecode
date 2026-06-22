"""Context Firewall — side-channel notification subsystem.

Operational chatter (capture confirmations, skill promotions, staleness
warnings, danger-guard notices) is routed to a *sink* instead of being
injected into the agent's context window.  This keeps the model context lean —
only high-value recall reaches the agent.

Public API
----------
- ``NotifyEvent`` — the event dataclass hooks produce.
- ``EventKind`` / ``EventSeverity`` — enum types for kind and severity.
- ``emit_event(repo_root, event)`` — module-level convenience; fully
  exception-safe, never raises.
- ``NotifyRouter`` — resolves config and dispatches to the active sink(s).
- ``FileSink`` / ``DiscordSink`` / ``SlackSink`` — concrete sink classes.
"""

from __future__ import annotations

from oh_no_my_claudecode.notify.events import EventKind, EventSeverity, NotifyEvent
from oh_no_my_claudecode.notify.router import NotifyRouter, emit_event
from oh_no_my_claudecode.notify.sinks import DiscordSink, FileSink, SlackSink

__all__ = [
    "DiscordSink",
    "EventKind",
    "EventSeverity",
    "FileSink",
    "NotifyEvent",
    "NotifyRouter",
    "SlackSink",
    "emit_event",
]
