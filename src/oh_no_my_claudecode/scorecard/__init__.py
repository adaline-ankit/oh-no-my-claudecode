"""The ``onmc scorecard`` feature — one shareable agent-readiness + trust report.

``scorecard`` is the *aggregator* that ties onmc's suite together into a single
viral artifact a repo can show off.  It invents no new analysis; it composes four
signals that already exist elsewhere in onmc, each degrading gracefully to "n/a"
when its subsystem is absent:

- **Agent-readiness** — the 0-100 score from
  :func:`oh_no_my_claudecode.roast.scorer.compute_roast`.
- **Top agent + trust** — the highest-trust agent from the reputation ledger
  (:func:`oh_no_my_claudecode.registry.registry.build_registry`).
- **Best model** — the best-verified model from
  :func:`oh_no_my_claudecode.flywheel.analyze.summarize`.
- **Institutional-memory coverage** — entity/edge counts from
  :func:`oh_no_my_claudecode.orggraph.graph.build_org_graph`.

The blend is deterministic and offline — no LLM call.  The feature self-registers
via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``scorecard.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.scorecard.scorecard import (
    Scorecard,
    build_scorecard,
    render_markdown,
    render_summary,
)

__all__ = ["Scorecard", "build_scorecard", "render_markdown", "render_summary"]
