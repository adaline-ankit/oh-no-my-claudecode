"""Generic markdown importer.

Accepts either:

- A path to a single ``.md`` file  — imported as one item.
- A path to a directory            — all ``*.md`` files inside are imported.

Each file can be imported as a **skill** (default) or a **memory** (when
``--as memory`` is passed).  The same name/kind derivation logic used by the
OMC and hermes importers is applied.

When importing as **skill**: each file = one :class:`~oh_no_my_claudecode.models.Skill`
(name from first ``# `` heading or filename, trigger from first prose line, tagged
``imported:md``).

When importing as **memory**: each top-level ``##`` section = one
:class:`~oh_no_my_claudecode.models.MemoryEntry` (same heuristic as the hermes importer,
tagged ``imported:md``).  Files with no ``##`` sections become a single entry.

No DB access — pure parsing.
"""

from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, Skill, SourceType
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

# Reuse the parsing helpers from the specialised importers.
from . import hermes as _hermes_parser
from . import omc as _omc_parser

_IMPORT_TAG = "imported:md"


def _skill_from_file(path: Path) -> Skill:
    """Parse one .md file into a Skill tagged ``imported:md``."""
    body = path.read_text(encoding="utf-8")
    name = _omc_parser._derive_name(body, path.stem)
    trigger = _omc_parser._derive_trigger(body, name)
    now = utc_now()
    return Skill(
        id=stable_id("md", path.stem, body[:256], prefix="skill"),
        name=name,
        body=body,
        trigger=trigger,
        tags=[_IMPORT_TAG],
        files=[],
        source_memory_ids=[],
        confidence=0.5,
        created_at=now,
        updated_at=now,
    )


def _memories_from_file(path: Path) -> list[MemoryEntry]:
    """Parse one .md file into MemoryEntry objects tagged ``imported:md``."""
    text = path.read_text(encoding="utf-8")
    entries: list[MemoryEntry] = []
    for title, body in _hermes_parser._sections(text):
        if not body:
            continue
        kind = _hermes_parser._infer_kind(title) if title else MemoryKind.DOC_FACT
        summary = body[:200].strip()
        now = utc_now()
        entry = MemoryEntry(
            id=stable_id("md", path.stem, title, body[:128], prefix="mem"),
            kind=kind,
            title=title or path.stem,
            summary=summary,
            details=body,
            source_type=SourceType.MANUAL_SEED,
            source_ref=str(path),
            tags=[_IMPORT_TAG],
            confidence=0.6,
            feedback_score=0.0,
            created_at=now,
            updated_at=now,
        )
        entries.append(entry)
    return entries


def resolve_md_paths(path: Path) -> list[Path]:
    """Return the .md files to import from *path*.

    - If *path* is a file: ``[path]``
    - If *path* is a directory: all ``*.md`` files inside (sorted).

    Raises :exc:`FileNotFoundError` when *path* does not exist or no .md files
    are found in a directory.
    """
    if path.is_file():
        return [path]
    if path.is_dir():
        files = sorted(path.glob("*.md"))
        if not files:
            msg = f"No .md files found in directory: {path}"
            raise FileNotFoundError(msg)
        return files
    msg = f"Path not found: {path}"
    raise FileNotFoundError(msg)


def parse_as_skills(files: list[Path]) -> list[Skill]:
    """Parse *files* as skills."""
    skills: list[Skill] = []
    seen: set[str] = set()
    for f in files:
        sk = _skill_from_file(f)
        if sk.id not in seen:
            seen.add(sk.id)
            skills.append(sk)
    return skills


def parse_as_memories(files: list[Path]) -> list[MemoryEntry]:
    """Parse *files* as memories."""
    memories: list[MemoryEntry] = []
    seen: set[str] = set()
    for f in files:
        for entry in _memories_from_file(f):
            if entry.id not in seen:
                seen.add(entry.id)
                memories.append(entry)
    return memories
