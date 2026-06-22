"""OMC skills importer.

Parses oh-my-claudecode ``.omc/skills/*.md`` files (project scope) and
``~/.omc/skills/*.md`` (user scope) and produces :class:`~oh_no_my_claudecode.models.Skill`
objects tagged ``imported:omc``.

Each ``.md`` file becomes one skill.  The skill name is derived from the first
``# `` heading found in the file; if absent, the filename stem is used.  The
trigger is the first non-blank line of the body that does not start with ``#``;
if none, a generic "when relevant" placeholder is used.

No DB access — pure parsing.
"""

from __future__ import annotations

import re
from pathlib import Path

from oh_no_my_claudecode.models import Skill
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

_HEADING_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)

# Default search paths for OMC skills (project-relative then user home).
_DEFAULT_SKILL_DIRS: tuple[str, ...] = (
    ".omc/skills",
    "~/.omc/skills",
)


def _derive_name(text: str, filename_stem: str) -> str:
    """Return the skill name: first ``# `` heading or the filename stem."""
    match = _HEADING_RE.search(text)
    if match:
        return match.group(1).strip()
    return filename_stem.replace("-", " ").replace("_", " ").strip()


def _derive_trigger(text: str, name: str) -> str:
    """Return a short trigger sentence from the first prose line after the heading."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            # Truncate to a single sentence / 120 chars.
            trigger = stripped[:120].rstrip()
            return trigger
    return f"when working with {name.lower()}"


def _skill_from_file(path: Path) -> Skill:
    """Parse one .md file into a Skill."""
    body = path.read_text(encoding="utf-8")
    name = _derive_name(body, path.stem)
    trigger = _derive_trigger(body, name)
    now = utc_now()
    return Skill(
        id=stable_id("omc", path.stem, body[:256], prefix="skill"),
        name=name,
        body=body,
        trigger=trigger,
        tags=["imported:omc"],
        files=[],
        source_memory_ids=[],
        confidence=0.5,
        created_at=now,
        updated_at=now,
    )


def resolve_omc_dirs(path: Path | None, *, cwd: Path | None = None) -> list[Path]:
    """Return existing OMC skills directories to search.

    When *path* is given it is used directly.  Otherwise the default search
    order is tried: ``<cwd>/.omc/skills`` then ``~/.omc/skills``.

    Raises :exc:`FileNotFoundError` when no directory is found.
    """
    base = cwd or Path.cwd()
    if path is not None:
        if path.is_dir():
            return [path]
        msg = f"OMC skills directory not found: {path}"
        raise FileNotFoundError(msg)

    candidates = [
        base / ".omc" / "skills",
        Path.home() / ".omc" / "skills",
    ]
    found = [d for d in candidates if d.is_dir()]
    if not found:
        msg = (
            "No OMC skills directory found.\n"
            "Expected '.omc/skills' (project) or '~/.omc/skills' (user).\n"
            "Pass an explicit path: onmc import omc <path>"
        )
        raise FileNotFoundError(msg)
    return found


def parse(dirs: list[Path]) -> list[Skill]:
    """Parse all .md files in *dirs* and return a list of :class:`Skill` objects."""
    skills: list[Skill] = []
    seen: set[str] = set()
    for d in dirs:
        for md_file in sorted(d.glob("*.md")):
            skill = _skill_from_file(md_file)
            if skill.id not in seen:
                seen.add(skill.id)
                skills.append(skill)
    return skills
