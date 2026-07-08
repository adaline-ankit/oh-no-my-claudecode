"""onmc crews — optional CrewAI interop.

Provides two capabilities:

- ``plan_to_crew_spec`` (pure, zero extras required): convert an onmc mission
  plan or swarm manifest into a portable CrewAI crew specification dict.
- ``run_crew`` (requires ``[crewai]`` extra): execute a crew spec as an onmc
  execution backend, wrapping the outcome in an accountability receipt.

Install the optional extra to enable ``run_crew``::

    pip install "oh-no-my-claudecode[crewai]"

Without the extra, ``plan_to_crew_spec`` and ``crewai_available`` work
normally; ``run_crew`` raises a clear ``ImportError``-based error.
"""

from __future__ import annotations

from oh_no_my_claudecode.crews.interop import (
    CrewRunReceipt,
    crewai_available,
    plan_to_crew_spec,
    run_crew,
)

__all__ = [
    "CrewRunReceipt",
    "crewai_available",
    "plan_to_crew_spec",
    "run_crew",
]
