"""``onmc inbox`` — a ranked work queue.

A self-contained feature package that surfaces a single prioritised to-do list
for a repo, drawn from four sources:

- **manual** — items the user adds via ``onmc inbox add "<text>"``.
- **todo** — ``TODO`` / ``FIXME`` markers grepped from the source tree.
- **coverage** — high-churn files with no memory coverage (reuses
  :mod:`oh_no_my_claudecode.coverage.compiler`).
- **memory** — low-confidence / unverified memories worth revisiting.

State for manual items lives as JSON under ``.onmc/inbox/`` (mirroring the
``notify`` subsystem's file-storage convention).  Ranking is deterministic so
that ``rank`` / ``list`` / ``run`` produce stable, testable output.

The feature registers its CLI surface via the additive auto-discovery hook
(see :mod:`oh_no_my_claudecode.command_registry`) — zero edits to ``cli.py``.
"""

from __future__ import annotations

from oh_no_my_claudecode.inbox.queue import (
    InboxItem,
    add_item,
    gather_candidates,
    list_items,
    rank_items,
)

__all__ = [
    "InboxItem",
    "add_item",
    "gather_candidates",
    "list_items",
    "rank_items",
]
