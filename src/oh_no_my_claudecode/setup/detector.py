from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.core.repo import discover_repo_root
from oh_no_my_claudecode.hooks.installer import claude_settings_path
from oh_no_my_claudecode.ingest.docs import discover_doc_paths
from oh_no_my_claudecode.ingest.repo_tree import detect_project_hints, scan_repository_files


@dataclass(slots=True)
class EnvironmentDetection:
    repo_root: Path
    commit_count: int
    file_count: int
    doc_count: int
    project_type: str
    claude_code_detected: bool
    hooks_installed: bool
    mcp_registered: bool


def detect_environment(cwd: Path | str = ".") -> EnvironmentDetection:
    """Detect repo, Claude Code, and project characteristics for setup."""
    repo_root = discover_repo_root(Path(cwd))
    repo_files = scan_repository_files(repo_root, exclude_dirs=["node_modules", ".venv", "dist"])
    hints = detect_project_hints(repo_root, repo_files)
    docs = discover_doc_paths(
        repo_root,
        globs=["README*", "docs/**/*.md", "CLAUDE.md", "AGENTS.md"],
    )
    settings_path = claude_settings_path()
    settings = _load_settings(settings_path)
    return EnvironmentDetection(
        repo_root=repo_root,
        commit_count=_commit_count(repo_root),
        file_count=len(repo_files),
        doc_count=len(docs),
        project_type=_project_type(hints),
        claude_code_detected=settings_path.parent.exists(),
        hooks_installed=_hooks_installed(settings),
        mcp_registered=_mcp_registered(settings),
    )


def _commit_count(repo_root: Path) -> int:
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return 0
    return int(result.stdout.strip() or "0")


def _project_type(hints: object) -> str:
    python_tools = getattr(hints, "python_tools", [])
    package_scripts = getattr(hints, "package_scripts", [])
    if python_tools:
        return "Python project"
    if package_scripts:
        return "JS/TS project"
    return "General repo"


def _load_settings(settings_path: Path) -> dict[str, object]:
    if not settings_path.exists():
        return {}
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _hooks_installed(settings: dict[str, object]) -> bool:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    return "PreCompact" in hooks and "PostCompact" in hooks


def _mcp_registered(settings: dict[str, object]) -> bool:
    servers = settings.get("mcpServers")
    return isinstance(servers, dict) and "onmc" in servers
