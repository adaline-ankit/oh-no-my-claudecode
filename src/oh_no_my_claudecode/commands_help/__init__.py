"""Help tiering for ``onmc`` — groups all commands into human categories.

Exposed as the ``onmc commands`` CLI surface (auto-discovered via
:mod:`oh_no_my_claudecode.command_registry`).  Pure-logic helpers live in
:mod:`oh_no_my_claudecode.commands_help.core` so they can be tested without
Typer or the rest of the CLI.
"""
