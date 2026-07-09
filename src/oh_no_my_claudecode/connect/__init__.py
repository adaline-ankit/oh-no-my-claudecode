"""``onmc connect`` — bidirectional ecosystem adapter.

This package plugs onmc's accountable "brain" into two neighbouring open-source
projects without either side reinventing the other:

- **OpenClaw** — a high-star async-agent *router* whose whole job is transport
  (WebSocket / webhook across 50+ chat platforms) and which "never reasons, only
  routes".  :mod:`oh_no_my_claudecode.connect.openclaw` translates an OpenClaw
  event envelope into a call to the existing gateway pipeline
  (:func:`oh_no_my_claudecode.gateway.pipeline.handle_inbound`) and translates the
  :class:`~oh_no_my_claudecode.gateway.pipeline.InboundResult` back into an
  OpenClaw-shaped reply.  OpenClaw stays the transport; onmc becomes the
  accountable decision layer underneath it.

- **Hermes** — a self-improving memory tool that keeps ``MEMORY.md`` / ``USER.md``.
  :mod:`oh_no_my_claudecode.connect.hermes` adds a *continuous* mirror on top of
  the existing one-shot importer
  (:mod:`oh_no_my_claudecode.importers.hermes`): a watermark under
  ``.onmc/connect/hermes-state.json`` records already-imported ids/hashes so each
  sync imports only the delta, idempotently.

Everything here reuses the existing gateway / mission-bridge / importer / notify
building blocks; it adds glue and two new outbound sinks, never a second copy of
the auth / approve / intake decision tree.  The feature is auto-discovered via
:func:`oh_no_my_claudecode.connect.commands.register` — zero edits to ``cli.py``.
"""

from __future__ import annotations

from oh_no_my_claudecode.connect.hermes import HermesSyncResult, sync_hermes
from oh_no_my_claudecode.connect.openclaw import (
    OpenClawInbound,
    handle_openclaw,
    parse_openclaw_event,
    to_openclaw_reply,
)
from oh_no_my_claudecode.connect.sinks import OpenClawSink, TelegramSink

__all__ = [
    "HermesSyncResult",
    "OpenClawInbound",
    "OpenClawSink",
    "TelegramSink",
    "handle_openclaw",
    "parse_openclaw_event",
    "sync_hermes",
    "to_openclaw_reply",
]
