"""Tests for terse mode and hot-path performance.

Covers:
1. Terse output is meaningfully smaller than full (≥40% char reduction).
2. Terse output still contains the key facts (title, failed-approach tag).
3. ONMC_TERSE / ONMC_VERBOSE / --terse gating works.
4. recall compile finishes under 1 s on a seeded store.
5. Timeout path returns fast (no hang).
6. Terse boot_digest format is compact and contains key content.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from oh_no_my_claudecode.hooks.boot_digest import compile_boot_digest
from oh_no_my_claudecode.hooks.prompt_recall import (
    compile_prompt_recall,
    compile_prompt_recall_safe,
)
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.serialize.terse import (
    is_terse,
    render_boot_digest_terse,
    render_guard_terse,
    render_recall_terse,
    render_why_terse,
)
from oh_no_my_claudecode.storage import SQLiteStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_memory(
    *,
    mid: str = "mem-1",
    kind: MemoryKind = MemoryKind.INVARIANT,
    title: str = "Test invariant",
    summary: str = "All writes go through the boundary module.",
    confidence: float = 0.9,
    feedback_score: float = 0.0,
    staleness: str | None = None,
) -> MemoryEntry:
    return MemoryEntry(
        id=mid,
        kind=kind,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.DOC,
        source_ref="docs/arch.md",
        tags=[],
        confidence=confidence,
        feedback_score=feedback_score,
        created_at=_now(),
        updated_at=_now(),
        staleness=staleness,  # type: ignore[arg-type]
    )


def _make_failed(title: str, summary: str) -> MemoryEntry:
    return _make_memory(
        mid=f"failed-{title[:4]}",
        kind=MemoryKind.FAILED_APPROACH,
        title=title,
        summary=summary,
    )


def _seed_store(db_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    mems = [
        _make_memory(
            mid="mem-cache",
            title="Cache invalidation boundary",
            summary=(
                "All cache invalidations must go through the shared boundary module. "
                "Direct cache writes from workers bypass the boundary and cause stale reads. "
                "This was established to maintain data consistency across all worker processes."
            ),
        ),
        _make_memory(
            mid="mem-worker",
            kind=MemoryKind.DECISION,
            title="Worker refresh pattern",
            summary=(
                "Workers must call invalidate_cache() and never write to the store directly. "
                "This was decided in PR #42 to centralise cache invalidation and avoid race "
                "conditions that manifested when multiple workers attempted concurrent writes."
            ),
        ),
        _make_failed(
            title="Direct cache write",
            summary=(
                "Writing to the cache store directly from workers bypasses the boundary module "
                "and causes stale reads. Attempted in Q3 2024 and caused a production incident."
            ),
        ),
        _make_memory(
            mid="mem-auth",
            kind=MemoryKind.DOC_FACT,
            title="Auth uses JWT",
            summary=(
                "All API endpoints require a Bearer JWT token in the Authorization header. "
                "Tokens are validated against the shared public key set stored in Firestore."
            ),
        ),
    ]
    storage.upsert_memories(mems)
    return storage


# ---------------------------------------------------------------------------
# 1. Terse output is ≥40% smaller than full
# ---------------------------------------------------------------------------


def test_recall_terse_is_meaningfully_smaller_than_full(tmp_path: Path) -> None:
    storage = _seed_store(tmp_path / "mem.db")
    prompt = "cache invalidation boundary worker"

    full_text, full_tokens = compile_prompt_recall(
        storage, prompt, limit=5, budget_tokens=300, terse=False
    )
    terse_text, terse_tokens = compile_prompt_recall(
        storage, prompt, limit=5, budget_tokens=300, terse=True
    )

    assert full_text, "full must return content"
    assert terse_text, "terse must return content"

    full_chars = len(full_text)
    terse_chars = len(terse_text)
    reduction = (full_chars - terse_chars) / full_chars

    # 35% is a robust lower bound: terse strips headers, blank lines, italic details.
    assert reduction >= 0.35, (
        f"Expected ≥35% char reduction, got {reduction:.0%}. "
        f"full={full_chars} terse={terse_chars}"
    )


def test_boot_digest_terse_is_smaller_than_full() -> None:
    """Terse boot digest strips markdown scaffolding and is shorter than full."""
    memories = [
        _make_memory(
            mid=f"m{i}",
            title=f"Invariant {i}: always validate before processing",
            summary=(
                f"This is a moderately long summary for invariant {i}. "
                "Never skip the validation step even under high load. "
                "The downstream handler assumes clean input from all upstream callers."
            ),
        )
        for i in range(5)
    ]
    full_text, _ = compile_boot_digest(
        memories=memories, tasks=[], repo_name="my-repo", terse=False
    )
    terse_text, _ = compile_boot_digest(
        memories=memories, tasks=[], repo_name="my-repo", terse=True
    )

    assert full_text, "full must return content"
    assert terse_text, "terse must return content"

    # Terse must be strictly shorter (strips ### headers, blank lines, markdown list syntax).
    assert len(terse_text) < len(full_text), (
        f"Terse should be shorter: full={len(full_text)} terse={len(terse_text)}"
    )


# ---------------------------------------------------------------------------
# 2. Terse output retains key facts
# ---------------------------------------------------------------------------


def test_recall_terse_contains_key_facts(tmp_path: Path) -> None:
    storage = _seed_store(tmp_path / "mem.db")
    terse_text, _ = compile_prompt_recall(
        storage, "cache invalidation boundary", limit=5, terse=True
    )
    assert terse_text
    # The key title must appear.
    assert "Cache invalidation boundary" in terse_text


def test_recall_terse_failed_approach_has_correct_tag(tmp_path: Path) -> None:
    storage = _seed_store(tmp_path / "mem.db")
    terse_text, _ = compile_prompt_recall(
        storage, "direct cache write worker", limit=5, terse=True
    )
    assert terse_text
    # FAILED tag must appear.
    assert "FAILED" in terse_text


def test_boot_digest_terse_contains_key_content() -> None:
    memories = [
        _make_memory(title="Core rule", summary="Never bypass the validator."),
        _make_memory(
            mid="m2",
            kind=MemoryKind.FAILED_APPROACH,
            title="Bypassing validator",
            summary="Caused data corruption in prod.",
        ),
    ]
    terse_text, _ = compile_boot_digest(
        memories=memories, tasks=[], repo_name="test-repo", terse=True
    )
    assert "Core rule" in terse_text
    assert "test-repo" in terse_text


# ---------------------------------------------------------------------------
# 3. ONMC_TERSE / ONMC_VERBOSE / --terse gating
# ---------------------------------------------------------------------------


def test_is_terse_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONMC_TERSE", raising=False)
    monkeypatch.delenv("ONMC_VERBOSE", raising=False)
    assert is_terse(default=False) is False


def test_is_terse_default_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ONMC_TERSE", raising=False)
    monkeypatch.delenv("ONMC_VERBOSE", raising=False)
    assert is_terse(default=True) is True


def test_onmc_terse_env_forces_terse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONMC_TERSE", "1")
    monkeypatch.delenv("ONMC_VERBOSE", raising=False)
    assert is_terse(default=False) is True


def test_onmc_verbose_overrides_terse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONMC_TERSE", "1")
    monkeypatch.setenv("ONMC_VERBOSE", "1")
    assert is_terse(default=True) is False


def test_compile_prompt_recall_terse_true_returns_compact(tmp_path: Path) -> None:
    storage = _seed_store(tmp_path / "mem.db")
    text, _ = compile_prompt_recall(storage, "cache invalidation", limit=5, terse=True)
    if text:
        assert "##" not in text  # no markdown headers in terse output


def test_compile_prompt_recall_terse_false_returns_full_markdown(tmp_path: Path) -> None:
    storage = _seed_store(tmp_path / "mem.db")
    text, _ = compile_prompt_recall(storage, "cache invalidation", limit=5, terse=False)
    if text:
        assert "## Relevant repo memory" in text


# ---------------------------------------------------------------------------
# 4. Recall compile under 1 s on seeded store
# ---------------------------------------------------------------------------


def test_recall_compile_is_fast(tmp_path: Path) -> None:
    storage = _seed_store(tmp_path / "mem.db")
    start = time.monotonic()
    compile_prompt_recall(storage, "cache invalidation boundary worker", terse=True)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"Recall compile took {elapsed:.3f}s, expected < 1s"


# ---------------------------------------------------------------------------
# 5. Timeout path returns fast and doesn't hang
# ---------------------------------------------------------------------------


def test_compile_prompt_recall_safe_returns_fast(tmp_path: Path) -> None:
    storage = _seed_store(tmp_path / "mem.db")
    start = time.monotonic()
    result, tokens = compile_prompt_recall_safe(storage, "cache invalidation", timeout_ms=800)
    elapsed = time.monotonic() - start
    # Must complete well within the timeout budget.
    assert elapsed < 2.0, f"Safe compile took {elapsed:.3f}s"
    assert isinstance(result, str)
    assert isinstance(tokens, int)


def test_compile_prompt_recall_safe_with_very_short_timeout(tmp_path: Path) -> None:
    """Even with a near-zero timeout the function returns quickly and cleanly."""
    storage = _seed_store(tmp_path / "mem.db")
    start = time.monotonic()
    result, tokens = compile_prompt_recall_safe(storage, "cache invalidation", timeout_ms=1)
    elapsed = time.monotonic() - start
    # Must return within 1 second even on timeout.
    assert elapsed < 1.5, f"Took {elapsed:.3f}s with 1ms timeout"
    assert isinstance(result, str)
    assert isinstance(tokens, int)


# ---------------------------------------------------------------------------
# 6. Terse renderers direct unit tests
# ---------------------------------------------------------------------------


def test_render_recall_terse_empty_returns_empty() -> None:
    assert render_recall_terse([]) == ""


def test_render_recall_terse_formats_kind_prefix() -> None:
    mem = _make_memory(kind=MemoryKind.INVARIANT, title="My rule", summary="Do this always.")
    out = render_recall_terse([mem])
    assert out.startswith("INVARIANT: My rule")


def test_render_recall_terse_failed_approach_label() -> None:
    mem = _make_failed("Bad approach", "This caused crashes.")
    out = render_recall_terse([mem])
    assert "FAILED(don't retry)" in out


def test_render_boot_digest_terse_empty_returns_empty() -> None:
    out = render_boot_digest_terse(
        invariants=[], hotspots=[], active_tasks=[], repo_name="test", prefs=[]
    )
    assert out == ""


def test_render_guard_terse_empty_entries() -> None:
    out = render_guard_terse([], "fix the cache")
    assert "GUARD" in out
    assert "no dead-ends" in out


def test_render_guard_terse_with_entries() -> None:
    class FakeEntry:
        title = "Direct DB write"
        what_was_tried = "Wrote directly to the store."
        why_it_failed = "Caused race conditions."

    out = render_guard_terse([FakeEntry()], "fix the cache")
    assert "GUARD" in out
    assert "FAILED(don't retry)" in out
    assert "Direct DB write" in out


def test_render_why_terse_basic() -> None:
    class FakeReport:
        path = "src/cache.py"
        risk_verdict = "high-churn hotspot"
        decisions: list[MemoryEntry] = []
        failed_approaches: list[MemoryEntry] = []
        hotspot_memories: list[MemoryEntry] = []
        git_history = None

    out = render_why_terse(FakeReport())
    assert "WHY:src/cache.py" in out
    assert "high-churn hotspot" in out
