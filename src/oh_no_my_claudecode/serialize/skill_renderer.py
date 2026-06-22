"""Compact skill renderer for hook-injected and serialized output.

Format design:
  Terse (one line per skill, hook default):
    SKILL: <name> — trigger: <trigger> | steps: <truncated body>

  Verbose (multi-line, under ONMC_VERBOSE=1):
    ## Relevant skills
    **<name>** — <trigger>
      <body (truncated to budget)>

Both renderers are token-frugal and emit nothing when the skill list is empty.
"""

from __future__ import annotations

from oh_no_my_claudecode.models.skill import Skill

# Hard truncation limits for terse mode.
_TERSE_NAME_CHARS = 50
_TERSE_TRIGGER_CHARS = 80
_TERSE_BODY_CHARS = 120

# Block-level char ceiling for the full terse skills section.
_TERSE_BLOCK_CHARS = 600

# Verbose per-skill body chars.
_VERBOSE_BODY_CHARS = 300

# Max skills shown in verbose mode.
_VERBOSE_MAX = 3


def _truncate(text: str, max_chars: int) -> str:
    """Hard-truncate *text* to *max_chars*, appending '…' when cut."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def render_skills_terse(
    skills: list[Skill],
    *,
    max_items: int = 3,
) -> str:
    """Render top skills as compact terse lines.

    Returns a newline-joined string (no trailing newline) or "" when empty.
    Each line has the form:
      SKILL: <name> — <trigger> | <first step of body>
    """
    if not skills:
        return ""
    lines: list[str] = []
    for skill in skills[:max_items]:
        name = _truncate(skill.name, _TERSE_NAME_CHARS)
        trigger = _truncate(skill.trigger, _TERSE_TRIGGER_CHARS)
        # Surface first meaningful line of the body (steps).
        body_first = skill.body.split("\n")[0].strip() if skill.body else ""
        body_part = _truncate(body_first, _TERSE_BODY_CHARS) if body_first else ""
        if body_part:
            lines.append(f"SKILL: {name} — {trigger} | {body_part}")
        else:
            lines.append(f"SKILL: {name} — {trigger}")
    block = "\n".join(lines)
    return block[:_TERSE_BLOCK_CHARS]


def render_skills_verbose(
    skills: list[Skill],
    *,
    max_items: int = _VERBOSE_MAX,
) -> str:
    """Render skills in full markdown mode.

    Returns a markdown block string (with trailing newline) or "" when empty.
    """
    if not skills:
        return ""
    lines: list[str] = ["## Relevant skills", ""]
    for skill in skills[:max_items]:
        lines.append(f"**{skill.name}** — {skill.trigger}")
        body = _truncate(skill.body, _VERBOSE_BODY_CHARS)
        if body:
            lines.append(f"  {body}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
