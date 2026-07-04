"""The ``onmc autoroute`` feature — apply flywheel learning to model selection.

Where :mod:`oh_no_my_claudecode.flywheel` *learns* which model wins for which
kind of goal (from verified receipts), ``autoroute`` *applies* that learning:
given a goal, it recommends the historically-best model (+ rationale +
confidence + basis) so a swarm / loop can auto-select instead of hard-coding a
default.  This closes the self-improvement loop.

Pure, deterministic, offline — no LLM call, no training.  It reuses the
flywheel's aggregation (:func:`~oh_no_my_claudecode.flywheel.analyze.summarize`
/ :func:`~oh_no_my_claudecode.flywheel.analyze.load_trajectories`) and never
modifies it.  Self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships an ``autoroute.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.autoroute.autoroute import (
    Suggestion,
    suggest_from_repo,
    suggest_model,
)

__all__ = ["Suggestion", "suggest_from_repo", "suggest_model"]
