"""Repository-backed candidates for the public execution harness."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.context_engine import Candidate, RetrievalMode
from oh_no_my_claudecode.ingest.repo_tree import scan_repository_files

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_TEXT_EXTENSIONS = frozenset(
    {
        ".css",
        ".go",
        ".html",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".py",
        ".pyi",
        ".rb",
        ".rs",
        ".rst",
        ".sh",
        ".sql",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)
_TEXT_FILENAMES = frozenset({"Dockerfile", "Makefile", "README", "AGENTS.md", "CLAUDE.md"})
_EXCLUDED_DIRS = [
    ".git",
    ".onmc",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
]
_MAX_FILE_BYTES = 128 * 1024
_MAX_CANDIDATES = 1_000
_MAX_CONTENT_CHARS = 2_000
_SECRET_NAMES = frozenset(
    {
        ".env",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
    }
)


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value) if len(token) > 1}


def _is_secret_path(path: str) -> bool:
    name = Path(path).name.lower()
    return (
        name in _SECRET_NAMES
        or name.startswith(".env.")
        or name.endswith((".key", ".pem", ".p12", ".pfx"))
    )


def _excerpt(text: str, query_tokens: set[str]) -> str:
    if len(text) <= _MAX_CONTENT_CHARS:
        return text
    lines = text.splitlines()
    matching = [
        index
        for index, line in enumerate(lines)
        if query_tokens & _tokens(line)
    ]
    if not matching:
        return text[:_MAX_CONTENT_CHARS]
    selected: set[int] = set()
    for index in matching:
        selected.update(range(max(0, index - 4), min(len(lines), index + 5)))
        if sum(len(lines[item]) + 1 for item in selected) >= _MAX_CONTENT_CHARS:
            break
    return "\n".join(lines[index] for index in sorted(selected))[:_MAX_CONTENT_CHARS]


@dataclass(frozen=True, slots=True)
class RepositoryCandidateProvider:
    """Build bounded, cited candidates from safe text files in one repository."""

    repo_root: Path

    def candidates(self, query: str, mode: RetrievalMode) -> tuple[Candidate, ...]:
        del mode
        root = self.repo_root.resolve()
        query_tokens = _tokens(query)
        records = scan_repository_files(root, exclude_dirs=_EXCLUDED_DIRS)
        items: list[Candidate] = []
        for record in records:
            if len(items) >= _MAX_CANDIDATES:
                break
            path = record.path
            file_path = root / path
            if (
                _is_secret_path(path)
                or record.size_bytes > _MAX_FILE_BYTES
                or (
                    (record.extension or "") not in _TEXT_EXTENSIONS
                    and file_path.name not in _TEXT_FILENAMES
                )
            ):
                continue
            try:
                raw = file_path.read_bytes()
                if b"\x00" in raw:
                    continue
                text = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            path_tokens = _tokens(path)
            content = _excerpt(text, query_tokens)
            if not query_tokens & (path_tokens | _tokens(content)):
                continue
            structural = 1.0 if query_tokens & path_tokens else 0.35
            token_count = max(1, (len(content) + 3) // 4)
            items.append(
                Candidate(
                    id=f"repo:{path}",
                    content=content,
                    source=path,
                    token_count=token_count,
                    provenance=(f"repo:{path}",),
                    structural_score=structural,
                    dedupe_key=path,
                    metadata=(("path", path), ("kind", "repository-file")),
                )
            )
        return tuple(items)


__all__ = ["RepositoryCandidateProvider"]
