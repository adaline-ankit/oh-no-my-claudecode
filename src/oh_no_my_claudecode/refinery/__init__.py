"""``onmc refinery`` — Bors-style serialised merge queue.

Enqueue PRs, process them one at a time: rebase head onto main, wait for CI
green (quality matrix *and* CodeQL), merge, pop. On failure the entry is
kicked back with a reason so it cannot block the queue.

Public API
----------
The three submodules are independently importable:

- :mod:`~oh_no_my_claudecode.refinery.queue`   — pure state machine, no I/O.
- :mod:`~oh_no_my_claudecode.refinery.driver`  — side-effecting processor with
  injectable ``gh`` object.
- :mod:`~oh_no_my_claudecode.refinery.commands` — Typer CLI surface, auto-discovered.
"""

from __future__ import annotations
