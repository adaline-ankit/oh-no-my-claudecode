from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.llm import MarkdownEnvelope, generate_structured_logged
from oh_no_my_claudecode.llm.base import BaseLLMProvider, LLMProviderError
from oh_no_my_claudecode.models import (
    LLMGenerationRequest,
    MemoryArtifactRecord,
    MemoryEntry,
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
    artifacts = storage.list_memory_artifacts()
    active_tasks = [task for task in storage.list_tasks() if task.status.value == "active"]
    if provider is not None and log_path is not None:
        try:
            envelope = generate_structured_logged(
                provider,
                request=_generation_request(memories, artifacts, active_tasks),
                response_model=MarkdownEnvelope,
                log_path=log_path,
                operation="claude_md.generate",
            )
            parsed = _parse_sections(envelope.markdown)
            if parsed:
                return parsed
        except LLMProviderError:
            pass
    return _deterministic_sections(memories, artifacts, active_tasks)


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
        "You are generating a CLAUDE.md file for a coding agent working on this repository.\n\n"
        "CLAUDE.md is read by the agent at the start of every session. It must be:\n"
        "- Concise (target 400-600 tokens total)\n"
        "- Specific to this codebase, not generic advice\n"
        "- Actionable — every line should change how the agent behaves\n"
        "- Honest about complexity and known pitfalls\n\n"
        "Never include generic advice like \"write clean code\" or \"add tests\".\n"
        "Only include things specific to this repo that an agent would not know "
        "from reading the code.\n\n"
        "Return valid JSON with a single key named `markdown`.\n\n"
        "Here is the structured memory for this repository:\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}"
    )
    return LLMGenerationRequest(
        system_prompt="Return only valid JSON. Do not use markdown fences.",
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
            fallback="No critical invariants have been recorded yet.",
        ),
        "Architecture decisions": _bullets(
            [
                f"{memory.title}: {memory.summary}"
                for memory in memories
                if memory.kind.value == "decision"
            ],
            fallback="No architecture decisions have been recorded yet.",
        ),
        "Hotspot areas": _bullets(
            [
                f"{memory.title}: {memory.summary}"
                for memory in memories
                if memory.kind.value == "hotspot"
            ],
            fallback="No hotspot areas have been recorded yet.",
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
            fallback="No known bad approaches have been captured yet.",
        ),
        "Validation": _bullets(
            [
                f"{memory.title}: {memory.summary}"
                for memory in memories
                if memory.kind.value == "validation_rule"
            ],
            fallback="No explicit validation guidance has been recorded yet.",
        ),
        "Current active tasks": _bullets(
            [
                f"{task.title}: {shorten(task.description, max_length=100)}"
                for task in active_tasks
            ],
            fallback="No active tasks are currently recorded.",
        ),
    }
    return grouped


def _project_overview(memories: list[MemoryEntry]) -> str:
    candidates = [
        memory.summary
        for memory in memories
        if memory.kind.value == "doc_fact"
    ]
    if not candidates:
        return "Project overview unavailable. Run `onmc ingest` to build repo memory first."
    return " ".join(candidates[:3])


def _bullets(items: list[str], *, fallback: str) -> str:
    if not items:
        return fallback
    return "\n".join(f"- {item}" for item in items[:6])


def _join_sections(sections: dict[str, str]) -> str:
    lines = ["# CLAUDE.md", ""]
    for heading in SECTION_ORDER:
        lines.extend([f"## {heading}", sections.get(heading, ""), ""])
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
