"""The ``onmc pulse`` feature — a one-shot "is it stuck?" liveness heartbeat.

Pulse answers the single most common Claude-Code UX question of 2026 — often
called *Interactive Entropy* — "is the agent working, idle, or stuck?" — and
pushes the answer to your phone via the notify sinks (Slack / Telegram /
Discord / file).  It reads the same live swarm state as ``onmc missioncontrol``
and ``onmc watch`` and reduces it to a compact verdict (▶ working / ⏸ idle /
⚠️ possibly-stuck).

Unlike ``onmc watch`` (a terminal-only auto-refresh TUI), pulse is a **one-shot
verdict + PUSH**, not a live monitor.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``pulse.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.pulse.heartbeat import (
    DEFAULT_STUCK_AFTER_MS,
    GLYPH,
    VERDICT_EMPTY,
    VERDICT_IDLE,
    VERDICT_STUCK,
    VERDICT_WORKING,
    Pulse,
    PulseSwarm,
    PulseUnit,
    build_pulse,
    humanize_ms,
    render_pulse_text,
    to_event,
)

__all__ = [
    "DEFAULT_STUCK_AFTER_MS",
    "GLYPH",
    "VERDICT_EMPTY",
    "VERDICT_IDLE",
    "VERDICT_STUCK",
    "VERDICT_WORKING",
    "Pulse",
    "PulseSwarm",
    "PulseUnit",
    "build_pulse",
    "humanize_ms",
    "render_pulse_text",
    "to_event",
]
