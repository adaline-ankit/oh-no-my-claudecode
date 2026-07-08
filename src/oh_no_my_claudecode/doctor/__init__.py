"""``onmc doctor`` — integration health check for Claude Code.

Diagnoses whether onmc is correctly wired into Claude Code and prints
actionable fixes, modelled after ``brew doctor``.

Auto-discovered by
:func:`oh_no_my_claudecode.command_registry.register_feature_commands` via the
``commands.register`` convention — zero edits to ``cli.py`` needed.
"""
