"""Reuse radar — surface existing code that already does a thing.

Given a description or symbol name, :func:`find_reuse` indexes the repo via the
stdlib :mod:`ast` module and returns a ranked list of existing top-level
functions/classes that may already implement the desired behaviour.  Entirely
offline and deterministic — no LLM calls, no network — so an agent in a swarm
can check "does this already exist?" before reimplementing a pattern (DRY).

Optional ast-grep integration
------------------------------
When the ``ast-grep`` (or ``sg``) binary is on ``PATH`` and the caller opts in
(``--ast-grep`` CLI flag / ``ast_grep=True`` service kwarg), :func:`find_reuse`
additionally runs structural AST-pattern matching via :func:`find_reuse_structural`
and appends :class:`StructuralMatch` hits.  Binary absent or flag not set →
behaviour is completely unchanged (zero regression).
"""

from __future__ import annotations

from oh_no_my_claudecode.reuse.astgrep import (
    AstGrepRunner,
    StructuralMatch,
    ast_grep_available,
    find_reuse_structural,
    make_ast_grep_runner,
)
from oh_no_my_claudecode.reuse.radar import ReuseHit, find_reuse

__all__ = [
    "AstGrepRunner",
    "ReuseHit",
    "StructuralMatch",
    "ast_grep_available",
    "find_reuse",
    "find_reuse_structural",
    "make_ast_grep_runner",
]
