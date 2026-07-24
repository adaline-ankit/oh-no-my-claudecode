#!/usr/bin/env python3
"""Build the frozen code-retrieval evaluation dataset.

Construction rule (FROZEN — do NOT change after dataset is committed):
----------------------------------------------------------------------
1. Scope: only the three in-scope modules:
       src/oh_no_my_claudecode/retrieval_eval/
       src/oh_no_my_claudecode/retrieval/
       src/oh_no_my_claudecode/codeindex/
2. Chunk each Python file in those modules using the live chunker.
3. Retain chunks where:
       symbol != "__module__"   (not a whole-file chunk)
       kind in {function, class, method}
       is_test is False
4. Sort all retained chunks by chunk_id (hex string — deterministic across runs).
5. Stride-sample: stride = max(1, total // TARGET), keep chunks[::stride][:TARGET].
   TARGET = 40.
6. For each sampled chunk, derive the QUERY:
   a) Extract the first sentence from the docstring (the triple-quoted string
      immediately after the def/class statement, if present).
   b) If no docstring found, template from snake_case symbol name:
          words = symbol.replace("_", " ").split()
          "code that " + " ".join(words)
   c) Anti-leak: the exact symbol identifier is NOT included verbatim in the
      query when constructing from a docstring.  Instead the docstring text is
      used directly (it is human-authored description, not a lexical copy of the
      symbol name).  When using the template fallback the symbol name IS implied
      via the human-readable words — this is intentional (names are meaningful).
7. Each sampled chunk becomes ONE corpus entry + ONE query case.
   - corpus id  = chunk.chunk_id
   - query_id   = "code-{N:03d}" (zero-padded sequential)
   - surface    = "code-bm25"  (case for the BM25-only adapter)
   - relevant   = [chunk.chunk_id]
   The SAME query is also emitted with surface="code-hybrid" so BOTH adapters
   can be scored against the same queries without modifying the runner.
8. Corpus = ALL chunks from step 3 (not just the sampled ones), so retrieval
   is genuinely challenging — each query must find 1 correct chunk out of N.
9. Compute SHA256(JSON(version, corpus, cases)) and embed as dataset_sha.

Usage:
    cd <repo root>
    uv run python scripts/build_code_retrieval_dataset.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve repo root from script location
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from oh_no_my_claudecode.codeindex.chunker import chunk_file, compute_blob_sha  # noqa: E402

# ---------------------------------------------------------------------------
# Construction parameters (FROZEN)
# ---------------------------------------------------------------------------
TARGET = 40   # target number of sampled queries (per surface)
DATASET_VERSION = "1.0"

_SCOPE_DIRS = [
    "src/oh_no_my_claudecode/retrieval_eval",
    "src/oh_no_my_claudecode/retrieval",
    "src/oh_no_my_claudecode/codeindex",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_docstring_first_sentence(content: str, symbol: str) -> str | None:
    """Parse *content* as Python and return the first sentence of the symbol's docstring.

    Returns None when no docstring is found or when the content is not valid Python.
    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None

    symbol_nodes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(tree):
        if not isinstance(node, symbol_nodes) or node.name != symbol:
            continue
        docstring = ast.get_docstring(node)
        if docstring:
            # Take the first sentence (up to first period followed by
            # whitespace-or-end, or the full first line).
            first_line = docstring.splitlines()[0].strip()
            # Try sentence boundary
            m = re.match(r"^(.+?[.!?])\s", first_line + " ")
            if m:
                return m.group(1).strip()
            return first_line
    return None


def _make_query(content: str, symbol: str, kind: str) -> str:
    """Derive a natural-language query for a code chunk.

    Priority:
    1. First sentence of the symbol's docstring (symbol name not explicitly added).
    2. Template: "<kind> that <snake_case_words>" (safe fallback — symbol words used).
    """
    # Try docstring extraction
    doc_sentence = _extract_docstring_first_sentence(content, symbol)
    if doc_sentence and len(doc_sentence) > 10:  # noqa: PLR2004
        return doc_sentence

    # Fallback: template from the symbol name
    words = re.sub(r"[^a-zA-Z0-9]+", " ", symbol).strip().split()
    readable = " ".join(w.lower() for w in words if w)
    kind_label = {"function": "function", "class": "class", "method": "method"}.get(
        kind, "code unit"
    )
    return f"{kind_label} that {readable}"


# ---------------------------------------------------------------------------
# Main build logic
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Repo root: {_REPO_ROOT}")
    print(f"Scoped dirs: {_SCOPE_DIRS}")

    # Discover and chunk all Python files in the scoped dirs
    all_chunks = []
    for scope_rel in _SCOPE_DIRS:
        scope_abs = _REPO_ROOT / scope_rel
        if not scope_abs.exists():
            print(f"WARNING: scope dir not found: {scope_abs}", file=sys.stderr)
            continue
        for py_file in sorted(scope_abs.rglob("*.py")):
            rel = py_file.relative_to(_REPO_ROOT).as_posix()
            blob_sha = compute_blob_sha(py_file)
            if not blob_sha:
                continue
            chunks, _ = chunk_file(py_file, rel, blob_sha, "build-dataset")
            for c in chunks:
                if (
                    c.symbol != "__module__"
                    and c.kind in {"function", "class", "method"}
                    and not c.is_test
                ):
                    all_chunks.append(c)

    print(f"Total eligible chunks (corpus): {len(all_chunks)}")

    # Sort by chunk_id for deterministic ordering
    all_chunks.sort(key=lambda c: c.chunk_id)

    # Stride-sample TARGET queries
    stride = max(1, len(all_chunks) // TARGET)
    sampled = all_chunks[::stride][:TARGET]
    print(f"Sampled {len(sampled)} chunks (stride={stride}, target={TARGET})")

    # Build corpus: ALL eligible chunks
    corpus = []
    for c in all_chunks:
        corpus.append({
            "id": c.chunk_id,
            "kind": c.kind,
            "path": c.path,
            "symbol": c.symbol,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "language": c.language,
            "content": c.content,
        })

    # Build cases: one pair (bm25, hybrid) per sampled chunk
    cases = []
    for i, c in enumerate(sampled):
        query_text = _make_query(c.content, c.symbol, c.kind)
        qnum = i + 1
        # BM25-surface case
        cases.append({
            "query_id": f"code-{qnum:03d}-bm25",
            "surface": "code-bm25",
            "query": query_text,
            "relevant_ids": [c.chunk_id],
            "graded": {},
        })
        # Hybrid-surface case (identical query, different surface tag)
        cases.append({
            "query_id": f"code-{qnum:03d}-hybrid",
            "surface": "code-hybrid",
            "query": query_text,
            "relevant_ids": [c.chunk_id],
            "graded": {},
        })

    print(f"Cases generated: {len(cases)} ({len(cases)//2} per surface)")

    # Compute canonical SHA
    content_for_sha = {
        "version": DATASET_VERSION,
        "corpus": corpus,
        "cases": cases,
    }
    sha = hashlib.sha256(
        json.dumps(content_for_sha, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    print(f"Dataset SHA256: {sha}")

    # Write output
    out = {
        "version": DATASET_VERSION,
        "dataset_sha": sha,
        "_meta": {
            "description": (
                "Frozen code-retrieval evaluation split for onmc retrieval-eval. "
                "See scripts/build_code_retrieval_dataset.py for the full construction rule. "
                "Do NOT edit this file manually — its SHA256 is pinned and verified on load."
            ),
            "construction_rule": (
                "Chunks from 3 in-scope modules (retrieval_eval, retrieval, codeindex), "
                f"sorted by chunk_id, stride-sampled (stride={stride}, target={TARGET}). "
                "Query = first docstring sentence OR snake_case template. "
                "Corpus = all eligible chunks; relevant = the sampled chunk only."
            ),
            "scope_dirs": _SCOPE_DIRS,
            "stride": stride,
            "target": TARGET,
        },
        "corpus": corpus,
        "cases": cases,
    }

    out_path = _REPO_ROOT / "datasets" / "retrieval_code_v1.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"Written to: {out_path}")

    # Show sample queries so we can verify anti-leak
    print("\nSample (first 5 queries):")
    for c in cases[:10:2]:  # every other (only bm25 side)
        print(f"  [{c['query_id']}] {c['query'][:100]}")
        print(f"    -> relevant: {c['relevant_ids']}")


if __name__ == "__main__":
    main()
