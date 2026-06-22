"""Hermes agent context importer.

Nous hermes-agent stores its knowledge in two files:

- ``MEMORY.md`` — project/session knowledge, split on ``##`` headings.
- ``USER.md``   — user preferences and cross-repo facts.

Each top-level ``##`` section becomes one :class:`~oh_no_my_claudecode.models.MemoryEntry`.
The section heading becomes the ``title``; the section body becomes both ``summary``
(first 200 chars) and ``details`` (full body).  Sections without a ``##`` heading (bare
preamble content before the first heading) are grouped as a single entry titled after
the source filename.

Heuristic kind mapping (applied to the heading text, case-insensitive):

- contains "decision" → :attr:`MemoryKind.DECISION`
- contains "invariant" or "rule" → :attr:`MemoryKind.INVARIANT`
- contains "hotspot" or "churn" → :attr:`MemoryKind.HOTSPOT`
- contains "gotcha" or "warning" or "caution" → :attr:`MemoryKind.GOTCHA`
- contains "pattern" → :attr:`MemoryKind.GIT_PATTERN`
- contains "conflict" → :attr:`MemoryKind.DESIGN_CONFLICT`
- contains "failed" or "avoid" → :attr:`MemoryKind.FAILED_APPROACH`
- everything else → :attr:`MemoryKind.DOC_FACT`

All imported memories get ``source_type=SourceType.MANUAL_SEED`` and are tagged
``imported:hermes``.

No DB access — pure parsing.
"""

from __future__ import annotations

import re
from pathlib import Path

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

# Splits on top-level ## headings.
_H2_RE = re.compile(r"^##\s+(.+)", re.MULTILINE)

_DEFAULT_FILES = ("MEMORY.md", "USER.md")


def _infer_kind(heading: str) -> MemoryKind:
    """Heuristically map a section heading to a :class:`MemoryKind`."""
    lower = heading.lower()
    if "decision" in lower:
        return MemoryKind.DECISION
    if "invariant" in lower or "rule" in lower:
        return MemoryKind.INVARIANT
    if "hotspot" in lower or "churn" in lower:
        return MemoryKind.HOTSPOT
    if "gotcha" in lower or "warning" in lower or "caution" in lower:
        return MemoryKind.GOTCHA
    if "pattern" in lower:
        return MemoryKind.GIT_PATTERN
    if "conflict" in lower:
        return MemoryKind.DESIGN_CONFLICT
    if "failed" in lower or "avoid" in lower:
        return MemoryKind.FAILED_APPROACH
    return MemoryKind.DOC_FACT


def _sections(text: str) -> list[tuple[str, str]]:
    """Split *text* on ``##`` headings.

    Returns ``[(title, body), ...]``.  Content before the first ``##`` is
    returned as a section with title ``""`` (caller handles empty-title case).
    """
    parts: list[tuple[str, str]] = []
    matches = list(_H2_RE.finditer(text))
    if not matches:
        # No headings — treat whole file as one section.
        return [("", text.strip())]

    preamble = text[: matches[0].start()].strip()
    if preamble:
        parts.append(("", preamble))

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        parts.append((heading, body))

    return parts


def _memory_from_section(
    title: str,
    body: str,
    *,
    source_ref: str,
) -> MemoryEntry:
    """Build one :class:`MemoryEntry` from a parsed section."""
    kind = _infer_kind(title) if title else MemoryKind.DOC_FACT
    summary = body[:200].strip()
    now = utc_now()
    return MemoryEntry(
        id=stable_id("hermes", source_ref, title, body[:128], prefix="mem"),
        kind=kind,
        title=title or source_ref,
        summary=summary,
        details=body,
        source_type=SourceType.MANUAL_SEED,
        source_ref=source_ref,
        tags=["imported:hermes"],
        confidence=0.6,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )


def resolve_hermes_files(path: Path | None, *, cwd: Path | None = None) -> list[Path]:
    """Return existing hermes context files.

    When *path* is a file, return ``[path]``.  When *path* is a directory,
    look for ``MEMORY.md`` and ``USER.md`` inside it.  When *path* is None,
    search the current working directory.

    Raises :exc:`FileNotFoundError` when no hermes files are found.
    """
    base = cwd or Path.cwd()
    if path is not None:
        if path.is_file():
            return [path]
        if path.is_dir():
            found = [path / name for name in _DEFAULT_FILES if (path / name).exists()]
            if found:
                return found
            msg = (
                f"No MEMORY.md or USER.md found in {path}.\n"
                "Pass a path to a specific file or a directory containing hermes files."
            )
            raise FileNotFoundError(msg)
        msg = f"Path not found: {path}"
        raise FileNotFoundError(msg)

    # Auto-detect in cwd.
    found = [base / name for name in _DEFAULT_FILES if (base / name).exists()]
    if not found:
        msg = (
            "No hermes context files found.\n"
            "Expected 'MEMORY.md' or 'USER.md' in the current directory.\n"
            "Pass an explicit path: onmc import hermes <path>"
        )
        raise FileNotFoundError(msg)
    return found


def parse(files: list[Path]) -> list[MemoryEntry]:
    """Parse hermes context files and return :class:`MemoryEntry` objects."""
    memories: list[MemoryEntry] = []
    seen: set[str] = set()
    for md_file in files:
        text = md_file.read_text(encoding="utf-8")
        for title, body in _sections(text):
            if not body:
                continue
            entry = _memory_from_section(title, body, source_ref=md_file.name)
            if entry.id not in seen:
                seen.add(entry.id)
                memories.append(entry)
    return memories
