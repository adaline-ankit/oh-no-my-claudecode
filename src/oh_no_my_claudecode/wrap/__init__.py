"""``onmc wrap`` — make onmc the default layer for a Claude Code session.

Wrapping installs two hooks into ``.claude/settings.json``:

- a ``PreToolUse`` hook (matcher ``"Task"``) that intercepts native
  agent-spawning and redirects it to ``onmc swarm`` (strict = deny + redirect,
  soft = nudge), and
- a ``UserPromptSubmit`` hook that routes each prompt through onmc's
  deterministic router + dead-end guard and injects a terse "prefer onmc
  paths" nudge.

``onmc unwrap`` is the perfect inverse: it removes exactly what ``wrap`` added
(reusing the shared installer's surgical strip) and restores the CLAUDE.md
policy stanza, leaving every other hook untouched.

The decision logic lives in :mod:`oh_no_my_claudecode.wrap.logic` and is built
to never raise — a wrapper that bricks Claude Code is unacceptable.
"""

from __future__ import annotations

from oh_no_my_claudecode.wrap.logic import (
    compile_prompt_policy,
    compile_task_intercept,
    swarm_active,
)
from oh_no_my_claudecode.wrap.state import (
    read_wrap_strict,
    remove_claude_md_stanza,
    remove_wrap_state,
    upsert_claude_md_stanza,
    write_wrap_state,
)

__all__ = [
    "compile_prompt_policy",
    "compile_task_intercept",
    "read_wrap_strict",
    "remove_claude_md_stanza",
    "remove_wrap_state",
    "swarm_active",
    "upsert_claude_md_stanza",
    "write_wrap_state",
]
