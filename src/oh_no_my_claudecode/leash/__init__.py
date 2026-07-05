"""The ``onmc leash`` feature — guardrails-as-game.

Define playful "house rules" the agent should follow during a session,
check activity text against them, and score compliance — gamified
guardrails with a live compliance grade.

Core I/O is isolated in :mod:`~oh_no_my_claudecode.leash.rules` — all
public functions are pure over injectable ``leash_dir`` and ``ts``
arguments, making the module fully testable offline.

The feature self-registers via the command auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry`): it ships a ``leash.commands``
module exposing ``register(app)`` — **zero** edits to ``cli.py`` or any
shared hub.

Distinct from related features
-------------------------------
- ``drift``  — enforces *memory-directives* against *source code* files.
- ``wrap``   — installs Claude Code hooks that intercept tool calls at
  runtime.
- ``leash``  — user-defined *session rules* scored against event text;
  lightweight, gamified, no code analysis.
"""

from __future__ import annotations

from oh_no_my_claudecode.leash.rules import (
    HISTORY_FILE,
    LEASH_SUBDIR,
    RULES_FILE,
    SEVERITY_HARD,
    SEVERITY_SOFT,
    Rule,
    ScoreCard,
    Violation,
    add_rule,
    check,
    load_rules,
    load_score,
    record_check,
    remove_rule,
    save_rules,
    score,
)

__all__ = [
    "HISTORY_FILE",
    "LEASH_SUBDIR",
    "RULES_FILE",
    "SEVERITY_HARD",
    "SEVERITY_SOFT",
    "Rule",
    "ScoreCard",
    "Violation",
    "add_rule",
    "check",
    "load_rules",
    "load_score",
    "record_check",
    "remove_rule",
    "save_rules",
    "score",
]
