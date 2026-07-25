"""Repository signals that bias retrieval toward the task's real context.

Three offline, fail-safe signals feed the run-path candidate providers:

* :func:`changed_paths` — files touched in the working tree / index (via
  ``git status``), so retrieval is *git-diff-aware*: candidates the developer
  is actively editing get a bounded relevance boost.
* :class:`CodeOwners` — CODEOWNERS ownership resolution, surfaced as per-file
  ``owners`` metadata.
* :func:`detect_conventions` — provider/framework/convention fingerprint from
  repo manifests (pyproject/package.json/go.mod/…), surfaced as metadata.

Every function degrades to an empty result on any error (no git, parse
failure, timeout); retrieval must never break because a signal is unavailable.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

_GIT_TIMEOUT_S = 5


def changed_paths(repo_root: Path) -> frozenset[str]:
    """Repo-relative POSIX paths with uncommitted changes (staged/unstaged/new).

    Uses ``git status --porcelain`` so modified, staged, and untracked files
    all count. Returns an empty set outside a git repo or on any failure.
    """
    try:
        completed = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo_root), "status", "--porcelain", "-z"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    if completed.returncode != 0:
        return frozenset()
    paths: set[str] = set()
    for entry in completed.stdout.split("\0"):
        if len(entry) <= 3:
            continue
        # Porcelain: "XY <path>"; rename entries carry "orig\0new" but the -z
        # split already separated them, so take the trailing path token.
        raw = entry[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        paths.add(raw.replace("\\", "/"))
    return frozenset(paths)


@dataclass(frozen=True, slots=True)
class CodeOwners:
    """Parsed CODEOWNERS rules; last matching pattern wins (git semantics)."""

    rules: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @classmethod
    def load(cls, repo_root: Path) -> CodeOwners:
        """Load CODEOWNERS from the conventional locations; empty if absent."""
        for candidate in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
            path = repo_root / candidate
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            return cls._parse(text)
        return cls()

    @classmethod
    def _parse(cls, text: str) -> CodeOwners:
        rules: list[tuple[str, tuple[str, ...]]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            pattern, owners = parts[0], tuple(parts[1:])
            if owners:
                rules.append((pattern, owners))
        return cls(tuple(rules))

    def owners_for(self, path: str) -> tuple[str, ...]:
        """Owners for *path* (repo-relative POSIX); last matching rule wins."""
        posix = path.replace("\\", "/")
        matched: tuple[str, ...] = ()
        for pattern, owners in self.rules:
            if _codeowners_match(pattern, posix):
                matched = owners
        return matched


def _codeowners_match(pattern: str, path: str) -> bool:
    """Approximate CODEOWNERS glob matching (dir prefixes + fnmatch)."""
    pat = pattern.lstrip("/")
    if pat.endswith("/"):
        return path == pat.rstrip("/") or path.startswith(pat)
    if "*" not in pat and "?" not in pat:
        # A bare path matches itself or anything beneath it (dir semantics).
        return path == pat or path.startswith(pat + "/")
    return fnmatch(path, pat) or fnmatch(path, pat + "/*")


_MANIFEST_PROVIDERS: tuple[tuple[str, str, str], ...] = (
    ("pyproject.toml", "language", "python"),
    ("setup.py", "language", "python"),
    ("package.json", "language", "javascript"),
    ("go.mod", "language", "go"),
    ("Cargo.toml", "language", "rust"),
    ("pom.xml", "language", "java"),
    ("Gemfile", "language", "ruby"),
)


def detect_conventions(repo_root: Path) -> tuple[tuple[str, str], ...]:
    """Detect provider/framework/convention signals from repo manifests.

    Returns a sorted tuple of ``(key, value)`` pairs, e.g.
    ``(("language", "python"), ("test_framework", "pytest"))``. Empty on any
    error. Deterministic (sorted, deduplicated).
    """
    signals: dict[str, str] = {}
    for manifest, key, value in _MANIFEST_PROVIDERS:
        if (repo_root / manifest).is_file():
            signals.setdefault(key, value)
    try:
        pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        pyproject = ""
    if "pytest" in pyproject:
        signals.setdefault("test_framework", "pytest")
    if "ruff" in pyproject:
        signals.setdefault("linter", "ruff")
    if "mypy" in pyproject:
        signals.setdefault("type_checker", "mypy")
    return tuple(sorted(signals.items()))


__all__ = ["CodeOwners", "changed_paths", "detect_conventions"]
