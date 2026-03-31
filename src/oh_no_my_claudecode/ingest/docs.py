from __future__ import annotations

import re
from pathlib import Path

from oh_no_my_claudecode.core.repo import relative_path
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.utils.text import shorten, stable_id, tokenize, unique_preserve
from oh_no_my_claudecode.utils.time import utc_now

EXCLUDED_DOC_PATTERNS = [
    r"README\.[a-z]{2}(?:-[A-Z]{2})?\.md$",
    r"CHANGELOG\.[a-z]{2}(?:-[A-Z]{2})?\.md$",
    r"CONTRIBUTING\.[a-z]{2}(?:-[A-Z]{2})?\.md$",
]
OUTPUT_FILES = {"CLAUDE.md", "AGENTS.md", ".cursorrules"}
TOC_PATTERNS = [
    r"^table of contents$",
    r"^contents$",
    r"^index$",
    r"^\d+\.\s",
    r"^overview$",
    r"^introduction$",
    r"^installation$",
    r"^usage$",
    r"^license$",
    r"^contributing$",
]


def discover_doc_paths(repo_root: Path, *, globs: list[str]) -> list[Path]:
    discovered: set[Path] = set()
    for pattern in globs:
        discovered.update(repo_root.glob(pattern))
    return sorted(
        path
        for path in discovered
        if path.is_file() and ".onmc" not in path.parts and should_ingest_doc_path(path)
    )


def is_primary_doc(path: Path) -> bool:
    """Return False for translated variants of primary docs."""
    name = path.name
    return not any(re.search(pattern, name) for pattern in EXCLUDED_DOC_PATTERNS)


def should_ingest_doc_path(path: Path) -> bool:
    """Return whether the doc path should be ingested into ONMC memory."""
    if path.name in OUTPUT_FILES:
        return False
    return is_primary_doc(path)


def extract_doc_memories(repo_root: Path, doc_path: Path, *, max_chars: int) -> list[MemoryEntry]:
    content = doc_path.read_text(encoding="utf-8")
    sections = split_markdown_sections(content)
    relative = relative_path(repo_root, doc_path)
    now = utc_now()
    memories: list[MemoryEntry] = []

    for heading, body in sections[:10]:
        text = body.strip()
        if len(text) < 40:
            continue
        clipped = text[:max_chars].strip()
        kind = classify_doc_section(heading, clipped)
        title = f"{doc_path.name}: {heading or 'Overview'}"
        summary = shorten(clipped, max_length=160)
        tags = unique_preserve(tokenize(relative) + tokenize(heading))
        confidence = doc_confidence(kind, clipped)
        if not is_primarily_english(summary):
            confidence = 0.0
        memories.append(
            MemoryEntry(
                id=stable_id(relative, heading, summary, prefix=kind.value),
                kind=kind,
                title=title,
                summary=summary,
                details=clipped,
                source_type=SourceType.DOC,
                source_ref=relative,
                tags=tags[:8],
                confidence=confidence,
                created_at=now,
                updated_at=now,
            )
        )
    return memories


def split_markdown_sections(content: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = "Overview"
    current_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith("#"):
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line.lstrip("#").strip() or "Overview"
            current_lines = []
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))
    return [(heading, body) for heading, body in sections if body.strip()]


def classify_doc_section(heading: str, body: str) -> MemoryKind:
    text = f"{heading}\n{body}".lower()
    invariant_keywords = ("do not", "don't", "never", "must", "always", "required")
    validation_keywords = ("test", "lint", "typecheck", "validate", "ci", "check")
    decision_keywords = (
        "decision",
        "rationale",
        "trade-off",
        "tradeoff",
        "architecture",
        "we use",
        "we chose",
    )

    if is_structural_heading(heading):
        return MemoryKind.DOC_FACT
    if any(keyword in text for keyword in invariant_keywords):
        if any(keyword in text for keyword in validation_keywords):
            return MemoryKind.VALIDATION_RULE
        return MemoryKind.INVARIANT
    if any(keyword in text for keyword in decision_keywords):
        return MemoryKind.DECISION
    return MemoryKind.DOC_FACT


def doc_confidence(kind: MemoryKind, body: str) -> float:
    base = {
        MemoryKind.DOC_FACT: 0.55,
        MemoryKind.DECISION: 0.7,
        MemoryKind.INVARIANT: 0.75,
        MemoryKind.VALIDATION_RULE: 0.75,
        MemoryKind.HOTSPOT: 0.5,
        MemoryKind.GIT_PATTERN: 0.5,
    }[kind]
    if len(body) > 300:
        return min(base + 0.05, 0.95)
    return base


def is_structural_heading(title: str) -> bool:
    """Return whether a heading is structural boilerplate rather than repo knowledge."""
    normalized = title.lower().strip()
    return any(re.match(pattern, normalized) for pattern in TOC_PATTERNS)


def is_primarily_english(text: str) -> bool:
    """Return False when non-ASCII content dominates the supplied text."""
    if not text:
        return True
    non_ascii = sum(1 for char in text if ord(char) > 127)
    return (non_ascii / max(len(text), 1)) < 0.3
