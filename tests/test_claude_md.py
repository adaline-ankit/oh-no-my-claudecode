from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.claude_md import (
    claude_md_meta_path,
    claude_md_path,
    generate_claude_md,
    preview_claude_md_update,
    update_claude_md,
)
from oh_no_my_claudecode.core.service import OnmcService


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
