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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.codeindex.exclusions import redact_secrets
from oh_no_my_claudecode.context_engine import Candidate, RetrievalMode, TrustLevel
from oh_no_my_claudecode.harness_run.repo_signals import (
    CodeOwners,
    changed_paths,
    detect_conventions,
)
from oh_no_my_claudecode.ingest.repo_tree import scan_repository_files
from oh_no_my_claudecode.retrieval import (
    HybridRetriever,
    Reranker,
    RetrievalDecision,
)

# Bounded relevance boost applied to files with uncommitted changes so
# retrieval is git-diff-aware (what the developer is editing is likely relevant).
_DIFF_BOOST = 0.25
_MANIFEST_NAMES = frozenset(
    {"pyproject.toml", "package.json", "go.mod", "Cargo.toml", "pom.xml", "Gemfile", "setup.py"}
)

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


def _trust_after_redaction(base: TrustLevel, redactions: int) -> TrustLevel:
    """A file that carried inline secrets is treated as untrusted."""
    return TrustLevel.UNTRUSTED if redactions > 0 else base


def _redaction_metadata(redactions: int) -> tuple[tuple[str, str], ...]:
    """Metadata recording how many secrets were masked (omitted when none)."""
    return (("redacted", str(redactions)),) if redactions > 0 else ()


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
class _RepoSignals:
    """Precomputed, repo-wide signals shared across all candidates in one call."""

    changed: frozenset[str]
    owners: CodeOwners
    conventions: str

    @classmethod
    def collect(cls, root: Path) -> _RepoSignals:
        conv = detect_conventions(root)
        return cls(
            changed=changed_paths(root),
            owners=CodeOwners.load(root),
            conventions=";".join(f"{key}={value}" for key, value in conv),
        )

    def structural_boost(self, path: str, structural: float) -> float:
        """Apply the git-diff boost when *path* has uncommitted changes."""
        if path in self.changed:
            return min(1.0, structural + _DIFF_BOOST)
        return structural

    def metadata_for(self, path: str) -> tuple[tuple[str, str], ...]:
        """Ownership / diff / convention metadata for *path* (unique keys)."""
        extra: list[tuple[str, str]] = []
        if path in self.changed:
            extra.append(("changed", "true"))
        owners = self.owners.owners_for(path)
        if owners:
            extra.append(("owners", ",".join(owners)))
        if self.conventions and Path(path).name in _MANIFEST_NAMES:
            extra.append(("conventions", self.conventions))
        return tuple(extra)


@dataclass(frozen=True, slots=True)
class RepositoryCandidateProvider:
    """Build bounded, cited candidates from safe text files in one repository."""

    repo_root: Path

    def candidates(self, query: str, mode: RetrievalMode) -> tuple[Candidate, ...]:
        del mode
        root = self.repo_root.resolve()
        query_tokens = _tokens(query)
        records = scan_repository_files(root, exclude_dirs=_EXCLUDED_DIRS)
        signals = _RepoSignals.collect(root)
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
            content, redactions = redact_secrets(content)
            structural = 1.0 if query_tokens & path_tokens else 0.35
            structural = signals.structural_boost(path, structural)
            token_count = max(1, (len(content) + 3) // 4)
            trust = _trust_after_redaction(_trust_for_path(path), redactions)
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
                        *_redaction_metadata(redactions),
                        *signals.metadata_for(path),
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
    Any unexpected exception during corpus construction or retrieval falls back to
    :class:`RepositoryCandidateProvider` so a retrieval bug can never block a run.

    That fallback is **typed and reported**, not silent. Previously the ``except``
    swallowed the exception whole, so a run whose retrieval had degraded to the
    basic lexical provider was indistinguishable from a healthy one — neither the
    user nor a benchmark could tell that the feature under test had switched
    itself off. ``on_fallback`` receives ``"<ExceptionType>: <message>"`` and the
    controller surfaces it on the context stage.
    """

    repo_root: Path
    top_k: int = 20
    min_score: float = 0.0
    token_budget: int | None = None
    retrieval_mode: str = "bm25"  # BM25-first for code; "hybrid"/"dense" opt-in
    candidate_promoted: bool = False
    min_candidate_confidence: float = 0.65
    reranker: Reranker | None = None
    on_fallback: Callable[[str], None] | None = None
    on_decision: Callable[[RetrievalDecision], None] | None = None

    def candidates(self, query: str, mode: RetrievalMode) -> tuple[Candidate, ...]:
        try:
            base = self._hybrid_candidates(query)
        except Exception as exc:  # noqa: BLE001 - must never block a run
            if self.on_fallback is not None:
                self.on_fallback(f"{type(exc).__name__}: {exc}")
            base = RepositoryCandidateProvider(self.repo_root).candidates(query, mode)
        # Graph expansion (blueprint M2): append callers + covering tests of the
        # top retrieved files from the codeindex graph. Pass-through when the
        # index is absent or unreadable — expansion never blocks a run.
        from oh_no_my_claudecode.harness_run.blast_radius import expand_with_blast_radius

        return expand_with_blast_radius(self.repo_root, base)

    def _hybrid_candidates(self, query: str) -> tuple[Candidate, ...]:
        root = self.repo_root.resolve()
        records = scan_repository_files(root, exclude_dirs=_EXCLUDED_DIRS)

        doc_ids: list[str] = []
        index_texts: list[str] = []  # path-prefixed for BM25 path-term matching
        full_texts: list[str] = []  # raw content for evidence / excerpt

        seen_paths: set[str] = set()
        for record in records:
            path = record.path
            # The index can legitimately yield the same path more than once
            # (re-indexed entries, symlinked docs). Two candidates sharing the
            # id `repo:<path>` but carrying different retrieval scores make the
            # context planner raise "conflicting candidates share id", which
            # crashed `onmc run` on real repositories. Index each path once.
            if path in seen_paths:
                continue
            seen_paths.add(path)
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
        measured_budget = self.token_budget
        if measured_budget is None:
            measured_budget = sum(max(1, len(text.split())) for text in full_texts)
        decision = retriever.retrieve_measured(
            query,
            k=self.top_k,
            requested_mode=self.retrieval_mode,
            candidate_promoted=self.candidate_promoted,
            min_candidate_confidence=self.min_candidate_confidence,
            token_budget=measured_budget,
            reranker=self.reranker,
        )
        if self.on_decision is not None:
            self.on_decision(decision)
        hits = decision.hits
        if not hits:
            return ()

        query_tokens = _tokens(query)
        top_score = hits[0].score
        norm = top_score if top_score > 0.0 else 1.0
        signals = _RepoSignals.collect(root)

        items: list[Candidate] = []
        for hit in hits:
            path = hit.doc_id.removeprefix("repo:")
            path_tokens = _tokens(path)
            structural = 1.0 if query_tokens & path_tokens else 0.35
            structural = signals.structural_boost(path, structural)
            content, start_line, end_line = _excerpt_with_span(hit.evidence, query_tokens)
            content, redactions = redact_secrets(content)
            token_count = max(1, (len(content) + 3) // 4)
            semantic = (
                min(1.0, hit.score / norm)
                if decision.selected_stage != "bm25"
                else None
            )
            trust = _trust_after_redaction(_trust_for_path(path), redactions)
            items.append(
                Candidate(
                    id=hit.doc_id,
                    content=content,
                    source=path,
                    token_count=token_count,
                    provenance=(
                        hit.doc_id,
                        f"retrieval:{decision.selected_stage}",
                        f"query-plan:{decision.query_plan.schema_version}",
                    ),
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
                        ("query_intent", decision.query_plan.intent.value),
                        ("retrieval_stage", decision.selected_stage),
                        ("retrieval_confidence", f"{decision.confidence:.6f}"),
                        ("retrieval_fallback", decision.fallback_reason),
                        ("lexical_floor", str(decision.query_plan.lexical_floor).lower()),
                        ("candidate_promoted", str(decision.candidate_promoted).lower()),
                        ("retrieval_token_budget", str(decision.token_budget)),
                        ("trust", trust.value),
                        *_redaction_metadata(redactions),
                        *signals.metadata_for(path),
                    ),
                )
            )
        return tuple(items)


__all__ = ["HybridRepositoryCandidateProvider", "RepositoryCandidateProvider"]
