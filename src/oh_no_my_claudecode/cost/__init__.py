"""``onmc cost`` — spend breakdown and forecast from run receipts.

Distinct from :mod:`oh_no_my_claudecode.savings` (an ROI / "wrapped" card
comparing agent time against an assumed human baseline) and
:mod:`oh_no_my_claudecode.standup` (an activity digest over a recent window).
``cost`` is about money: where it went (by model, by day) and a simple,
clearly-labelled projection of where it is going.
"""

from __future__ import annotations
