"""onmc teams — optional AutoGen / AG2 interop.

Two capabilities:
- ``plan_to_team_spec(plan)`` — PURE, always works, no autogen needed.
  Converts an onmc mission/swarm plan dict into an AutoGen GroupChat spec.
- ``run_team(spec, *, runner)`` — runs a team spec via an INJECTABLE runner
  and writes a tamper-evident onmc receipt.  Requires the ``[autogen]`` extra
  only when the built-in ``autogen_runner`` is passed; tests inject a fake.

Check availability with ``autogen_available()`` before calling
``autogen_runner``.
"""

from __future__ import annotations

from oh_no_my_claudecode.teams.interop import (
    autogen_available,
    plan_to_team_spec,
    run_team,
)

__all__ = [
    "autogen_available",
    "plan_to_team_spec",
    "run_team",
]
