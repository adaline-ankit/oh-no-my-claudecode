from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.claude_md.generator import (
    SECTION_ORDER,
    _join_sections,
    _section_hashes,
    build_claude_md_markdown,
    claude_md_meta_path,
    claude_md_path,
)
from oh_no_my_claudecode.llm.base import BaseLLMProvider
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now


def preview_claude_md_update(
    *,
    repo_root: Path,
    storage: SQLiteStorage,
    provider: BaseLLMProvider | None,
    log_path: Path | None,
) -> str:
    """Return the CLAUDE.md content that would be written."""
    sections = build_claude_md_markdown(
        repo_root=repo_root,
        storage=storage,
        provider=provider,
        log_path=log_path,
    )
    return _join_sections(sections)


def update_claude_md(
    *,
    repo_root: Path,
    storage: SQLiteStorage,
    provider: BaseLLMProvider | None,
    log_path: Path | None,
    write: bool = True,
) -> tuple[str, list[str]]:
    """Update stale CLAUDE.md sections while preserving marked user-written sections."""
    target_path = claude_md_path(repo_root)
    existing_text = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    existing_sections = _parse_existing_sections(existing_text)
    fresh_sections = build_claude_md_markdown(
        repo_root=repo_root,
        storage=storage,
        provider=provider,
        log_path=log_path,
    )
    meta = _load_meta(repo_root)
    next_hashes = _section_hashes(repo_root, storage)
    section_hashes = meta.get("section_hashes")
    stale_sections = [
        heading
        for heading in SECTION_ORDER
        if not isinstance(section_hashes, dict)
        or section_hashes.get(heading) != next_hashes.get(heading)
        or (heading not in existing_sections and fresh_sections.get(heading, "").strip())
    ]
    merged: dict[str, str] = {}
    for heading in SECTION_ORDER:
        user_written, content = existing_sections.get(heading, (False, ""))
        if user_written and content:
            merged[heading] = content
            continue
        if heading in stale_sections or not content:
            merged[heading] = fresh_sections.get(heading, "")
        else:
            merged[heading] = content
    markdown = _join_sections(merged)
    if write:
        claude_md_path(repo_root).write_text(markdown, encoding="utf-8")
        claude_md_meta_path(repo_root).write_text(
            json.dumps(
                {"generated_at": isoformat_utc(utc_now()), "section_hashes": next_hashes},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return markdown, stale_sections


def _parse_existing_sections(markdown: str) -> dict[str, tuple[bool, str]]:
    sections: dict[str, tuple[bool, str]] = {}
    current: str | None = None
    current_user_written = False
    buffer: list[str] = []
    pending_user_written = False
    for line in markdown.splitlines():
        if line.strip() == "<!-- user-written -->":
            pending_user_written = True
            continue
        if line.startswith("## "):
            if current is not None:
                sections[current] = (current_user_written, "\n".join(buffer).strip())
            current = line[3:].strip()
            current_user_written = pending_user_written
            pending_user_written = False
            buffer = []
            continue
        if current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = (current_user_written, "\n".join(buffer).strip())
    return sections


def _load_meta(repo_root: Path) -> dict[str, object]:
    meta_path = claude_md_meta_path(repo_root)
    if not meta_path.exists():
        return {}
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}
