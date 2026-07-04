"""The ``onmc orggraph`` feature — an institutional-memory knowledge graph.

Institutional memory is the frontier bottleneck for AI coding agents: the
context lives in people's heads and scattered notes, not in a form an agent can
traverse. onmc already stores *provenanced* memories; ``orggraph`` turns those
memories into an **entity/relationship knowledge graph with lineage** — every
node and edge is traceable back to the memory that justified it.

- :func:`~oh_no_my_claudecode.orggraph.graph.build_org_graph` extracts entities
  (files, components, decisions, people) and typed edges (``supersedes``,
  ``depends-on``, ``decided-by``, ``caused-by``, ``relates-to``) from a list of
  memories. It is pure, offline, stdlib-only, and deterministic.
- :func:`~oh_no_my_claudecode.orggraph.graph.query_entity` returns an entity, its
  neighbours, and its provenance.
- :func:`~oh_no_my_claudecode.orggraph.graph.decision_lineage` returns the chain
  of memories/edges behind a decision.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships an ``orggraph.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.
"""

from __future__ import annotations

from oh_no_my_claudecode.orggraph.graph import (
    Edge,
    Entity,
    OrgGraph,
    build_org_graph,
    decision_lineage,
    query_entity,
)

__all__ = [
    "Edge",
    "Entity",
    "OrgGraph",
    "build_org_graph",
    "decision_lineage",
    "query_entity",
]
