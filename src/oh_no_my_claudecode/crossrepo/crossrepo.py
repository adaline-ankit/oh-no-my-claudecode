"""Pure, deterministic, offline cross-repo analysis.

Two capabilities, both stdlib + reuse of existing onmc readers, no LLM, no
network:

- :func:`scan_repos` — build a cross-repo **impact map**.  For each sibling
  repo it collects the set of top-level module/package names (dirs under
  ``src/`` or top-level packages at the repo root).  A module that appears in
  **two or more** repos is a ripple surface: a change to it in one repo can
  propagate into every other repo that also carries it.

- :func:`federated_recall` — a unified **recall** across the repos'
  ``.agent-memory/`` exports.  Each repo's export is loaded via the same
  schema the :mod:`oh_no_my_claudecode.federation` importer uses
  (:class:`~oh_no_my_claudecode.sync.schema.ExportedMemoryRecord` /
  :class:`~oh_no_my_claudecode.sync.schema.SyncManifest`), every hit is tagged
  with its source repo, and results are ranked by a simple deterministic
  token-overlap score.

Everything here is a pure function over filesystem inputs: the same repos +
same query always yield the same output (sorted traversal, sorted ties).  A
path that is not a repo — or a repo with no memory export — is skipped
gracefully with a recorded note rather than raising.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.models import MemoryEntry
from oh_no_my_claudecode.sync.schema import ExportedMemoryRecord, SyncManifest
from oh_no_my_claudecode.utils.text import tokenize

# Directories never worth treating as a top-level "module" — VCS, caches,
# build output, tooling.  Mirrors the codegraph exclude set so the two agree
# on what counts as repo source.
_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".onmc",
        ".agent-memory",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".tox",
        "build",
        "dist",
        ".eggs",
        "site-packages",
        "tests",
        "test",
        "docs",
        "scripts",
        "examples",
    }
)

# Marker files that identify a directory as a project root worth scanning.
_REPO_MARKERS = frozenset(
    {
        ".git",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "package.json",
        "go.mod",
        "Cargo.toml",
    }
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoView:
    """A single repository's top-level module surface.

    ``modules`` is the sorted set of top-level package/module names discovered
    for the repo — the units through which a change can ripple to a sibling.
    """

    path: str
    name: str
    modules: list[str]


@dataclass(frozen=True)
class CrossImpact:
    """One shared module and the repos that carry it.

    A change to ``shared_module`` in any one of ``repos`` is a candidate ripple
    into all the others.
    """

    shared_module: str
    repos: list[str]


@dataclass
class CrossRepoMap:
    """The result of :func:`scan_repos`.

    ``repos`` are the successfully scanned repositories (sorted by name),
    ``impacts`` the modules shared across two or more of them (sorted by module
    name), and ``skipped`` a list of ``(path, reason)`` notes for inputs that
    were not usable repos.
    """

    repos: list[RepoView] = field(default_factory=list)
    impacts: list[CrossImpact] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation."""
        return {
            "repos": [
                {"path": r.path, "name": r.name, "modules": r.modules} for r in self.repos
            ],
            "impacts": [
                {"shared_module": i.shared_module, "repos": i.repos} for i in self.impacts
            ],
            "skipped": [{"path": p, "reason": reason} for p, reason in self.skipped],
        }


@dataclass(frozen=True)
class RecallHit:
    """One federated recall hit, attributed to its source repo."""

    repo: str
    memory_id: str
    title: str
    summary: str
    tags: list[str]
    score: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation."""
        return {
            "repo": self.repo,
            "memory_id": self.memory_id,
            "title": self.title,
            "summary": self.summary,
            "tags": self.tags,
            "score": self.score,
        }


# ---------------------------------------------------------------------------
# Impact map
# ---------------------------------------------------------------------------


def _repo_name(repo_root: Path) -> str:
    """Derive a short, stable repo label from its root directory name."""
    name = repo_root.name
    return name if name else repo_root.as_posix()


def _looks_like_repo(repo_root: Path) -> bool:
    """Return whether *repo_root* is a plausible project root.

    True when it is a directory containing any recognised marker (``.git``,
    ``pyproject.toml``, ``package.json``, …) or a ``src/`` directory.  Kept
    permissive so a constructed test fixture with just a ``src/`` tree counts.
    """
    if not repo_root.is_dir():
        return False
    if (repo_root / "src").is_dir():
        return True
    return any((repo_root / marker).exists() for marker in _REPO_MARKERS)


def _top_level_modules(repo_root: Path) -> list[str]:
    """Return the sorted set of top-level module/package names for a repo.

    Preference order for where packages live:

    1. ``src/`` layout — every immediate sub-directory of ``src/`` that is not
       excluded, plus any top-level ``*.py`` module directly under ``src/``.
    2. Otherwise, the repo root — every immediate sub-directory that is not
       excluded, plus top-level ``*.py`` modules at the root.

    Deterministic: directories and files are read in sorted order and the
    result is de-duplicated and sorted.
    """
    base = repo_root / "src" if (repo_root / "src").is_dir() else repo_root
    modules: set[str] = set()
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    for entry in entries:
        name = entry.name
        if name in _EXCLUDE_DIRS or name.startswith("."):
            continue
        if entry.is_dir():
            modules.add(name)
        elif entry.is_file() and name.endswith(".py") and name != "__init__.py":
            modules.add(name[: -len(".py")])
    return sorted(modules)


def scan_repos(paths: list[Path]) -> CrossRepoMap:
    """Scan *paths* and build a cross-repo impact map.

    For each path that is a usable repo, collect its top-level module names.
    Compute impacts as every module name that appears in **two or more** repos.
    Non-repo or unreadable paths are skipped and recorded in ``skipped``.

    Deterministic and offline: repos are sorted by name, impacts by module
    name, and each impact's repo list is sorted.
    """
    repos: list[RepoView] = []
    skipped: list[tuple[str, str]] = []
    seen_roots: set[str] = set()

    for path in paths:
        repo_root = path.expanduser()
        try:
            repo_root = repo_root.resolve()
        except OSError:
            skipped.append((path.as_posix(), "unresolvable path"))
            continue
        key = repo_root.as_posix()
        if key in seen_roots:
            skipped.append((path.as_posix(), "duplicate path"))
            continue
        if not repo_root.exists():
            skipped.append((path.as_posix(), "path does not exist"))
            continue
        if not _looks_like_repo(repo_root):
            skipped.append((path.as_posix(), "not a repo (no src/ or project marker)"))
            continue
        seen_roots.add(key)
        modules = _top_level_modules(repo_root)
        repos.append(
            RepoView(path=key, name=_repo_name(repo_root), modules=modules)
        )

    repos.sort(key=lambda r: (r.name, r.path))

    # module name -> set of repo names carrying it
    module_repos: dict[str, set[str]] = {}
    for repo in repos:
        for module in repo.modules:
            module_repos.setdefault(module, set()).add(repo.name)

    impacts = [
        CrossImpact(shared_module=module, repos=sorted(names))
        for module, names in module_repos.items()
        if len(names) >= 2
    ]
    impacts.sort(key=lambda i: i.shared_module)

    return CrossRepoMap(repos=repos, impacts=impacts, skipped=skipped)


# ---------------------------------------------------------------------------
# Federated recall
# ---------------------------------------------------------------------------


def _resolve_agent_memory_dir(source: Path) -> Path | None:
    """Return the ``.agent-memory/`` dir for *source*, or ``None`` if absent.

    Accepts either a path directly to a ``.agent-memory/`` directory (contains
    ``manifest.json``) or a repo root containing a ``.agent-memory/``
    sub-directory.  Mirrors the resolution the federation importer performs but
    returns ``None`` instead of raising so recall degrades gracefully.
    """
    if (source / "manifest.json").exists():
        return source
    nested = source / ".agent-memory"
    if (nested / "manifest.json").exists():
        return nested
    return None


def _load_export_memories(agent_memory_dir: Path) -> list[MemoryEntry]:
    """Load every exported memory under *agent_memory_dir*.

    Uses the same schema the federation importer uses
    (:class:`SyncManifest` for validation, :class:`ExportedMemoryRecord` per
    payload).  Corrupt or unreadable payloads are skipped individually so one
    bad file cannot sink the whole recall.
    """
    manifest_path = agent_memory_dir / "manifest.json"
    try:
        SyncManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []

    memories: list[MemoryEntry] = []
    memories_dir = agent_memory_dir / "memories"
    if not memories_dir.exists():
        return memories
    for payload_path in sorted(memories_dir.glob("*/*.json")):
        try:
            record = ExportedMemoryRecord.model_validate(
                json.loads(payload_path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError):
            continue
        memories.append(record.memory)
    return memories


def _relevance(query_tokens: set[str], memory: MemoryEntry) -> int:
    """Return a deterministic token-overlap relevance score for *memory*.

    Title matches weigh more than summary/tag matches than details — a simple,
    ReDoS-free set-intersection over lowercased tokens.  Zero means no overlap.
    """
    if not query_tokens:
        return 0
    title_tokens = set(tokenize(memory.title))
    summary_tokens = set(tokenize(memory.summary))
    tag_tokens = {tok for tag in memory.tags for tok in tokenize(tag)}
    detail_tokens = set(tokenize(memory.details))

    title_hits = len(query_tokens & title_tokens)
    summary_hits = len(query_tokens & (summary_tokens | tag_tokens))
    detail_hits = len(query_tokens & detail_tokens)
    return title_hits * 5 + summary_hits * 2 + detail_hits


def federated_recall(paths: list[Path], query: str) -> list[RecallHit]:
    """Search every repo's ``.agent-memory/`` export for *query*.

    Loads each repo's memory export (skipping repos without one), scores each
    memory by deterministic token overlap with *query*, and returns the hits
    with a non-zero score, ranked best-first.  Every hit carries its source
    repo label so results are unambiguously attributed.

    Ties are broken deterministically by ``(repo, memory_id)`` so the same
    inputs always produce the same ordering.  An empty *query* or repos with no
    export yield an empty list rather than raising.
    """
    query_tokens = set(tokenize(query))

    hits: list[RecallHit] = []
    for path in paths:
        source = path.expanduser()
        try:
            source = source.resolve()
        except OSError:
            continue
        agent_memory_dir = _resolve_agent_memory_dir(source)
        if agent_memory_dir is None:
            continue
        repo_label = _repo_name(agent_memory_dir.parent)
        for memory in _load_export_memories(agent_memory_dir):
            score = _relevance(query_tokens, memory)
            if score <= 0:
                continue
            hits.append(
                RecallHit(
                    repo=repo_label,
                    memory_id=memory.id,
                    title=memory.title,
                    summary=memory.summary,
                    tags=list(memory.tags),
                    score=score,
                )
            )

    hits.sort(key=lambda h: (-h.score, h.repo, h.memory_id))
    return hits
