"""Context Firewall helpers for hook modules.

This module provides the ``is_firewall_enabled()`` flag and a thin wrapper
around ``emit_event`` that respects the kill-switch.  Hook modules import
from here instead of calling ``emit_event`` directly so the kill-switch is
always honoured.

Kill-switch
-----------
Set ``ONMC_FIREWALL=0`` (or ``false`` / ``no``) to disable firewall routing.
When the firewall is OFF the hooks fall back to their pre-firewall behaviour:
no events are sent to the sink, and (if ``ONMC_VERBOSE=1`` is set) verbose
pointer lines remain in context.  The kill-switch does NOT affect the notify
subsystem itself — ``ONMC_NOTIFY_ENABLED=0`` controls that separately.

Default: firewall ON.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from oh_no_my_claudecode.notify import NotifyEvent, emit_event


def is_firewall_enabled() -> bool:
    """Return True when the context firewall is active (default ON).

    Reads ``ONMC_FIREWALL`` from the environment:
    - ``"0"`` / ``"false"`` / ``"no"``  → firewall OFF
    - anything else (including unset)    → firewall ON
    """
    val = os.environ.get("ONMC_FIREWALL", "").strip().lower()
    return val not in ("0", "false", "no")


def firewall_emit(repo_root: Path, event: NotifyEvent) -> None:
    """Emit *event* to the sink if the firewall is enabled.

    Fully exception-safe — never raises.  If the firewall is disabled
    (``ONMC_FIREWALL=0``) the call is a no-op.
    """
    if not is_firewall_enabled():
        return
    with contextlib.suppress(Exception):
        emit_event(repo_root, event)
