"""The ``onmc badge`` feature — a shareable "No-Slop verified" proof-of-work badge.

onmc's swarm/loop receipts already prove that a unit of work is *real* and
*verified*: each :class:`RunReceipt` JSON under ``.agent-memory/receipts/`` carries
a ``git_tree_sha``, a ``diff_sha``, a ``verified`` flag, and a tamper-evident
``receipt_hash``. This feature surfaces that proof as a shields.io-style Markdown
badge (and a shields.io *endpoint* payload), plus a PR-comment body that cites the
hashes — so every PR can advertise that onmc gated the work.

Everything here is **pure** and offline:

- :func:`load_receipt` resolves a receipt either by an explicit file path or by a
  swarm id (optionally a unit id) via the swarm ``manifest.json``. It returns
  ``None`` on any missing/unreadable input — it never raises for absence.
- :func:`render_markdown_badge`, :func:`endpoint_payload`, and
  :func:`comment_body` are pure functions over a receipt dict.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``badge.commands`` module
exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.badge.badge import (
    comment_body,
    endpoint_payload,
    load_receipt,
    render_markdown_badge,
)

__all__ = [
    "comment_body",
    "endpoint_payload",
    "load_receipt",
    "render_markdown_badge",
]
