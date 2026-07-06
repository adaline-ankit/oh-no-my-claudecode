"""``onmc bottleneck`` — surface slowest goals, models, and outlier runs.

Reads the same run-receipt schema (:mod:`oh_no_my_claudecode.ledger.accounting`)
that ``onmc cost`` reads, but looks at time instead of money: which goals and
models eat the most wall-clock time, and which individual runs are outliers
worth investigating. Deterministic, offline, LLM-free.
"""

from __future__ import annotations
