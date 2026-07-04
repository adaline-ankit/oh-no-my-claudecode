"""The ``onmc attest`` feature — verifiable, portable proof-of-work.

An onmc receipt already proves work is real and verified locally
(``git_tree_sha``, ``diff_sha``, ``receipt_hash``, ``verified``).  ``attest``
turns one receipt into a **signed, portable attestation** a third party can
verify without trusting onmc, plus an agent **reputation summary** — the shape
the agent economy (ERC-8004 registries, WorkProtocol) needs for verifiable
proof-of-work.

Everything here is stdlib-only and offline: HMAC-SHA256 when a shared secret is
present, a SHA256 integrity digest otherwise.  The core (:mod:`attest.attest`)
is pure; the CLI (:mod:`attest.commands`) self-registers via the command
auto-discovery convention (see :mod:`oh_no_my_claudecode.command_registry`) —
**zero** edits to ``cli.py`` or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.attest.attest import (
    Attestation,
    ReputationSummary,
    build_attestation,
    build_reputation,
    canonical_claim,
    sign_claim,
    verify_attestation,
)

__all__ = [
    "Attestation",
    "ReputationSummary",
    "build_attestation",
    "build_reputation",
    "canonical_claim",
    "sign_claim",
    "verify_attestation",
]
