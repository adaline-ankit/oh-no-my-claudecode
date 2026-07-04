"""The ``onmc crossrepo`` feature — a cross-repo brain.

Multi-repo understanding is an unsolved frontier: a change in one repo
routinely ripples into its siblings, and an agent's accumulated memory is
siloed per repo.  ``crossrepo`` composes two existing onmc capabilities to
close that gap, deterministically and offline:

- **Impact map** (:func:`scan_repos`) — given N sibling repo paths, find the
  top-level modules/packages that appear in more than one repo.  Those shared
  names are the ripple surface: change one in repo A and repo B may feel it.

- **Federated recall** (:func:`federated_recall`) — a unified search across the
  repos' ``.agent-memory/`` exports, reusing the same reader schema as
  :mod:`oh_no_my_claudecode.federation`, with every hit attributed to its
  source repo and ranked by deterministic token overlap.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``crossrepo.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any shared
hub.  It only *imports* from ``federation`` and ``sync`` — it never modifies
them.
"""

from __future__ import annotations

from oh_no_my_claudecode.crossrepo.crossrepo import (
    CrossImpact,
    CrossRepoMap,
    RecallHit,
    RepoView,
    federated_recall,
    scan_repos,
)

__all__ = [
    "CrossImpact",
    "CrossRepoMap",
    "RecallHit",
    "RepoView",
    "federated_recall",
    "scan_repos",
]
