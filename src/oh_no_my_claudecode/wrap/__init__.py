"""``onmc wrap`` — make onmc the default layer for a Claude Code session.

Wrapping installs four hooks into ``.claude/settings.json``:

- a ``PreToolUse`` hook (matcher ``"Task"``) that intercepts native
  agent-spawning and redirects it to ``onmc swarm`` (strict = deny + redirect,
  soft = nudge), and
- a ``UserPromptSubmit`` hook that routes each prompt through onmc's
  deterministic router + dead-end guard and arms a completion contract,
- a low-risk decision intercept that chooses reversible defaults, and
- a ``Stop`` guard that requires a non-vacuous change plus a passing repository
  verifier before Claude can claim completion.

The session switch (``onmc wrap on/off/toggle``) controls whether the
deep-wrap lifecycle hooks engage.  When off, all hooks exit 0 silently.
When on (or ``default_active: true`` in the wrap state), the full control
plane is active: memory-grounded prompts, task intercept, telemetry, and
pre-compact snapshots.

The ``/onmc`` Claude Code slash command is installed by ``onmc wrap`` and calls
``onmc wrap toggle`` so the user can flip the control plane from within Claude
Code with a single keystroke.

``onmc unwrap`` is the perfect inverse: it removes exactly what ``wrap`` added
(hooks, state file, CLAUDE.md stanza, and the /onmc slash command), leaving
every other hook untouched.

The decision logic lives in :mod:`oh_no_my_claudecode.wrap.logic` and is built
to never raise — a wrapper that bricks Claude Code is unacceptable.
"""

from __future__ import annotations

from oh_no_my_claudecode.wrap.logic import (
    compile_decision_intercept,
    compile_prompt_policy,
    compile_task_intercept,
    swarm_active,
)
from oh_no_my_claudecode.wrap.session import (
    is_active,
    read_default_active,
    session_active_path,
    set_active,
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
    "compile_decision_intercept",
    "compile_task_intercept",
    "is_active",
    "read_default_active",
    "read_wrap_strict",
    "remove_claude_md_stanza",
    "remove_wrap_state",
    "session_active_path",
    "set_active",
    "swarm_active",
    "upsert_claude_md_stanza",
    "write_wrap_state",
]
