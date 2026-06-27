"""onmc ledger — agent-work cost / ROI accounting over run receipts.

This package turns the tamper-evident ``RunReceipt`` JSON files written by
``onmc loop`` and ``onmc swarm`` (``.agent-memory/receipts/run-*.json``) into a
simple accounting summary: how many runs, how much they cost in USD, how much
wall-clock time they burned, how many verified, and a per-model / per-agent
breakdown.

Honesty is the whole point of the metering wedge:

- ``cost_usd`` is ``None`` on many receipts (the adapter did not surface a
  price).  We never fabricate a cost — those runs contribute ``0`` to the cost
  total and are counted separately as ``cost_unknown_count`` so the headline
  cost is honestly labelled "n/a" when nothing is known.
- ROI is an *estimate*, explicitly labelled ``est``.  It compares wall-clock
  time the agent spent against a transparent assumption of what a human would
  have spent, never claiming precision it does not have.

The aggregation core (:func:`summarize_receipts`) is a **pure** function over a
list of receipt dicts so it can be unit-tested offline by injecting receipts.
:func:`load_receipts` is the thin, impure I/O wrapper the CLI uses to read the
on-disk receipt directory; it is deliberately not exercised in tests.
"""

from __future__ import annotations

from oh_no_my_claudecode.ledger.accounting import (
    LedgerSummary,
    RoiEstimate,
    load_receipts,
    roi,
    summarize_receipts,
)

__all__ = [
    "LedgerSummary",
    "RoiEstimate",
    "load_receipts",
    "roi",
    "summarize_receipts",
]
