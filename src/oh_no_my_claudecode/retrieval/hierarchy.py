"""R3 — hierarchical retrieval interfaces with attributable trust.

The retrieval frontier moved from "feed the model chunks" to "expose retrieval
*interfaces* and let the model choose granularity" (A-RAG), and from static
embeddings to direct corpus interaction. This module gives ONMC that shape over
the existing code graph: three typed interfaces —

    repo_map()          repo level: what exists, where the mass is
    file_view(path)     file level: symbols + spans, no bodies
    symbol_view(name)   symbol level: body + callers/callees (blast radius)

Every response is tagged with its interface id (``hier:repo`` / ``hier:file`` /
``hier:symbol``), so the attribution ledger can score *retrieval interfaces*
exactly like memories and skills — trust is measured lift on the repo's own
benchmark, not architectural fashion. The skill router's rule extends here
unchanged: relevance proposes, evidence disposes.

Offline, deterministic, read-only over ``.onmc/codeindex.db``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.codeindex.store import CodeIndexStore

#: Interface ids — the units attribution scores.
REPO_INTERFACE = "hier:repo"
FILE_INTERFACE = "hier:file"
SYMBOL_INTERFACE = "hier:symbol"

_DB_RELPATH = Path(".onmc") / "codeindex.db"


@dataclass(frozen=True, slots=True)
class HierView:
    """One interface response, tagged for attribution."""

    interface: str
    subject: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"interface": self.interface, "subject": self.subject, "content": self.content}


class HierarchicalRetriever:
    """Repo → file → symbol interfaces over the code index."""

    def __init__(self, repo_root: Path) -> None:
        db_path = Path(repo_root) / _DB_RELPATH
        if not db_path.is_file():
            raise FileNotFoundError(
                f"code index missing at {db_path}; build it first (onmc codegraph)"
            )
        self._store = CodeIndexStore(db_path)

    def repo_map(self, *, top: int = 40) -> HierView:
        """The wide view: files ranked by symbol mass, tests marked."""
        chunks: Counter[str] = Counter()
        tests: set[str] = set()
        for path, _sha in sorted(self._store.get_indexed_blob_shas().items()):
            file_chunks = self._store.get_chunks_for_path(path)
            chunks[path] = len(file_chunks)
            if any(c.is_test for c in file_chunks):
                tests.add(path)
        lines = [
            f"{path}  ({count} symbols){'  [tests]' if path in tests else ''}"
            for path, count in chunks.most_common(top)
        ]
        return HierView(REPO_INTERFACE, "repo", "\n".join(lines))

    def file_view(self, path: str) -> HierView:
        """The middle view: a file's symbols and spans — structure, no bodies."""
        rows = [
            f"{chunk.kind} {chunk.symbol}  L{chunk.start_line}-{chunk.end_line}"
            for chunk in self._store.get_chunks_for_path(path)
        ]
        content = "\n".join(rows) if rows else f"(no indexed symbols in {path})"
        return HierView(FILE_INTERFACE, path, content)

    def symbol_view(self, symbol: str, *, max_bodies: int = 3) -> HierView:
        """The deep view: bodies plus the blast radius (callers/callees)."""
        sections: list[str] = []
        for chunk in self._store.get_chunks_for_symbol(symbol)[:max_bodies]:
            callers = self._store.get_callers(chunk.path, chunk.symbol)
            callees = self._store.get_callees(chunk.path, chunk.symbol)
            radius = []
            if callers:
                radius.append(
                    "callers: " + ", ".join(f"{e.src_path}:{e.src_symbol}" for e in callers[:8])
                )
            if callees:
                radius.append(
                    "callees: " + ", ".join(f"{e.dst_path}:{e.dst_symbol}" for e in callees[:8])
                )
            sections.append(
                f"# {chunk.path}:{chunk.symbol} (L{chunk.start_line}-{chunk.end_line})\n"
                + ("\n".join(radius) + "\n" if radius else "")
                + chunk.content
            )
        content = "\n\n".join(sections) if sections else f"(symbol {symbol!r} not indexed)"
        return HierView(SYMBOL_INTERFACE, symbol, content)


__all__ = [
    "FILE_INTERFACE",
    "REPO_INTERFACE",
    "SYMBOL_INTERFACE",
    "HierView",
    "HierarchicalRetriever",
]
