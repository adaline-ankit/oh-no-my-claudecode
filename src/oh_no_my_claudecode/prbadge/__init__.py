"""``onmc prbadge`` — post a shareable verified-work badge comment on a PR.

Turns the local trust ledger (run receipts under ``.agent-memory/receipts/``,
the same corpus :mod:`oh_no_my_claudecode.ledger` aggregates) into a compact
Markdown comment and posts it to a GitHub PR via ``gh pr comment``.

Distribution mechanic: every onmc-built PR can advertise onmc with one
command. The badge is honest — it only claims what the receipts support, and
renders a "no verified receipts yet" zero-state rather than fabricating a
number.
"""

from __future__ import annotations

from oh_no_my_claudecode.prbadge.prbadge import (
    BadgeContent,
    build_badge,
    render_markdown,
)

__all__ = ["BadgeContent", "build_badge", "render_markdown"]
