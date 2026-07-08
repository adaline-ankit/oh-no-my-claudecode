"""``onmc explain`` — plain-English verdict of a run receipt.

Reads the latest (or a specified) tamper-evident receipt from
``.agent-memory/receipts/run-*.json`` and prints a human-readable verdict:
whether the run verified, why it stopped, and key accounting figures.

Public surface
--------------
- :func:`oh_no_my_claudecode.explain.analyze.explain_receipt` — pure function.
- :func:`oh_no_my_claudecode.explain.commands.register` — CLI entry point.
"""

from __future__ import annotations

__all__: list[str] = []
