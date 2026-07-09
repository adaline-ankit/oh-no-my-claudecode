"""The accountable agent gateway — onmc's live inbound layer.

The gateway is the "wrapper over all of onmc": it receives an inbound chat
message from a transport router (OpenClaw / Slack / Telegram / Claude Code
Channels), runs it through the already-built ``missionbridge`` pipeline, and
returns a trust-oriented decision.  OpenClaw is explicitly a router that "never
performs reasoning" — onmc is the brain behind it.

This package is pure wiring over existing pieces; it invents no new policy:

- :mod:`oh_no_my_claudecode.gateway.pipeline` — the deterministic core
  (:func:`handle_inbound`), reusing ``missionbridge.auth`` /
  ``missionbridge.approve`` / ``missionbridge.intake``.
- :mod:`oh_no_my_claudecode.gateway.server` — a stdlib ``http.server`` app with
  a socket-free :func:`route` for testing.
- :mod:`oh_no_my_claudecode.gateway.commands` — the auto-discovered ``onmc
  gateway`` CLI group.
"""

from __future__ import annotations

from oh_no_my_claudecode.gateway.pipeline import InboundResult, handle_inbound

__all__ = ["InboundResult", "handle_inbound"]
