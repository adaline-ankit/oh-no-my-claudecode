"""The ``onmc registry`` feature — an agent-reputation trust ledger.

``onmc attest`` produces portable, signed proof-of-work attestations. This
feature is the reputation layer *on top* of them: aggregate many attestations
(across many agents) into a queryable, rankable trust ledger — the
marketplace/reputation surface the agent economy needs.

It reuses :func:`oh_no_my_claudecode.attest.attest.verify_attestation` and the
:class:`~oh_no_my_claudecode.attest.attest.Attestation` schema verbatim (import
only — ``attest`` is never modified). Only *signature-verified* attestations
count toward an agent's reputation; unverifiable ones are recorded and flagged
but never earn trust.

The ledger persists as a JSON file under the repo's ``.onmc/`` state dir, and
the feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`) — **zero** edits to ``cli.py`` or
any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.registry.registry import (
    VOLUME_THRESHOLD,
    AgentReputation,
    Registry,
    build_registry,
    ingest,
    load_attestation,
    rank,
)

__all__ = [
    "VOLUME_THRESHOLD",
    "AgentReputation",
    "Registry",
    "build_registry",
    "ingest",
    "load_attestation",
    "rank",
]
