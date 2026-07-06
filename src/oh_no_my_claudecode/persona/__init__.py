"""Selectable agent personality presets for the ``onmc persona`` command.

Public API:

- :data:`oh_no_my_claudecode.persona.presets.PRESETS` — registry of all
  available :class:`~oh_no_my_claudecode.persona.presets.PersonaSpec` objects.
- :func:`oh_no_my_claudecode.persona.presets.get_persona` — look up a preset
  by name; raises :class:`~oh_no_my_claudecode.persona.presets.UnknownPersonaError`
  for unrecognised names.
- :func:`oh_no_my_claudecode.persona.presets.line` — deterministic line
  selection for a ``(persona, event, seed)`` triple.
"""
