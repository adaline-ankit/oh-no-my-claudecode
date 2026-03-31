from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.ingest.docs import is_primarily_english, is_structural_heading
from oh_no_my_claudecode.llm import MarkdownEnvelope, generate_structured_logged
from oh_no_my_claudecode.llm.base import BaseLLMProvider, LLMProviderError
from oh_no_my_claudecode.models import (
    LLMGenerationRequest,
    MemoryArtifactRecord,
    MemoryEntry,
    MemoryKind,
    TaskRecord,
)
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import shorten
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now

SECTION_ORDER = [
    "Project overview",
    "Critical invariants",
    "Architecture decisions",
    "Hotspot areas",
    "Known bad approaches",
    "Validation",
    "Current active tasks",
]


def claude_md_path(repo_root: Path) -> Path:
    """Return the repo CLAUDE.md path."""
    return repo_root / "CLAUDE.md"


def claude_md_meta_path(repo_root: Path) -> Path:
    """Return the CLAUDE.md metadata path inside .onmc."""
    return repo_root / ".onmc" / "claude-md-meta.json"


def load_claude_md_meta(repo_root: Path) -> dict[str, Any]:
    """Load stored CLAUDE.md metadata if it exists."""
    meta_path = claude_md_meta_path(repo_root)
    if not meta_path.exists():
        return {}
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def generate_claude_md(
    *,
    repo_root: Path,
    storage: SQLiteStorage,
    provider: BaseLLMProvider | None,
    log_path: Path | None,
    write: bool = True,
) -> tuple[str, dict[str, str]]:
    """Generate CLAUDE.md markdown and optionally write it to disk."""
    sections = build_claude_md_markdown(
        repo_root=repo_root,
        storage=storage,
        provider=provider,
        log_path=log_path,
    )
    section_hashes = _section_hashes(repo_root, storage)
    markdown = _join_sections(sections)
    if write:
        claude_md_path(repo_root).write_text(markdown, encoding="utf-8")
        claude_md_meta_path(repo_root).write_text(
            json.dumps(
                {
                    "generated_at": isoformat_utc(utc_now()),
                    "section_hashes": section_hashes,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return markdown, section_hashes


def build_claude_md_markdown(
    *,
    repo_root: Path,
    storage: SQLiteStorage,
    provider: BaseLLMProvider | None,
    log_path: Path | None,
) -> dict[str, str]:
    """Build CLAUDE.md sections from stored memory, optionally with LLM assistance."""
    memories = storage.list_memories()
    claude_md_memories = filter_for_claude_md(memories)
    artifacts = storage.list_memory_artifacts()
    active_tasks = [task for task in storage.list_tasks() if task.status.value == "active"]
    if provider is not None and log_path is not None:
        try:
            envelope = generate_structured_logged(
                provider,
                request=_generation_request(claude_md_memories, artifacts, active_tasks),
                response_model=MarkdownEnvelope,
                log_path=log_path,
                operation="claude_md.generate",
            )
            parsed = _parse_sections(envelope.markdown)
            if parsed:
                return parsed
        except LLMProviderError:
            pass
    return _deterministic_sections(claude_md_memories, artifacts, active_tasks)


def _generation_request(
    memories: list[MemoryEntry],
    artifacts: list[MemoryArtifactRecord],
    active_tasks: list[TaskRecord],
) -> LLMGenerationRequest:
    payload = {
        "memories": [
            {
                "id": memory.id,
                "kind": memory.kind.value,
                "title": memory.title,
                "summary": memory.summary,
                "source_ref": memory.source_ref,
                "confidence": memory.confidence,
            }
            for memory in memories[:80]
        ],
        "artifacts": [
            {
                "memory_id": artifact.memory_id,
                "type": artifact.type.value,
                "title": artifact.title,
                "summary": artifact.summary,
                "task_id": artifact.task_id,
            }
            for artifact in artifacts[:40]
        ],
        "active_tasks": [
            {
                "task_id": task.task_id,
                "title": task.title,
                "description": task.description,
            }
            for task in active_tasks[:10]
        ],
    }
    prompt = (
        "You are writing a CLAUDE.md for a coding agent.\n\n"
        "Rules:\n"
        "- Write in your own words. Do not copy text from the memory records.\n"
        "- Be specific to this codebase. Generic advice is useless.\n"
        "- Each bullet must be actionable — it must change how the agent behaves.\n"
        "- Omit any section that has no supporting records.\n"
        "- Do not write placeholder text like \"No X recorded yet\".\n"
        "- Maximum 600 tokens total.\n"
        "- English only.\n\n"
        "The output should explain the current repo reality, not restate documentation structure.\n"
        "Use the memory records as source material, not as text to reproduce.\n\n"
        "Return valid JSON with a single key named `markdown`.\n\n"
        "Memory records (use as source material, do not reproduce):\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}"
    )
    return LLMGenerationRequest(
        system_prompt=(
            "Return only valid JSON. Do not use markdown fences. "
            "The markdown must be concise, synthesized, and repo-specific."
        ),
        prompt=prompt,
        temperature=0.0,
        max_tokens=1600,
    )


def _deterministic_sections(
    memories: list[MemoryEntry],
    artifacts: list[MemoryArtifactRecord],
    active_tasks: list[TaskRecord],
) -> dict[str, str]:
    grouped = {
        "Project overview": _project_overview(memories),
        "Critical invariants": _bullets(
            [
                f"{memory.title}: {memory.summary}"
                for memory in memories
                if memory.kind.value == "invariant"
            ],
        ),
        "Architecture decisions": _bullets(
            [
                f"{memory.title}: {memory.summary}"
                for memory in memories
                if memory.kind.value == "decision"
            ],
        ),
        "Hotspot areas": _bullets(
            [
                f"{memory.title}: {memory.summary}"
                for memory in memories
                if memory.kind.value == "hotspot"
            ],
        ),
        "Known bad approaches": _bullets(
            [
                f"{artifact.title}: {artifact.summary}"
                for artifact in artifacts
                if artifact.type.value in {"did_not_work", "design_conflict"}
            ]
            + [
                f"{memory.title}: {memory.summary}"
                for memory in memories
                if memory.kind.value in {"failed_approach", "design_conflict", "gotcha"}
            ],
        ),
        "Validation": _bullets(
            [
                f"{memory.title}: {memory.summary}"
                for memory in memories
                if memory.kind.value == "validation_rule"
            ],
        ),
        "Current active tasks": _bullets(
            [
                f"{task.title}: {shorten(task.description, max_length=100)}"
                for task in active_tasks
            ],
        ),
    }
    return {heading: content for heading, content in grouped.items() if content.strip()}


def _project_overview(memories: list[MemoryEntry]) -> str:
    candidates = [
        memory.summary
        for memory in memories
        if memory.kind == MemoryKind.DOC_FACT
    ]
    if not candidates:
        return ""
    return " ".join(candidates[:3])


def _bullets(items: list[str]) -> str:
    if not items:
        return ""
    return "\n".join(f"- {item}" for item in items[:6])


def _join_sections(sections: dict[str, str]) -> str:
    lines = ["# CLAUDE.md", ""]
    for heading in SECTION_ORDER:
        content = sections.get(heading, "").strip()
        if not content:
            continue
        lines.extend([f"## {heading}", content, ""])
    return "\n".join(lines).strip() + "\n"


def _parse_sections(markdown: str) -> dict[str, str]:
    current: str | None = None
    sections: dict[str, list[str]] = {}
    for line in markdown.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return {
        heading: "\n".join(lines).strip()
        for heading, lines in sections.items()
        if heading in SECTION_ORDER
    }


def _section_hashes(repo_root: Path, storage: SQLiteStorage) -> dict[str, str]:
    payload = {
        "memories": [memory.model_dump(mode="json") for memory in storage.list_memories()],
        "artifacts": [
            artifact.model_dump(mode="json") for artifact in storage.list_memory_artifacts()
        ],
        "tasks": [task.model_dump(mode="json") for task in storage.list_tasks()],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return dict.fromkeys(SECTION_ORDER, digest)


def filter_for_claude_md(memories: list[MemoryEntry]) -> list[MemoryEntry]:
    """Filter memory records down to high-signal inputs for CLAUDE.md generation."""
    filtered: list[MemoryEntry] = []
    for memory in memories:
        if memory.feedback_score < -0.3:
            continue
        if memory.confidence < 0.6:
            continue
        if not is_primarily_english(memory.summary):
            continue
        if is_structural_heading(memory.title):
            continue
        if memory.kind == MemoryKind.DOC_FACT:
            continue
        filtered.append(memory)
    overview_candidates = [
        memory
        for memory in memories
        if memory.kind == MemoryKind.DOC_FACT
        and memory.confidence >= 0.6
        and memory.feedback_score >= -0.3
        and is_primarily_english(memory.summary)
        and not is_structural_heading(memory.title)
    ][:2]
    return [*overview_candidates, *filtered]
