from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, Field, RootModel

from oh_no_my_claudecode.llm import generate_structured_logged
from oh_no_my_claudecode.llm.base import BaseLLMProvider, LLMProviderError
from oh_no_my_claudecode.models import (
    LLMGenerationRequest,
    MemoryEntry,
    MemoryKind,
    ProjectConfig,
    RepoFileRecord,
    SourceType,
)
from oh_no_my_claudecode.utils.text import stable_id, tokenize
from oh_no_my_claudecode.utils.time import utc_now

COMMIT_BATCH_SIZE = 50
MAX_COMMIT_BATCHES = 10
MAX_SOURCE_FILES = 20


class ExtractedKnowledgeItem(BaseModel):
    kind: str
    title: str
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_commits: list[str] = Field(default_factory=list)
    files_mentioned: list[str] = Field(default_factory=list)


class ExtractedKnowledgeList(RootModel[list[ExtractedKnowledgeItem]]):
    pass


def batch_commits_for_llm(
    commit_lines: list[str],
    batch_size: int = COMMIT_BATCH_SIZE,
) -> list[str]:
    """Group commit lines into stable prompt-sized batches."""
    batches: list[str] = []
    for index in range(0, len(commit_lines), batch_size):
        chunk = commit_lines[index : index + batch_size]
        if chunk:
            batches.append("\n".join(chunk))
    return batches[:MAX_COMMIT_BATCHES]


def extract_llm_memories(
    *,
    repo_root: Path,
    config: ProjectConfig,
    provider: BaseLLMProvider,
    log_path: Path,
    commit_lines: list[str],
    docs: dict[str, str],
    existing_memories: list[MemoryEntry],
    repo_files: list[RepoFileRecord] | None = None,
    git_churn_rank: list[str] | None = None,
) -> tuple[list[MemoryEntry], int]:
    """Extract structured repo memory from commits and docs using the configured LLM."""
    commit_extracted: list[MemoryEntry] = []
    extracted: list[MemoryEntry] = []
    deduped = 0
    for batch_index, batch in enumerate(batch_commits_for_llm(commit_lines), start=1):
        try:
            payload = generate_structured_logged(
                provider,
                LLMGenerationRequest(
                    system_prompt=(
                        "Return only valid JSON that matches the provided schema. "
                        "Do not include markdown fences."
                    ),
                    prompt=_commit_prompt(batch),
                    temperature=0.0,
                    max_tokens=min(config.llm.max_tokens * 2, 2400),
                ),
                ExtractedKnowledgeList,
                log_path=log_path,
                operation=f"ingest.commits.batch_{batch_index}",
            )
        except LLMProviderError:
            continue
        commit_extracted.extend(
            _items_to_memories(
                payload.root,
                repo_root=repo_root,
                source_ref_prefix="commit",
            )
        )
    extracted.extend(commit_extracted)

    for doc_path, content in docs.items():
        try:
            payload = generate_structured_logged(
                provider,
                LLMGenerationRequest(
                    system_prompt=(
                        "Return only valid JSON that matches the provided schema. "
                        "Do not include markdown fences."
                    ),
                    prompt=_doc_prompt(doc_path, content),
                    temperature=0.0,
                    max_tokens=min(config.llm.max_tokens * 2, 2400),
                ),
                ExtractedKnowledgeList,
                log_path=log_path,
                operation=f"ingest.doc.{doc_path}",
            )
        except LLMProviderError:
            continue
        extracted.extend(
            _items_to_memories(
                payload.root,
                repo_root=repo_root,
                source_ref_prefix=doc_path,
            )
        )

    if (
        should_run_source_extraction(len(commit_extracted))
        and repo_files is not None
        and git_churn_rank is not None
    ):
        extracted.extend(
            _extract_source_file_memories(
                repo_root=repo_root,
                config=config,
                provider=provider,
                log_path=log_path,
                repo_files=repo_files,
                git_churn_rank=git_churn_rank,
            )
        )

    deduped_entries: list[MemoryEntry] = []
    for entry in extracted:
        if _is_semantic_duplicate(entry, [*existing_memories, *deduped_entries]):
            deduped += 1
            continue
        deduped_entries.append(entry)
    return deduped_entries, deduped


def _items_to_memories(
    items: Iterable[ExtractedKnowledgeItem],
    *,
    repo_root: Path,
    source_ref_prefix: str,
) -> list[MemoryEntry]:
    now = utc_now()
    memories: list[MemoryEntry] = []
    for item in items:
        if item.confidence < 0.7:
            continue
        kind = _memory_kind_for_item(item.kind)
        if kind is None:
            continue
        source_bits = [source_ref_prefix, *item.source_commits, *item.files_mentioned]
        source_ref = "|".join(bit for bit in source_bits if bit)[:400]
        memory_id = stable_id(
            kind.value,
            item.title,
            source_ref,
            prefix=kind.value,
        )
        memories.append(
            MemoryEntry(
                id=memory_id,
                kind=kind,
                title=item.title[:60],
                summary=item.summary,
                details=item.summary,
                source_type=SourceType.LLM_EXTRACTED,
                source_ref=source_ref or repo_root.as_posix(),
                tags=tokenize(" ".join([item.title, *item.files_mentioned]))[:8],
                confidence=item.confidence,
                created_at=now,
                updated_at=now,
            )
        )
    return memories


def _memory_kind_for_item(kind: str) -> MemoryKind | None:
    mapping = {
        "decision": MemoryKind.DECISION,
        "invariant": MemoryKind.INVARIANT,
        "validation_rule": MemoryKind.VALIDATION_RULE,
        "failed_approach": MemoryKind.FAILED_APPROACH,
        "design_conflict": MemoryKind.DESIGN_CONFLICT,
        "gotcha": MemoryKind.GOTCHA,
    }
    return mapping.get(kind)


def should_run_source_extraction(commit_memory_count: int) -> bool:
    """Return whether source-file extraction should run after commit extraction."""
    return commit_memory_count < 8


def should_extract_file(path: Path, git_churn_rank: list[str]) -> bool:
    """Return True if this file is worth sending to LLM for extraction."""
    path_text = path.as_posix()
    file_name = path.name
    path_segments = {segment.lower() for segment in path.parts}
    churn_candidates = git_churn_rank[:20]
    if (
        "test" in path_segments
        or "tests" in path_segments
        or "spec" in path_segments
        or file_name.startswith("test_")
        or file_name.endswith("_test.py")
    ):
        return True
    if path_text in churn_candidates or any(
        path_text.endswith(candidate) for candidate in churn_candidates
    ):
        return True
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    signals = [
        "TODO",
        "FIXME",
        "WARNING",
        "must ",
        "never ",
        "always ",
        "DO NOT",
        "IMPORTANT",
        "HACK",
        "XXX",
        "invariant",
    ]
    if any(signal in text for signal in signals):
        return True
    return re.search(r"\b[A-Z_]{4,}\s*=", text) is not None


def _is_semantic_duplicate(entry: MemoryEntry, existing: list[MemoryEntry]) -> bool:
    entry_tokens = set(tokenize(entry.title))
    if not entry_tokens:
        return False
    for current in existing:
        if current.kind != entry.kind:
            continue
        current_tokens = set(tokenize(current.title))
        if not current_tokens:
            continue
        overlap = len(entry_tokens & current_tokens) / max(len(entry_tokens), len(current_tokens))
        if overlap >= 0.6:
            return True
    return False


def _extract_source_file_memories(
    *,
    repo_root: Path,
    config: ProjectConfig,
    provider: BaseLLMProvider,
    log_path: Path,
    repo_files: list[RepoFileRecord],
    git_churn_rank: list[str],
) -> list[MemoryEntry]:
    selected_paths = [
        repo_root / record.path
        for record in repo_files
        if should_extract_file(repo_root / record.path, git_churn_rank)
    ][:MAX_SOURCE_FILES]
    memories: list[MemoryEntry] = []
    for path in selected_paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = generate_structured_logged(
                provider,
                LLMGenerationRequest(
                    system_prompt=(
                        "Return only valid JSON that matches the provided schema. "
                        "Do not include markdown fences."
                    ),
                    prompt=_source_file_prompt(
                        path.relative_to(repo_root).as_posix(),
                        path.read_text(encoding="utf-8", errors="ignore")[:8_000],
                    ),
                    temperature=0.0,
                    max_tokens=min(config.llm.max_tokens * 2, 1800),
                ),
                ExtractedKnowledgeList,
                log_path=log_path,
                operation=f"ingest.source.{path.relative_to(repo_root).as_posix()}",
            )
        except LLMProviderError:
            continue
        memories.extend(
            _items_to_memories(
                payload.root,
                repo_root=repo_root,
                source_ref_prefix=path.relative_to(repo_root).as_posix(),
            )
        )
    return memories


def _commit_prompt(commit_batch: str) -> str:
    return (
        "You are extracting structured engineering knowledge from git commit messages.\n\n"
        "For each commit, identify:\n"
        "- architectural decisions (choices made with clear rationale)\n"
        "- invariants (rules that must always hold)\n"
        "- failed approaches (things that were tried and reverted or marked as bad)\n"
        "- design conflicts (approaches rejected because they conflicted with constraints)\n"
        "- gotchas (non-obvious things that caused problems)\n\n"
        "Return ONLY a JSON array. Each object must have:\n"
        "{\n"
        '  "kind": "decision" | "invariant" | "failed_approach" | "design_conflict" | "gotcha",\n'
        '  "title": "short title under 60 chars",\n'
        '  "summary": "1-2 sentence description",\n'
        '  "confidence": 0.0-1.0,\n'
        '  "source_commits": ["<sha>", ...],\n'
        '  "files_mentioned": ["path/to/file.py", ...]\n'
        "}\n\n"
        "Only include items with confidence >= 0.7.\n"
        "Do not invent information not present in the commits.\n"
        "Return [] if nothing meaningful is found.\n\n"
        f"Commits:\n{commit_batch}"
    )


def _doc_prompt(doc_path: str, content: str) -> str:
    return (
        "You are extracting structured engineering knowledge from a project document.\n\n"
        "Extract:\n"
        "- decisions: explicit choices made "
        '(look for "we decided", "we chose", "rationale:")\n'
        "- invariants: rules that must always hold "
        '(look for "must", "never", "always", "required")\n'
        "- validation_rules: how to test or verify things "
        '(look for "run", "test", "verify", "check")\n\n'
        "Return ONLY a JSON array with the same schema as above.\n"
        "Do not include generic information present in any project.\n"
        "Only include project-specific knowledge.\n\n"
        f"Document path: {doc_path}\n"
        f"Document contents:\n{content}"
    )


def _source_file_prompt(filename: str, content: str) -> str:
    return (
        "You are extracting structured engineering knowledge from source code.\n\n"
        "Look for:\n"
        "- invariants: rules that must always hold (from comments with \"must\", "
        "\"never\", \"always\", ALL_CAPS constants, assertion comments)\n"
        "- gotchas: non-obvious things that cause problems (TODO/FIXME comments, WARNING "
        "blocks, \"DO NOT\" comments)\n"
        "- validation_rules: how to verify correctness (test function names, assertion "
        "patterns)\n"
        "- decisions: architectural choices visible from code structure and comments\n\n"
        "Return ONLY a JSON array. Each item:\n"
        "{\n"
        '  "kind": "invariant" | "gotcha" | "validation_rule" | "decision",\n'
        '  "title": "under 60 chars",\n'
        '  "summary": "1-2 sentences",\n'
        '  "confidence": 0.0-1.0,\n'
        '  "files_mentioned": ["path/to/file"]\n'
        "}\n\n"
        "Only return items with confidence >= 0.75.\n"
        "Do not include generic programming advice.\n"
        "Only include things specific to this codebase.\n"
        "Return [] if nothing specific is found.\n\n"
        f"File: {filename}\n"
        f"Content:\n{content}"
    )


def commit_lines_from_payload(commits: list[dict[str, object]] | list[object]) -> list[str]:
    """Normalize commit dictionaries into prompt lines for batching."""
    lines: list[str] = []
    for item in commits:
        if not isinstance(item, dict):
            continue
        commit_hash = str(item.get("commit_hash", "")).strip()
        subject = str(item.get("subject", "")).strip()
        files = item.get("files") or []
        file_list = ", ".join(str(value) for value in files if value)[:240]
        if commit_hash and subject:
            lines.append(f"{commit_hash} | {subject} | files: {file_list}")
    return lines
