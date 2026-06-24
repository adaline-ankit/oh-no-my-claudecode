"""Export onmc skills as Agent Skills SKILL.md files (agentskills.io open standard).

The open-standard layout is::

    <out_dir>/<slug>/SKILL.md

where ``<slug>`` is a valid lowercase-hyphen directory name derived from the
skill's name.  SKILL.md contains a YAML frontmatter block followed by the
skill body and a provenance footer.

Supported by 16+ tools: Claude Code, Cursor, Codex, Gemini, Copilot, OpenCode,
Goose, Letta, Hermes, and more (agentskills.io).

Public API
----------
- :func:`skill_slug`    — derive a valid, dedup-safe slug from a skill's name.
- :func:`render_skill_md` — render a single SKILL.md string (pure, no I/O).
- :func:`export_skills`   — write ``<out_dir>/<slug>/SKILL.md`` for each skill.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oh_no_my_claudecode.models.skill import Skill

# Combined description + when_to_use is truncated at this character limit
# (agentskills.io spec §2 — some tools index only this many chars).
_DESC_CHAR_CAP = 1536

# Maximum slug length to keep directory names filesystem-friendly.
_SLUG_MAX_LEN = 48


def skill_slug(skill: Skill, *, existing: set[str] | None = None) -> str:
    """Return a valid lowercase-hyphen slug for *skill*.

    The slug is derived from the skill's ``name`` field.  If *existing* is
    supplied and the derived slug collides, a short suffix from the skill ``id``
    is appended to make it unique.

    Parameters
    ----------
    skill:
        The skill to derive a slug from.
    existing:
        Optional set of already-allocated slugs.  When the derived slug
        collides, ``"--" + skill.id[-6:]`` is appended.

    Returns
    -------
    str
        A non-empty lowercase-hyphen slug safe for use as a directory name.
    """
    raw = re.sub(r"[^a-z0-9]+", "-", skill.name.lower()).strip("-")
    if not raw:
        raw = "skill"
    slug = raw[:_SLUG_MAX_LEN].strip("-") or "skill"

    if existing is not None and slug in existing:
        suffix = re.sub(r"[^a-z0-9]", "", skill.id.lower())[-6:] or "x"
        candidate = f"{slug[:_SLUG_MAX_LEN - 7]}-{suffix}".strip("-")
        slug = candidate or slug

    return slug


def render_skill_md(skill: Skill) -> str:
    """Render a SKILL.md string for *skill* (pure — no filesystem side-effects).

    Format
    ------
    ::

        ---
        name: <display name>
        description: <description text, truncated at _DESC_CHAR_CAP combined>
        when_to_use: <trigger text>
        paths: <comma-separated files globs>      # omitted when skill.files is empty
        ---

        <skill body>

        _Learned by onmc from <repo> · confidence X.XX_

    YAML escaping
    -------------
    ``name``, ``description``, and ``when_to_use`` are written as YAML block
    scalars when they contain special characters; otherwise as plain scalars.
    ``paths`` is always written as a plain inline comma-separated string.

    Parameters
    ----------
    skill:
        The skill to render.

    Returns
    -------
    str
        Full SKILL.md content with YAML frontmatter and markdown body.
    """
    name_yaml = _yaml_scalar("name", skill.name)
    description, when_to_use = _cap_description(skill.trigger, skill.trigger)
    # Use the trigger as description (what-it-does / when-to-invoke) — the
    # body carries the actionable know-how.  Prefer skill.name for description
    # when trigger is very short, but always write when_to_use from trigger.
    description = skill.name
    combined = f"{description} {skill.trigger}"
    if len(combined) > _DESC_CHAR_CAP:
        # Truncate description so that combined stays within cap.
        budget = _DESC_CHAR_CAP - len(skill.trigger) - 1  # 1 for the space
        description = description[:max(0, budget)].rstrip()

    desc_yaml = _yaml_scalar("description", description)
    when_yaml = _yaml_scalar("when_to_use", skill.trigger)

    frontmatter_lines = [
        "---",
        name_yaml,
        desc_yaml,
        when_yaml,
    ]

    if skill.files:
        paths_value = ", ".join(skill.files)
        frontmatter_lines.append(f"paths: {paths_value}")

    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines)

    confidence_str = f"{skill.confidence:.2f}"
    provenance = f"_Learned by onmc · confidence {confidence_str}_"

    body = skill.body.strip()
    return f"{frontmatter}\n\n{body}\n\n{provenance}\n"


def export_skills(
    skills: list[Skill],
    out_dir: Path,
) -> list[Path]:
    """Write one ``<out_dir>/<slug>/SKILL.md`` per skill (idempotent).

    Each skill gets its own subdirectory named after its slug.  Existing
    files with identical content are not re-written (idempotent).

    Parameters
    ----------
    skills:
        The skills to export.  An empty list produces no output.
    out_dir:
        Base directory; created (with parents) if it does not exist.

    Returns
    -------
    list[Path]
        Paths of every SKILL.md file that was written (may be empty).
    """
    if not skills:
        return []

    out_dir.mkdir(parents=True, exist_ok=True)

    allocated: set[str] = set()
    written: list[Path] = []

    for skill in skills:
        slug = skill_slug(skill, existing=allocated)
        allocated.add(slug)

        skill_dir = out_dir / slug
        skill_dir.mkdir(parents=True, exist_ok=True)

        dest = skill_dir / "SKILL.md"
        content = render_skill_md(skill)

        if dest.exists() and dest.read_text(encoding="utf-8") == content:
            # Idempotent — same content, no re-write needed.
            continue

        dest.write_text(content, encoding="utf-8")
        written.append(dest)

    return written


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cap_description(description: str, when_to_use: str) -> tuple[str, str]:
    """Truncate *description* so that ``description + ' ' + when_to_use``
    fits within ``_DESC_CHAR_CAP`` characters.

    Returns the (possibly truncated) description and the unchanged
    *when_to_use* string.
    """
    combined = f"{description} {when_to_use}"
    if len(combined) <= _DESC_CHAR_CAP:
        return description, when_to_use
    budget = _DESC_CHAR_CAP - len(when_to_use) - 1
    return description[:max(0, budget)].rstrip(), when_to_use


def _yaml_scalar(key: str, value: str) -> str:
    """Return a YAML key: value line, quoting *value* when necessary.

    Quoting is applied when the value:
    - starts or ends with whitespace
    - contains a colon followed by a space (``:``)
    - contains a double-quote character
    - starts with a YAML indicator character (``[``, ``{``, ``>``, ``|``,
      ``&``, ``*``, ``!``, ``%``, ``@``, `` `` `)

    Uses double-quote escaping (replace ``"`` with ``\\"``).
    """
    yaml_indicators = set('[{>|&*!%@`')
    needs_quoting = (
        value != value.strip()
        or ": " in value
        or '"' in value
        or (bool(value) and value[0] in yaml_indicators)
    )
    if needs_quoting:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}: "{escaped}"'
    return f"{key}: {value}"
