"""Replay Lab — deterministic re-derivation of onmc behaviour over a recorded session.

Public surface
--------------
- :func:`replay_session` — re-derive recall/guard hits for each step in a recorded
  trace session.  Deterministic, offline, no LLM.
- :func:`compare_replay` — run both ``with_memory=True`` and ``with_memory=False``
  and return a :class:`ReplayComparison` showing what memory changed.
- :class:`ReplayStep`, :class:`ReplayReport`, :class:`ReplayComparison` — data models.
"""

from __future__ import annotations

from oh_no_my_claudecode.replay.lab import compare_replay, replay_session
from oh_no_my_claudecode.replay.models import ReplayComparison, ReplayReport, ReplayStep

__all__ = [
    "ReplayComparison",
    "ReplayReport",
    "ReplayStep",
    "compare_replay",
    "replay_session",
]
