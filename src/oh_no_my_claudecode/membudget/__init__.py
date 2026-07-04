"""Memory-budget guard and consolidation suggester for onmc.

``onmc membudget`` inspects the onmc memory store, reports total size with a
per-kind breakdown, flags when the store is over a configurable byte budget, and
SUGGESTS concrete consolidation actions (merge near-duplicates, move verbose
entries to topic files, drop stale entries).

Advisory-only — never deletes or mutates the store.
"""

from oh_no_my_claudecode.membudget.analyzer import BudgetReport, analyze

__all__ = ["BudgetReport", "analyze"]
