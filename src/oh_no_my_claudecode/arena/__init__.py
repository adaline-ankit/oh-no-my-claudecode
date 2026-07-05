"""Model gladiator: head-to-head ELO scoreboard.

``onmc arena`` lets you record head-to-head model bouts (model A vs model B on
a task, who won) and tracks ELO ratings over time.  It is the interactive
comparison layer that complements ``flywheel`` (which learns best-model from
verified run receipts) and ``registry`` (which aggregates signed attestations).

Design constraints:
- **Pure / deterministic** — no I/O or randomness in the ELO math; identical
  bouts always yield identical ratings, byte-for-byte.
- **Offline, stdlib only** — no external dependencies.
- **Recompute-from-source** — ratings are always recomputed from the raw bouts
  log so they can never drift from the math (mirrors ``registry``).
- **Honest** — a model with no bouts has no rating (reported as absent, not as
  a fabricated default).
"""

from oh_no_my_claudecode.arena.elo import Bout, Ledger, update_elo

__all__ = ["Bout", "Ledger", "update_elo"]
