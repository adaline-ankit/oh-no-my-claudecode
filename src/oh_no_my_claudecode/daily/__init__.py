"""Calendar-day don't-break-the-chain engagement streak for onmc.

Tracks which calendar days (UTC) you were active and rewards
consecutive-day chains — a different axis from ``coach`` which tracks
per-event combos within a session.

Pure logic lives in :mod:`oh_no_my_claudecode.daily.chain`.
CLI surface lives in :mod:`oh_no_my_claudecode.daily.commands`.
"""

from oh_no_my_claudecode.daily.chain import (
    GridCell,
    current_streak,
    grid,
    longest_streak,
    milestone,
)

__all__ = [
    "GridCell",
    "current_streak",
    "grid",
    "longest_streak",
    "milestone",
]
