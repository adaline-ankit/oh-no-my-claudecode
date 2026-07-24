"""Repository-backed candidates for the public execution harness.

Two providers are exported:

* :class:`RepositoryCandidateProvider` — original graph-neighbours / token-match
  provider.  Used as the safe fallback.
* :class:`HybridRepositoryCandidateProvider` — wraps the hybrid BM25+dense+RRF
  retrieval module.  Token-budgeted, no-op on weak evidence (via ``min_score``),
  with an automatic fallback to :class:`RepositoryCandidateProvider` when hybrid
  retrieval raises an unexpected error (e.g. corpus construction failure).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.context_engine import Candidate, RetrievalMode, TrustLevel
from oh_no_my_claudecode.ingest.repo_tree import scan_repository_files
from oh_no_my_claudecode.retrieval import HybridRetriever

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


# Documentation / prose / vendored trees are prompt-injection-prone: their
# contents are treated as untrusted data, never instructions.
_UNTRUSTED_EXTENSIONS = frozenset({".md", ".markdown", ".rst", ".txt", ".html"})
_UNTRUSTED_DIR_PARTS = frozenset(
    {"docs", "doc", "examples", "example", "vendor", "third_party", "generated", "fixtures"}
)


def _trust_for_path(path: str) -> TrustLevel:
    """Classify a repo path as trusted (first-party source) or untrusted."""
    posix = path.replace("\\", "/").lower()
    parts = frozenset(posix.split("/"))
    if parts & _UNTRUSTED_DIR_PARTS:
        return TrustLevel.UNTRUSTED
    if Path(posix).suffix in _UNTRUSTED_EXTENSIONS:
        return TrustLevel.UNTRUSTED
    return TrustLevel.TRUSTED


def _excerpt_with_span(text: str, query_tokens: set[str]) -> tuple[str, int, int]:
    """Return a bounded excerpt plus its 1-based inclusive line span.

    For short files the whole text is returned spanning the entire file.  For
    long files, windows around query-matching lines are selected and the span
    is the min/max selected line so the citation points at real line numbers.
    """
    lines = text.splitlines()
    total = len(lines)
    if len(text) <= _MAX_CONTENT_CHARS:
        return text, 1, max(total, 1)
    matching = [index for index, line in enumerate(lines) if query_tokens & _tokens(line)]
    if not matching:
        head = text[:_MAX_CONTENT_CHARS]
        return head, 1, max(len(head.splitlines()), 1)
    selected: set[int] = set()
    for index in matching:
        selected.update(range(max(0, index - 4), min(total, index + 5)))
        if sum(len(lines[item]) + 1 for item in selected) >= _MAX_CONTENT_CHARS:
            break
    ordered = sorted(selected)
    excerpt = "\n".join(lines[index] for index in ordered)[:_MAX_CONTENT_CHARS]
    return excerpt, ordered[0] + 1, ordered[-1] + 1


def _excerpt(text: str, query_tokens: set[str]) -> str:
    excerpt, _start, _end = _excerpt_with_span(text, query_tokens)
    return excerpt


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
            content, start_line, end_line = _excerpt_with_span(text, query_tokens)
            if not query_tokens & (path_tokens | _tokens(content)):
                continue
            structural = 1.0 if query_tokens & path_tokens else 0.35
            token_count = max(1, (len(content) + 3) // 4)
            trust = _trust_for_path(path)
            items.append(
                Candidate(
                    id=f"repo:{path}",
                    content=content,
                    source=path,
                    token_count=token_count,
                    provenance=(f"repo:{path}",),
                    structural_score=structural,
                    dedupe_key=path,
                    path=path,
                    start_line=start_line,
                    end_line=end_line,
                    trust=trust,
                    metadata=(
                        ("path", path),
                        ("kind", "repository-file"),
                        ("trust", trust.value),
                    ),
                )
            )
        return tuple(items)


@dataclass(frozen=True, slots=True)
class HybridRepositoryCandidateProvider:
    """BM25+dense+RRF-ranked candidate provider for ``onmc run`` context.

    Indexes all safe text files in the repository once per ``candidates()``
    call and ranks them with :class:`~oh_no_my_claudecode.retrieval.HybridRetriever`.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.
    top_k:
        Maximum number of ranked files to surface as candidates (default 20).
    min_score:
        Minimum fused RRF score for the top result.  When the top result falls
        below this threshold ``retrieve()`` returns ``[]`` (no-op / no evidence),
        and this provider returns an empty tuple.  ``0.0`` disables the gate.
    token_budget:
        Optional whitespace-token cap passed to the underlying retriever; when
        reached the retriever stops collecting hits.  ``None`` → no cap (the
        :class:`~oh_no_my_claudecode.context_engine.ContextEngine` enforces the
        authoritative token budget during ``plan()``).

    Fallback behaviour
    ------------------
    Any unexpected exception during corpus construction or retrieval causes a
    transparent fallback to :class:`RepositoryCandidateProvider` so the run
    is never blocked by a retrieval error.
    """

    repo_root: Path
    top_k: int = 20
    min_score: float = 0.0
    token_budget: int | None = None

    def candidates(self, query: str, mode: RetrievalMode) -> tuple[Candidate, ...]:
        try:
            return self._hybrid_candidates(query)
        except Exception:  # noqa: BLE001
            return RepositoryCandidateProvider(self.repo_root).candidates(query, mode)

    def _hybrid_candidates(self, query: str) -> tuple[Candidate, ...]:
        root = self.repo_root.resolve()
        records = scan_repository_files(root, exclude_dirs=_EXCLUDED_DIRS)

        doc_ids: list[str] = []
        index_texts: list[str] = []  # path-prefixed for BM25 path-term matching
        full_texts: list[str] = []  # raw content for evidence / excerpt

        for record in records:
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
            doc_ids.append(f"repo:{path}")
            index_texts.append(f"{path}\n{text}")
            full_texts.append(text[:_MAX_CONTENT_CHARS])

        if not doc_ids:
            return ()

        retriever = HybridRetriever(
            doc_ids=doc_ids,
            texts=index_texts,
            evidence_texts=full_texts,
            min_score=self.min_score,
            token_budget=self.token_budget,
        )
        hits = retriever.retrieve(query, k=self.top_k)
        if not hits:
            return ()

        query_tokens = _tokens(query)
        top_score = hits[0].score
        norm = top_score if top_score > 0.0 else 1.0

        items: list[Candidate] = []
        for hit in hits:
            path = hit.doc_id.removeprefix("repo:")
            path_tokens = _tokens(path)
            structural = 1.0 if query_tokens & path_tokens else 0.35
            content, start_line, end_line = _excerpt_with_span(hit.evidence, query_tokens)
            token_count = max(1, (len(content) + 3) // 4)
            semantic = min(1.0, hit.score / norm)
            trust = _trust_for_path(path)
            items.append(
                Candidate(
                    id=hit.doc_id,
                    content=content,
                    source=path,
                    token_count=token_count,
                    provenance=(hit.doc_id,),
                    structural_score=structural,
                    semantic_score=semantic,
                    dedupe_key=path,
                    path=path,
                    start_line=start_line,
                    end_line=end_line,
                    trust=trust,
                    metadata=(
                        ("path", path),
                        ("kind", "repository-file"),
                        ("retrieval_rank", str(hit.rank)),
                        ("trust", trust.value),
                    ),
                )
            )
        return tuple(items)


__all__ = ["HybridRepositoryCandidateProvider", "RepositoryCandidateProvider"]
