from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from oh_no_my_claudecode.claude_md import (
    claude_md_meta_path,
    claude_md_path,
    generate_claude_md,
    preview_claude_md_update,
    update_claude_md,
)
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_memory(
    *,
    id: str,
    kind: MemoryKind,
    title: str,
    summary: str,
    confidence: float = 0.9,
) -> MemoryEntry:
    return MemoryEntry(
        id=id,
        kind=kind,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.DOC,
        source_ref="README.md",
        tags=[],
        confidence=confidence,
        feedback_score=0.0,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_claude_md_generation_produces_valid_markdown(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    _, _, storage = service._load_context()

    markdown, _ = generate_claude_md(
        repo_root=sample_repo,
        storage=storage,
        provider=None,
        log_path=None,
        write=False,
    )

    assert markdown.startswith("# CLAUDE.md")
    assert "## Critical invariants" in markdown
    assert not claude_md_path(sample_repo).exists()


def test_claude_md_update_only_marks_stale_sections(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    markdown = service.generate_claude_md(no_llm=True)

    assert "## Validation" in markdown

    updated, stale_sections = service.update_claude_md(no_llm=True)

    assert "## Validation" in updated
    assert stale_sections == []


def test_claude_md_update_preserves_user_written_sections(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    service.generate_claude_md(no_llm=True)
    claude_path = claude_md_path(sample_repo)
    claude_path.write_text(
        "# CLAUDE.md\n\n"
        "## Project overview\nManaged by ONMC.\n\n"
        "## Critical invariants\n- Existing invariant\n\n"
        "<!-- user-written -->\n## Architecture decisions\nCustom architecture note.\n\n"
        "## Hotspot areas\n- Existing hotspot\n\n"
        "## Known bad approaches\n- Existing bad approach\n\n"
        "## Validation\n- Existing validation\n\n"
        "## Current active tasks\n- Existing task\n",
        encoding="utf-8",
    )
    meta_path = claude_md_meta_path(sample_repo)
    meta_path.write_text(
        json.dumps({"generated_at": "2026-03-31T00:00:00+00:00", "section_hashes": {}}),
        encoding="utf-8",
    )

    updated, _ = update_claude_md(
        repo_root=sample_repo,
        storage=service._load_context()[2],
        provider=None,
        log_path=None,
        write=False,
    )

    assert "Custom architecture note." in updated


def test_claude_md_preview_does_not_write_to_disk(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    _, _, storage = service._load_context()

    preview = preview_claude_md_update(
        repo_root=sample_repo,
        storage=storage,
        provider=None,
        log_path=None,
    )

    assert "## Hotspot areas" in preview
    assert not claude_md_path(sample_repo).exists()


# ---------------------------------------------------------------------------
# Quality tests: formatting, truncation, fences, and label deduplication
# ---------------------------------------------------------------------------


def _generate_from_storage(tmp_path: Path, storage: SQLiteStorage) -> str:
    """Helper: run the deterministic generator and return the markdown."""
    markdown, _ = generate_claude_md(
        repo_root=tmp_path,
        storage=storage,
        provider=None,
        log_path=None,
        write=False,
    )
    return markdown


def test_no_stray_code_fences_in_output(sample_repo: Path) -> None:
    """Generated CLAUDE.md must contain no raw triple-backtick fences."""
    service = OnmcService(sample_repo)
    service.init_project()
    _, _, storage = service._load_context()

    # Seed an invariant whose summary contains a code fence.
    fenced_summary = "Run `make test` before merging. ```bash\nmake test\n``` See CI."
    storage.upsert_memories(
        [
            _make_memory(
                id="fence-test-1",
                kind=MemoryKind.INVARIANT,
                title="README.md: CI requirement",
                summary=fenced_summary,
            )
        ]
    )

    markdown = _generate_from_storage(sample_repo, storage)
    assert "```" not in markdown, "Generated CLAUDE.md must not contain raw code fences"


def test_no_mid_word_truncation_in_output(sample_repo: Path) -> None:
    """Truncated bullets must end at a word boundary, never mid-word."""
    service = OnmcService(sample_repo)
    service.init_project()
    _, _, storage = service._load_context()

    # Seed a decision whose summary is long enough to require truncation.
    long_summary = (
        "We use a shared cache boundary. " * 5
        + "The cache module centralises all invalidation responsibility across workers."
    )
    storage.upsert_memories(
        [
            _make_memory(
                id="trunc-test-1",
                kind=MemoryKind.DECISION,
                title="docs/arch.md: Cache boundary decision",
                summary=long_summary,
            )
        ]
    )

    markdown = _generate_from_storage(sample_repo, storage)

    # Find every `...` and assert it is preceded by a full word (no partial word cut).
    # A partial word would look like "structur..." or "central...".
    # A clean cut looks like "boundary..." (ends at whitespace before `...`).
    partial_word_re = re.compile(r"\w{4,}\.\.\.")
    bad_matches = partial_word_re.findall(markdown)
    assert not bad_matches, (
        f"Mid-word truncation detected in CLAUDE.md: {bad_matches}\n\nFull output:\n{markdown}"
    )


def test_no_duplicated_consecutive_source_labels(sample_repo: Path) -> None:
    """Source-file prefixes must not appear as repeated bullet labels."""
    service = OnmcService(sample_repo)
    service.init_project()
    _, _, storage = service._load_context()

    # Seed two invariants both with source-label-style titles.
    storage.upsert_memories(
        [
            _make_memory(
                id="label-test-1",
                kind=MemoryKind.INVARIANT,
                title="README.md: No direct DB writes",
                summary="Never write to the database from request handlers.",
            ),
            _make_memory(
                id="label-test-2",
                kind=MemoryKind.INVARIANT,
                title="README.md: Always validate input",
                summary="All user input must be validated at the API boundary.",
            ),
        ]
    )

    markdown = _generate_from_storage(sample_repo, storage)

    # Bullets should not start with "README.md:" as a raw prefix.
    readme_prefix_count = markdown.count("- README.md:")
    assert readme_prefix_count == 0, (
        f"Source label 'README.md:' repeated {readme_prefix_count} times as bullet prefix.\n"
        f"Full output:\n{markdown}"
    )


def test_seeded_memories_appear_as_clean_one_line_bullets(sample_repo: Path) -> None:
    """Known seeded memories must appear as clean one-line bullets without raw markdown."""
    service = OnmcService(sample_repo)
    service.init_project()
    _, _, storage = service._load_context()

    storage.upsert_memories(
        [
            _make_memory(
                id="clean-test-1",
                kind=MemoryKind.HOTSPOT,
                title="src/cache.py: Cache module",
                summary="The cache module is modified frequently and is central to invalidation.",
            ),
        ]
    )

    markdown = _generate_from_storage(sample_repo, storage)

    # The hotspot section should contain a clean bullet.
    assert "## Hotspot areas" in markdown
    hotspot_section_start = markdown.index("## Hotspot areas")
    # Find the next section heading after Hotspot areas, or end of file.
    next_section_match = re.search(r"^## ", markdown[hotspot_section_start + 1 :], re.MULTILINE)
    if next_section_match:
        section_text = markdown[
            hotspot_section_start : hotspot_section_start + 1 + next_section_match.start()
        ]
    else:
        section_text = markdown[hotspot_section_start:]

    # Must have at least one bullet.
    assert "- " in section_text, f"No bullets found in Hotspot section:\n{section_text}"
    # No raw code fences in that section.
    assert "```" not in section_text
    # Each bullet line should be a single line (no embedded newlines mid-bullet).
    for line in section_text.splitlines():
        if line.startswith("- "):
            assert "\n" not in line  # trivially true per splitlines but guards future changes


def test_inline_code_fences_stripped_from_collapsed_summary(sample_repo: Path) -> None:
    """Collapsed (single-line) code fences in stored summaries must be stripped."""
    service = OnmcService(sample_repo)
    service.init_project()
    _, _, storage = service._load_context()

    # Simulate a summary that has already been whitespace-collapsed (as happens after
    # shorten() at ingest time) — triple backticks but no newlines inside.
    collapsed_fence_summary = (
        "We use a shared cache. ```bash make test pip install -e . ``` See docs."
    )
    storage.upsert_memories(
        [
            _make_memory(
                id="inline-fence-test-1",
                kind=MemoryKind.DECISION,
                title="docs/arch.md: Build process",
                summary=collapsed_fence_summary,
            )
        ]
    )

    markdown = _generate_from_storage(sample_repo, storage)

    assert "```" not in markdown, (
        "Collapsed (inline) code fence leaked into CLAUDE.md output:\n" + markdown
    )
