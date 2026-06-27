"""Reuse radar — surface existing code that already does a thing.

Given a description or symbol name, :func:`find_reuse` indexes the repo via the
stdlib :mod:`ast` module and returns a ranked list of existing top-level
functions/classes that may already implement the desired behaviour.  Entirely
offline and deterministic — no LLM calls, no network — so an agent in a swarm
can check "does this already exist?" before reimplementing a pattern (DRY).
"""

from __future__ import annotations

from oh_no_my_claudecode.reuse.radar import ReuseHit, find_reuse

__all__ = ["ReuseHit", "find_reuse"]
