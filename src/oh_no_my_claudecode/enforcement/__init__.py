"""Enforced capability path: a reference monitor over the tool broker.

This package does not reimplement policy decisions — it *composes* the
deny-by-default :class:`~oh_no_my_claudecode.tool_broker.ToolBroker` into a classic
reference monitor. Every supported effect (filesystem, command, network, secret)
crosses :meth:`ReferenceMonitor.guard`; a denied effect is a guaranteed no-op; an
egress allowlist and an explicit approval path add composition on top; and an
append-only decision trace records provenance-tagged verdicts with secrets scrubbed.

Provenance :class:`TaintLabel` / :class:`Tainted` and opaque :class:`SecretHandle`
references live in :mod:`.taint`.
"""

from .monitor import (
    DecisionRecord,
    Effect,
    EffectExecutor,
    EnforcementResult,
    ReferenceMonitor,
)
from .taint import (
    UNTRUSTED_LABELS,
    RevealCapability,
    SecretHandle,
    Tainted,
    TaintLabel,
)

__all__ = [
    "UNTRUSTED_LABELS",
    "DecisionRecord",
    "Effect",
    "EffectExecutor",
    "EnforcementResult",
    "ReferenceMonitor",
    "RevealCapability",
    "SecretHandle",
    "Tainted",
    "TaintLabel",
]
