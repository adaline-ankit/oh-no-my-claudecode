"""Blast-radius context expansion — callers and covering tests of retrieved code.

Blueprint M2: "graph expansion for callers, dependencies, tests, and blast
radius". The code graph already exists (``codeindex``: chunks + caller /
test_to_source edges keyed by git blob SHA); this module is the missing glue
that feeds it into ``onmc run`` context. When retrieval selects a file, the
agent also sees who *calls* the code in it and which *tests* cover it — so it
edits knowing what depends on the change, instead of discovering the blast
radius from a broken suite afterwards.

Zero-cost when absent: no ``.onmc/codeindex.db`` (user never ran
``onmc codegraph``/``codeindex``) → candidates pass through unchanged.
"""

from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.context_engine.models import Candidate, TrustLevel

#: Cap on extra candidates so blast radius augments, never floods, the pack.
MAX_BLAST_CANDIDATES = 4

#: Per-candidate content cap (chars); callers are context, not the main act.
_MAX_CONTENT_CHARS = 2_000

#: Only expand the strongest few retrieved files — the tail is noise.
_MAX_SEED_FILES = 3

_DB_RELPATH = Path(".onmc") / "codeindex.db"


def expand_with_blast_radius(
    repo_root: Path,
    candidates: tuple[Candidate, ...],
    *,
    max_extra: int = MAX_BLAST_CANDIDATES,
) -> tuple[Candidate, ...]:
    """Append caller/test chunks for the top retrieved files.

    Pure augmentation: the base ranking is never reordered, ids never collide
    (``blast:`` namespace), and any index failure degrades to a pass-through —
    context expansion must never block a run.
    """
    if not candidates or max_extra <= 0:
        return candidates
    db_path = Path(repo_root) / _DB_RELPATH
    if not db_path.is_file():
        return candidates
    try:
        from oh_no_my_claudecode.codeindex.store import CodeIndexStore

        store = CodeIndexStore(db_path)
        seed_paths: list[str] = []
        for candidate in candidates:
            path = candidate.path or (
                candidate.id.removeprefix("repo:") if candidate.id.startswith("repo:") else None
            )
            if path and path not in seed_paths:
                seed_paths.append(path)
            if len(seed_paths) >= _MAX_SEED_FILES:
                break

        known_paths = {c.path for c in candidates if c.path} | {
            c.id.removeprefix("repo:") for c in candidates if c.id.startswith("repo:")
        }
        extras: list[Candidate] = []
        seen: set[str] = set()
        for path in seed_paths:
            for chunk in store.get_chunks_for_path(path):
                for edge in store.get_callers(path, chunk.symbol):
                    if len(extras) >= max_extra:
                        break
                    if edge.src_path in known_paths:
                        continue  # caller already retrieved on its own merit
                    for caller in store.get_chunks_for_symbol(edge.src_symbol):
                        if caller.path != edge.src_path:
                            continue
                        cid = f"blast:{caller.path}:{caller.symbol}"
                        if cid in seen:
                            continue
                        seen.add(cid)
                        relation = "test covering" if caller.is_test else "caller of"
                        content = caller.content[:_MAX_CONTENT_CHARS]
                        extras.append(
                            Candidate(
                                id=cid,
                                content=content,
                                source="blast-radius",
                                token_count=max(1, len(content) // 4),
                                provenance=(
                                    "codeindex",
                                    f"{relation} {path}:{chunk.symbol}",
                                ),
                                structural_score=0.6,
                                path=caller.path,
                                symbol=caller.symbol,
                                start_line=caller.start_line,
                                end_line=caller.end_line,
                                trust=(
                                    TrustLevel.TRUSTED
                                    if caller.trust_level == "trusted"
                                    else TrustLevel.UNTRUSTED
                                ),
                            )
                        )
        # Tests-first: knowing the covering test outranks knowing one more caller.
        extras.sort(key=lambda c: 0 if c.provenance[1].startswith("test") else 1)
        return candidates + tuple(extras[:max_extra])
    except Exception:
        return candidates  # expansion is best-effort, never blocking


__all__ = ["MAX_BLAST_CANDIDATES", "expand_with_blast_radius"]
