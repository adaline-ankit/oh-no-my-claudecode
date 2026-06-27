"""Self-registering demo feature for the command auto-discovery registry.

This package exists as living documentation of the auto-discovery convention
(see :mod:`oh_no_my_claudecode.command_registry`): it ships a
``registrydemo.commands`` module exposing ``register(app)`` that wires up the
``onmc registry-demo`` command — with **zero** edits to ``cli.py`` beyond the
single discovery line.

Keep this feature tiny and dependency-free; it doubles as the canonical example
new features copy from.
"""

from __future__ import annotations
