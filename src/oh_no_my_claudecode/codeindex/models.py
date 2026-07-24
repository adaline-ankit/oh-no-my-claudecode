"""Dataclasses for the incremental code-intelligence index.

Every chunk is keyed by its git blob SHA so unchanged files are skipped on
reindex.  Edges are stored by (src_path, src_symbol, dst_path, dst_symbol) —
not by chunk_id — so they survive chunk_id changes when file content changes,
making incremental updates produce the same result as a full rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ChunkKind = Literal["module", "function", "class", "method", "config", "docs", "test"]
EdgeType = Literal["import", "callee", "test_to_source"]
Language = Literal["python", "javascript", "typescript", "go", "rust", "java", "other"]


@dataclass(slots=True, frozen=True)
class IndexChunk:
    """A single indexed code unit keyed by git blob SHA.

    Fields
    ------
    chunk_id:
        Stable ID: ``sha256(blob_sha:path:symbol:start_line)[:16]``.
        Changes whenever the file content changes (new blob_sha).
    blob_sha:
        Git blob SHA of the file at index time.  Unchanged files are skipped.
    commit_sha:
        HEAD commit SHA at index time.
    path:
        Repo-relative POSIX path of the file.
    symbol:
        Symbol identifier: function/class/method name, or ``"__module__"``
        for the file-level chunk.
    kind:
        Chunk category — ``"function"``, ``"class"``, ``"method"``,
        ``"module"``, ``"config"``, ``"docs"``, ``"test"``.
    start_line:
        1-based first line of the chunk (inclusive).
    end_line:
        1-based last line of the chunk (inclusive).
    language:
        Source language detected from the file extension.
    is_test:
        Whether this chunk lives in a test file.
    is_stale:
        Whether the blob SHA is no longer present in HEAD.
    trust_level:
        Provenance trust tag (default ``"default"``).
    indexed_at:
        ISO-8601 UTC timestamp of when this chunk was indexed.
    content:
        Full source text of the chunk.
    """

    chunk_id: str
    blob_sha: str
    commit_sha: str
    path: str
    symbol: str
    kind: ChunkKind
    start_line: int
    end_line: int
    language: Language
    is_test: bool
    is_stale: bool
    trust_level: str
    indexed_at: str
    content: str

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "chunk_id": self.chunk_id,
            "blob_sha": self.blob_sha,
            "commit_sha": self.commit_sha,
            "path": self.path,
            "symbol": self.symbol,
            "kind": self.kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "language": self.language,
            "is_test": self.is_test,
            "is_stale": self.is_stale,
            "trust_level": self.trust_level,
            "indexed_at": self.indexed_at,
            "content": self.content,
        }


@dataclass(slots=True, frozen=True)
class IndexEdge:
    """A directed edge between two code chunks.

    Edges are stored by path+symbol pairs (not chunk_ids) for stability across
    file content changes.  The chunk_id for each endpoint is resolved at query
    time via the chunk store.

    Fields
    ------
    src_path:
        Repo-relative path of the source chunk's file.
    src_symbol:
        Symbol name of the source chunk (``"__module__"`` for file-level).
    dst_path:
        Repo-relative path of the destination chunk's file.
    dst_symbol:
        Symbol name of the destination chunk.
    edge_type:
        ``"import"`` — src file imports dst file (module-level edge).
        ``"callee"`` — src function calls dst function.
        ``"test_to_source"`` — src test file covers dst source module.
    """

    src_path: str
    src_symbol: str
    dst_path: str
    dst_symbol: str
    edge_type: EdgeType

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "src_path": self.src_path,
            "src_symbol": self.src_symbol,
            "dst_path": self.dst_path,
            "dst_symbol": self.dst_symbol,
            "edge_type": self.edge_type,
        }


@dataclass(slots=True)
class IndexStats:
    """Summary statistics for the code index.

    Fields
    ------
    total_chunks:
        Number of indexed chunks.
    total_edges:
        Number of indexed edges.
    total_files:
        Number of indexed files.
    stale_chunks:
        Chunks whose blob SHA is no longer current in HEAD.
    excluded_files:
        Paths skipped because they matched an exclusion rule.
    languages:
        Mapping of language name → number of chunks.
    commit_sha:
        HEAD commit SHA at last index build/update.
    built_at:
        ISO-8601 UTC timestamp of the last full build.
    """

    total_chunks: int = 0
    total_edges: int = 0
    total_files: int = 0
    stale_chunks: int = 0
    excluded_files: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    commit_sha: str = ""
    built_at: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-safe dict."""
        return {
            "total_chunks": self.total_chunks,
            "total_edges": self.total_edges,
            "total_files": self.total_files,
            "stale_chunks": self.stale_chunks,
            "excluded_files": self.excluded_files,
            "languages": dict(sorted(self.languages.items())),
            "commit_sha": self.commit_sha,
            "built_at": self.built_at,
        }
