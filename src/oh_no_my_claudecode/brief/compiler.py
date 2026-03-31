from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from oh_no_my_claudecode.brief.llm_ranker import rerank_memories_with_llm
from oh_no_my_claudecode.ingest.repo_tree import detect_project_hints
from oh_no_my_claudecode.llm.base import BaseLLMProvider
from oh_no_my_claudecode.models import (
    BriefArtifact,
    FileStat,
    MemoryEntry,
    MemoryKind,
    ProjectConfig,
    ProjectHints,
    RepoFileRecord,
)
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import shorten, tokenize, unique_preserve
from oh_no_my_claudecode.utils.time import utc_now

BUG_TOKENS = {"bug", "fix", "flaky", "regression", "error", "failure"}
DOC_TOKENS = {"docs", "readme", "architecture", "guide"}


def compile_brief(
    repo_root: Path,
    config: ProjectConfig,
    storage: SQLiteStorage,
    task: str,
    *,
    provider: BaseLLMProvider | None = None,
    log_path: Path | None = None,
) -> BriefArtifact:
    repo_files = storage.list_repo_files()
    file_stats = storage.list_file_stats()
    memories = storage.list_memories()
    hints = detect_project_hints(repo_root, repo_files)
    meta = storage.all_meta()

    selected_memories = score_memories(task, memories, limit=max(config.brief.max_memories, 30))
    relevance_reasons: dict[str, str] = {}
    if provider is not None and log_path is not None:
        reranked, relevance_reasons = rerank_memories_with_llm(
            task=task,
            candidates=selected_memories[:30],
            provider=provider,
            log_path=log_path,
        )
        selected_memories = reranked
    selected_memories = selected_memories[: config.brief.max_memories]
    files_to_inspect = score_files(task, repo_files, file_stats, selected_memories)
    files_to_inspect = files_to_inspect[: config.brief.max_files]
    impacted_areas = derive_impacted_areas(files_to_inspect, selected_memories)
    validation_checklist = build_validation_checklist(
        hints,
        files_to_inspect,
        repo_files,
    )
    risk_notes = build_risk_notes(selected_memories, files_to_inspect, file_stats)
    risk_notes = risk_notes[: config.brief.max_risks]
    reading_list = build_reading_list(repo_files, selected_memories, files_to_inspect)
    repo_overview = build_repo_overview(repo_files, meta, hints)
    provenance = build_provenance(selected_memories, meta)

    task_summary = (
        f"Task focus: {task}. Use stored repo memory plus the ranked files below "
        "to recover project-specific context quickly."
    )
    return BriefArtifact(
        task=task,
        generated_at=utc_now(),
        repo_root=repo_root.as_posix(),
        task_summary=shorten(task_summary, max_length=220),
        repo_overview=repo_overview,
        relevant_memories=selected_memories,
        relevance_reasons=relevance_reasons,
        impacted_areas=impacted_areas,
        files_to_inspect=files_to_inspect,
        risk_notes=risk_notes,
        validation_checklist=validation_checklist,
        reading_list=reading_list,
        provenance=provenance,
    )


def score_memories(task: str, memories: list[MemoryEntry], *, limit: int = 8) -> list[MemoryEntry]:
    task_tokens = set(tokenize(task))
    ranked: list[tuple[float, MemoryEntry]] = []
    for memory in memories:
        if memory.feedback_score <= -0.5:
            continue
        if memory.confidence <= 0.0:
            continue
        haystack_tokens = set(
            tokenize(
                " ".join(
                    [
                        memory.title,
                        memory.summary,
                        memory.details,
                        memory.source_ref,
                        " ".join(memory.tags),
                    ]
                )
            )
        )
        overlap = task_tokens & haystack_tokens
        score = float(len(overlap) * 5)
        if overlap and memory.kind in {
            MemoryKind.DECISION,
            MemoryKind.INVARIANT,
            MemoryKind.VALIDATION_RULE,
        }:
            score += 2.5
        if memory.kind == MemoryKind.HOTSPOT:
            score += 1.0
        if any(token in memory.source_ref.lower() for token in task_tokens):
            score += 2.0
        score += memory.confidence + (memory.feedback_score * 0.2)
        ranked.append((score, memory))

    ranked.sort(key=lambda item: (-item[0], item[1].title))
    top = [memory for score, memory in ranked if score > 0][:limit]
    if top:
        return top
    return [memory for _, memory in ranked[: min(limit, 5)]]


def score_files(
    task: str,
    repo_files: list[RepoFileRecord],
    file_stats: list[FileStat],
    memories: list[MemoryEntry],
) -> list[str]:
    task_tokens = set(tokenize(task))
    stats_by_path = {stat.path: stat for stat in file_stats}
    source_refs = [memory.source_ref for memory in memories]
    ranked: list[tuple[float, str]] = []

    for record in repo_files:
        score = 0.0
        path_tokens = set(tokenize(record.path))
        overlap = task_tokens & path_tokens
        score += len(overlap) * 6.0
        if any(token in record.path.lower() for token in task_tokens):
            score += 1.5
        if record.is_test and (task_tokens & BUG_TOKENS):
            score += 2.5
        if record.path.endswith(".md") and (task_tokens & DOC_TOKENS):
            score += 2.0
        if any(
            record.path.startswith(source_ref) or source_ref.startswith(record.path)
            for source_ref in source_refs
        ):
            score += 2.0

        stat = stats_by_path.get(record.path)
        if stat is not None:
            score += min(stat.change_count, 10) * 0.2
            score += min(stat.recent_change_count, 5) * 0.35

        ranked.append((score, record.path))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = [path for score, path in ranked if score > 0][:10]
    if selected:
        return selected

    fallbacks = [
        path
        for path in (
            "README.md",
            "docs/architecture.md",
            "pyproject.toml",
            *(stat.path for stat in file_stats[:4]),
        )
        if path in {record.path for record in repo_files}
    ]
    return unique_preserve(fallbacks)[:10]


def derive_impacted_areas(files_to_inspect: list[str], memories: list[MemoryEntry]) -> list[str]:
    scores: Counter[str] = Counter()
    for path in files_to_inspect:
        bucket = "/".join(path.split("/")[:2]) if "/" in path else path
        scores[bucket] += 2
    for memory in memories:
        ref = memory.source_ref.split("|")[0]
        bucket = "/".join(ref.split("/")[:2]) if "/" in ref else ref
        if bucket:
            scores[bucket] += 1
    return [area for area, _ in scores.most_common(6)]


def build_validation_checklist(
    hints: ProjectHints,
    files_to_inspect: list[str],
    repo_files: list[RepoFileRecord],
) -> list[str]:
    checklist: list[str] = []
    file_set = {record.path for record in repo_files}
    python_tools = hints.python_tools
    package_scripts = hints.package_scripts
    ci_workflows = hints.ci_workflows

    if "pytest" in python_tools:
        checklist.append("Run `pytest` for the affected area or the closest targeted subset.")
    if "ruff" in python_tools:
        checklist.append("Run `ruff check .` before finalizing changes.")
    if "mypy" in python_tools:
        checklist.append("Run `mypy src` if the task touches typed Python modules.")

    for script in package_scripts:
        if script in {"test", "lint", "typecheck", "build"}:
            checklist.append(f"Run `npm run {script}` if the impacted area includes JS/TS files.")

    for path in files_to_inspect[:4]:
        test_candidate = suggest_related_tests(path, file_set)
        if test_candidate:
            checklist.append(f"Inspect or update related tests in `{test_candidate}`.")

    if ci_workflows:
        checklist.append(
            f"Compare local validation against CI workflow hints: {', '.join(ci_workflows[:3])}."
        )

    return unique_preserve(checklist)[:7]


def suggest_related_tests(path: str, file_set: set[str]) -> str | None:
    candidate_paths = []
    source = Path(path)
    stem = source.stem
    suffix = source.suffix
    relative_parent = source.parent.as_posix()

    if relative_parent != ".":
        candidate_paths.append(f"tests/{relative_parent}/{stem}{suffix}")
        candidate_paths.append(f"tests/{relative_parent}/test_{stem}{suffix}")
    candidate_paths.append(f"tests/test_{stem}{suffix}")
    candidate_paths.append(f"tests/{stem}_test{suffix}")

    for candidate in candidate_paths:
        if candidate in file_set:
            return candidate
    return None


def build_risk_notes(
    memories: list[MemoryEntry],
    files_to_inspect: list[str],
    file_stats: list[FileStat],
) -> list[str]:
    notes: list[str] = []
    stats_by_path = {stat.path: stat for stat in file_stats}

    for memory in memories:
        if memory.kind in {MemoryKind.INVARIANT, MemoryKind.DECISION, MemoryKind.HOTSPOT}:
            notes.append(f"{memory.title}: {memory.summary}")

    for path in files_to_inspect[:4]:
        stat = stats_by_path.get(path)
        if stat and stat.change_count >= 3:
            notes.append(
                f"{path} has elevated churn "
                f"({stat.change_count} modifying commits in analyzed history)."
            )

    if not notes:
        notes.append(
            "No strong historical risks matched the task; confirm adjacent subsystems manually."
        )
    return unique_preserve(notes)


def build_reading_list(
    repo_files: list[RepoFileRecord],
    memories: list[MemoryEntry],
    files_to_inspect: list[str],
) -> list[str]:
    file_set = {record.path for record in repo_files}
    suggestions = []
    for memory in memories:
        if memory.source_ref in file_set:
            suggestions.append(memory.source_ref)
    suggestions.extend(files_to_inspect)
    for fallback in ("README.md", "docs/architecture.md", "AGENTS.md", "CLAUDE.md"):
        if fallback in file_set:
            suggestions.append(fallback)
    return unique_preserve(suggestions)[:8]


def build_repo_overview(
    repo_files: list[RepoFileRecord],
    meta: dict[str, str],
    hints: ProjectHints,
) -> list[str]:
    top_level_counts: defaultdict[str, int] = defaultdict(int)
    for record in repo_files:
        top_level = record.path.split("/")[0]
        top_level_counts[top_level] += 1
    top_levels = ", ".join(
        area
        for area, _ in sorted(
            top_level_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:5]
    )

    overview = [
        f"Indexed {len(repo_files)} files from the current repository tree.",
        f"Top-level areas: {top_levels or 'none detected'}.",
    ]
    if meta.get("last_ingest_commit_count"):
        overview.append(
            f"Analyzed {meta['last_ingest_commit_count']} git commits during the last ingest."
        )
    if meta.get("last_ingest_doc_count"):
        overview.append(f"Parsed {meta['last_ingest_doc_count']} markdown documents.")
    if hints.python_tools:
        overview.append(f"Detected Python validation tools: {', '.join(hints.python_tools)}.")
    if hints.package_scripts:
        overview.append(f"Detected package scripts: {', '.join(hints.package_scripts[:5])}.")
    return overview


def build_provenance(memories: list[MemoryEntry], meta: dict[str, str]) -> list[str]:
    entries = [
        f"{memory.kind.value}: {memory.source_type.value}:{memory.source_ref}"
        for memory in memories[:6]
    ]
    if "last_ingest_at" in meta:
        entries.append(f"Last ingest: {meta['last_ingest_at']}")
    return unique_preserve(entries)
