from __future__ import annotations

import json
import os
from pathlib import Path

from oh_no_my_claudecode.core.repo import is_test_path, path_bucket, relative_path
from oh_no_my_claudecode.models import (
    MemoryEntry,
    MemoryKind,
    ProjectHints,
    RepoFileRecord,
    SourceType,
)
from oh_no_my_claudecode.utils.text import shorten, stable_id, unique_preserve
from oh_no_my_claudecode.utils.time import utc_now


def scan_repository_files(repo_root: Path, *, exclude_dirs: list[str]) -> list[RepoFileRecord]:
    records: list[RepoFileRecord] = []
    excluded = set(exclude_dirs)
    for current_root, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in excluded and not dirname.startswith(".git")
        ]
        current_root_path = Path(current_root)
        if any(part in excluded for part in current_root_path.relative_to(repo_root).parts):
            continue
        for filename in filenames:
            file_path = current_root_path / filename
            rel_path = relative_path(repo_root, file_path)
            if rel_path.startswith(".onmc/"):
                continue
            records.append(
                RepoFileRecord(
                    path=rel_path,
                    extension=file_path.suffix.lower() or None,
                    is_test=is_test_path(rel_path),
                    size_bytes=file_path.stat().st_size,
                )
            )
    records.sort(key=lambda item: item.path)
    return records


def scan_selected_files(
    repo_root: Path,
    *,
    paths: list[str],
    exclude_dirs: list[str],
) -> tuple[list[RepoFileRecord], list[str]]:
    records: list[RepoFileRecord] = []
    warnings: list[str] = []
    excluded = set(exclude_dirs)
    seen: set[str] = set()

    for raw_path in paths:
        candidate = Path(raw_path)
        file_path = candidate if candidate.is_absolute() else repo_root / candidate
        try:
            relative = relative_path(repo_root, file_path)
        except ValueError:
            warnings.append(f"Skipped path outside repo: {raw_path}")
            continue
        if relative in seen:
            continue
        seen.add(relative)
        if any(part in excluded for part in Path(relative).parts):
            warnings.append(f"Skipped excluded path: {relative}")
            continue
        if not file_path.exists() or not file_path.is_file():
            warnings.append(f"Skipped missing file: {relative}")
            continue
        if relative.startswith(".onmc/"):
            warnings.append(f"Skipped ONMC state file: {relative}")
            continue
        records.append(
            RepoFileRecord(
                path=relative,
                extension=file_path.suffix.lower() or None,
                is_test=is_test_path(relative),
                size_bytes=file_path.stat().st_size,
            )
        )

    records.sort(key=lambda item: item.path)
    return records, warnings


def detect_project_hints(repo_root: Path, repo_files: list[RepoFileRecord]) -> ProjectHints:
    file_paths = {record.path for record in repo_files}
    hints = ProjectHints()

    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists():
        pyproject_text = pyproject.read_text(encoding="utf-8")
        for tool in ("pytest", "ruff", "mypy"):
            if tool in pyproject_text:
                hints.python_tools.append(tool)

    package_json = repo_root / "package.json"
    if package_json.exists():
        payload = json.loads(package_json.read_text(encoding="utf-8"))
        scripts = payload.get("scripts", {})
        hints.package_scripts = sorted(str(name) for name in scripts)

    workflows_dir = repo_root / ".github" / "workflows"
    if workflows_dir.exists():
        hints.ci_workflows = sorted(path.name for path in workflows_dir.glob("*.y*ml"))

    hints.test_directories = unique_preserve(
        path_bucket(record.path) for record in repo_files if record.is_test
    )
    hints.source_directories = unique_preserve(
        path_bucket(record.path)
        for record in repo_files
        if not record.is_test and not record.path.endswith(".md")
    )

    if "pytest" not in hints.python_tools and any(path.startswith("tests/") for path in file_paths):
        hints.python_tools.append("pytest")

    hints.python_tools = sorted(set(hints.python_tools))
    return hints


def infer_repo_shape_memories(repo_root: Path, hints: ProjectHints) -> list[MemoryEntry]:
    memories: list[MemoryEntry] = []
    now = utc_now()

    for tool in hints.python_tools:
        command = {
            "pytest": "pytest",
            "ruff": "ruff check .",
            "mypy": "mypy src",
        }.get(tool, tool)
        summary = (
            f"Repository configuration indicates `{tool}` is part of the local validation flow."
        )
        memories.append(
            MemoryEntry(
                id=stable_id("code", tool, prefix=MemoryKind.VALIDATION_RULE.value),
                kind=MemoryKind.VALIDATION_RULE,
                title=f"Validation tool configured: {tool}",
                summary=summary,
                details=(
                    f"Detected from repo metadata under {repo_root.name}. "
                    f"Consider running `{command}` for impacted changes."
                ),
                source_type=SourceType.CODE,
                source_ref="pyproject.toml" if tool in {"pytest", "ruff", "mypy"} else tool,
                tags=["validation", tool],
                confidence=0.85,
                created_at=now,
                updated_at=now,
            )
        )

    if hints.package_scripts:
        joined = ", ".join(hints.package_scripts[:6])
        memories.append(
            MemoryEntry(
                id=stable_id("code", "package-scripts", joined, prefix=MemoryKind.DOC_FACT.value),
                kind=MemoryKind.DOC_FACT,
                title="Package scripts detected",
                summary=f"package.json exposes scripts such as {joined}.",
                details=(
                    f"Available scripts discovered in package.json: {joined}. "
                    "Use them as validation hints when editing "
                    "JavaScript or TypeScript areas."
                ),
                source_type=SourceType.CODE,
                source_ref="package.json",
                tags=["package.json", "scripts"],
                confidence=0.7,
                created_at=now,
                updated_at=now,
            )
        )

    if hints.ci_workflows:
        workflow_list = ", ".join(hints.ci_workflows)
        memories.append(
            MemoryEntry(
                id=stable_id("code", "ci", workflow_list, prefix=MemoryKind.VALIDATION_RULE.value),
                kind=MemoryKind.VALIDATION_RULE,
                title="CI workflow hints",
                summary=f"GitHub Actions workflows are present: {workflow_list}.",
                details=(
                    "Mirror the checks that appear in CI workflows when "
                    "preparing a change. This is a conservative repo-shape "
                    "inference, not a guarantee of required gates."
                ),
                source_type=SourceType.CODE,
                source_ref=".github/workflows",
                tags=["ci", "validation"],
                confidence=0.65,
                created_at=now,
                updated_at=now,
            )
        )

    if hints.source_directories:
        source_dirs = ", ".join(hints.source_directories[:5])
        memories.append(
            MemoryEntry(
                id=stable_id(
                    "code",
                    "source-layout",
                    source_dirs,
                    prefix=MemoryKind.DOC_FACT.value,
                ),
                kind=MemoryKind.DOC_FACT,
                title="Primary source layout",
                summary=f"Primary source directories include {source_dirs}.",
                details=shorten(
                    f"Observed source-like directories from the current "
                    f"file tree: {source_dirs}. Use this as a navigation "
                    "hint when mapping tasks to files."
                ),
                source_type=SourceType.CODE,
                source_ref="repo_tree",
                tags=["layout", "source"],
                confidence=0.6,
                created_at=now,
                updated_at=now,
            )
        )

    return memories
