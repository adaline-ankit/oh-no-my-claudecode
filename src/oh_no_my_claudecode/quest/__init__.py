"""``onmc quest`` — gamified RPG backlog from receipts.

Turn work into an RPG: XP from verified runs, levels, achievements,
streaks, boss-fights (gnarly open tasks), and loot (completed work).
"""

from oh_no_my_claudecode.quest.engine import (
    Achievement,
    ActiveQuest,
    BossFight,
    Loot,
    QuestLog,
    compute_quests,
)

__all__ = [
    "Achievement",
    "ActiveQuest",
    "BossFight",
    "Loot",
    "QuestLog",
    "compute_quests",
]
