"""``onmc contract`` — spec-as-contract test generator.

Given an interface spec (JSON: ``name``, ``summary``, ``signature``,
``cases: [{given, expect}]``), emit a *failing* pytest skeleton plus a stub
module that raises :class:`NotImplementedError`. The agent's job then reduces to
"make the tests green".

The name is ``contract`` (not ``spec`` — that subcommand is already taken).

This package self-registers its CLI surface via the auto-discovery hook
(:mod:`oh_no_my_claudecode.command_registry`); adding it touched no shared hub
(``cli.py``, ``core/service.py``, ``rendering/console.py``).
"""

from __future__ import annotations

from oh_no_my_claudecode.contract.generator import (
    ContractSpecError,
    GeneratedContract,
    generate_contract,
)

__all__ = [
    "ContractSpecError",
    "GeneratedContract",
    "generate_contract",
]
