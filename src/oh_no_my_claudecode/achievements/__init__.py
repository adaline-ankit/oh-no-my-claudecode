"""``onmc achievements`` — gamified XP, streaks, and badges from run receipts.

Read-only, deterministic, LLM-free.  Pure aggregation over the same
``RunReceipt`` JSON shape the ``ledger`` and ``quest`` features already read
from ``.agent-memory/receipts/`` — no new schema, no new storage.

See :mod:`oh_no_my_claudecode.achievements.achievements` for the pure engine
and :mod:`oh_no_my_claudecode.achievements.commands` for the CLI surface.
"""

from __future__ import annotations

from oh_no_my_claudecode.achievements.achievements import (
    Achievement,
    AchievementsReport,
    build_report,
    render_text,
)

__all__ = [
    "Achievement",
    "AchievementsReport",
    "build_report",
    "render_text",
]
