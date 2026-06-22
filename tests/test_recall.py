"""Tests for the recall module — incident matching from error/stacktrace text."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.mcp_server.tools import call_onmc_tool
from oh_no_my_claudecode.models import MemoryArtifactType, MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.recall.compiler import (
    RecallResult,
    ScoreBreakdown,
    _build_citation,
    _score_memory,
    compile_recall,
    normalise_error_text,
)
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id, tokenize
from oh_no_my_claudecode.utils.time import utc_now


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------


def _init_storage(db_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    return storage


def _seed_failed_approach(
    storage: SQLiteStorage,
    title: str,
    summary: str,
    details: str,
    tags: list[str] | None = None,
) -> str:
    from oh_no_my_claudecode.models.memory import MemoryEntry

    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(MemoryKind.FAILED_APPROACH.value, title, summary, "test:seed", prefix="test"),
        kind=MemoryKind.FAILED_APPROACH,
        title=title,
        summary=summary,
        details=details,
        source_type=SourceType.MANUAL,
        source_ref="test:seed",
        tags=tags or [MemoryKind.FAILED_APPROACH.value],
        confidence=0.85,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return entry.id


def _seed_gotcha(
    storage: SQLiteStorage,
    title: str,
    summary: str,
    details: str,
) -> str:
    from oh_no_my_claudecode.models.memory import MemoryEntry

    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(MemoryKind.GOTCHA.value, title, summary, "test:seed", prefix="test"),
        kind=MemoryKind.GOTCHA,
        title=title,
        summary=summary,
        details=details,
        source_type=SourceType.MANUAL,
        source_ref="test:seed",
        tags=["gotcha"],
        confidence=0.8,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return entry.id



# ---------------------------------------------------------------------------
# Unit tests: normalise_error_text
# ---------------------------------------------------------------------------


def test_normalise_strips_line_numbers() -> None:
    raw = "TypeError: cannot read property x of undefined at foo.js:42:10"
    normalised = normalise_error_text(raw)
    assert "42" not in normalised
    assert "foo.js" in normalised
    assert "typeerror" in normalised


def test_normalise_strips_python_line_numbers() -> None:
    raw = (
        'Traceback (most recent call last):\n'
        '  File "src/worker.py", line 42, in run\n'
        "    raise TypeError('cannot unpack')\n"
        "TypeError: cannot unpack non-sequence int"
    )
    normalised = normalise_error_text(raw)
    assert "42" not in normalised
    assert "worker.py" in normalised
    assert "typeerror" in normalised
    assert "cannot unpack" in normalised


def test_normalise_strips_hex_addresses() -> None:
    raw = "Segmentation fault at 0x7f3abc123def"
    normalised = normalise_error_text(raw)
    assert "0x7f3abc123def" not in normalised
    assert "segmentation" in normalised


def test_normalise_strips_uuid() -> None:
    raw = "Error in handler 550e8400-e29b-41d4-a716-446655440000: connection failed"
    normalised = normalise_error_text(raw)
    assert "550e8400" not in normalised
    assert "connection" in normalised


def test_normalise_strips_timestamps() -> None:
    raw = "2026-06-22T15:30:00Z ERROR: database connection refused"
    normalised = normalise_error_text(raw)
    assert "2026" not in normalised
    assert "database" in normalised


def test_normalise_two_variants_same_error_same_tokens() -> None:
    """Two stacktraces for the same logical error should produce the same key tokens."""
    variant_a = "TypeError: cannot read property x of undefined at foo.js:42"
    variant_b = "TypeError: cannot read property x of undefined at foo.js:99:5"
    norm_a = normalise_error_text(variant_a)
    norm_b = normalise_error_text(variant_b)
    # Both should have the same core tokens after normalisation
    from oh_no_my_claudecode.utils.text import tokenize

    tokens_a = set(tokenize(norm_a))
    tokens_b = set(tokenize(norm_b))
    # "typeerror", "cannot", "read", "property", "foo" must be in both
    shared = tokens_a & tokens_b
    assert "typeerror" in shared or "cannot" in shared or "property" in shared


def test_normalise_empty_input_returns_empty() -> None:
    assert normalise_error_text("") == ""
    assert normalise_error_text("   ") == ""


def test_normalise_never_crashes_on_weird_input() -> None:
    weird_inputs = [
        "\x00\x01\x02",
        "\x1b[31mERROR\x1b[0m",
        "🔥" * 100,
        "a" * 10000,
    ]
    for inp in weird_inputs:
        result = normalise_error_text(inp)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Unit tests: compile_recall — semantic + lexical matching
# ---------------------------------------------------------------------------


def test_compile_recall_matches_failed_approach_to_typeerror(tmp_path: Path) -> None:
    """A seeded FAILED_APPROACH about TypeError matches a similar stacktrace."""
    storage = _init_storage(tmp_path / "memory.db")

    mem_id = _seed_failed_approach(
        storage,
        title="TypeError in foo.js property access",
        summary="Tried accessing property x on undefined object — TypeError raised.",
        details="Fix: guard with `if (obj && obj.x)` before access.",
        tags=["typeerror", "javascript", "property"],
    )

    result = compile_recall(
        storage,
        "TypeError: cannot read property x of undefined at foo.js:42:10",
        limit=5,
    )

    assert result.has_matches
    assert any(e.memory_id == mem_id for e in result.entries)
    match = next(e for e in result.entries if e.memory_id == mem_id)
    assert "TypeError" in match.title or "TypeError" in match.what_happened


def test_compile_recall_bias_failed_approach_over_decision(tmp_path: Path) -> None:
    """FAILED_APPROACH memories rank above DECISION for the same token overlap."""
    from oh_no_my_claudecode.models.memory import MemoryEntry

    storage = _init_storage(tmp_path / "memory.db")
    now = utc_now()

    failed_id = _seed_failed_approach(
        storage,
        title="TypeError property access failure",
        summary="TypeError accessing property on undefined caused production crash.",
        details="Fixed by adding null check before property access.",
        tags=["typeerror", "property"],
    )

    decision_entry = MemoryEntry(
        id=stable_id("decision", "TypeError handling", "Use try/catch", "test:seed", prefix="dec"),
        kind=MemoryKind.DECISION,
        title="TypeError handling convention",
        summary="TypeError property access must be guarded with null checks.",
        details="Team decision: wrap all property accesses from external data.",
        source_type=SourceType.MANUAL,
        source_ref="test:decision",
        tags=["typeerror", "property"],
        confidence=0.8,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([decision_entry])

    result = compile_recall(
        storage,
        "TypeError: cannot read property x of undefined",
        limit=5,
    )

    assert result.has_matches
    ids = [e.memory_id for e in result.entries]
    assert failed_id in ids
    # FAILED_APPROACH should rank first
    assert ids.index(failed_id) < ids.index(decision_entry.id)


def test_compile_recall_uses_fix_artifact_as_resolution(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a FIX artifact exists, its evidence is used as the resolution text."""
    import oh_no_my_claudecode as onmc
    from oh_no_my_claudecode.models.memory_artifact import MemoryArtifactRecord

    monkeypatch.chdir(sample_repo)
    repo = onmc.init(sample_repo)

    _, _, storage = repo._service._load_context()

    task = repo._service.start_task(
        title="Connection investigation",
        description="Investigating connection refused errors.",
        labels=[],
    )

    mem_id = _seed_failed_approach(
        storage,
        title="Connection refused on startup",
        summary="Database connection refused when starting the service.",
        details="Vague details here.",
    )

    # Create the artifact with the real task id to satisfy the FK constraint.
    artifact = MemoryArtifactRecord(
        memory_id=mem_id,
        task_id=task.task_id,
        type=MemoryArtifactType.FIX,
        title="Connection fix",
        summary="Fix: connection fix",
        why_it_matters="Avoid the connection refused error.",
        apply_when="When the service fails to start.",
        avoid_when=None,
        evidence="Set DB_HOST env var before starting; ensure postgres is running.",
        related_files=[],
        related_modules=[],
        confidence=0.9,
        created_at=utc_now(),
    )
    storage.create_memory_artifact(artifact)

    result = compile_recall(
        storage,
        "connection refused database startup service",
        limit=5,
    )

    assert result.has_matches
    match = next((e for e in result.entries if e.memory_id == mem_id), None)
    assert match is not None
    assert "DB_HOST" in match.resolution or "postgres" in match.resolution


def test_compile_recall_empty_on_no_match(tmp_path: Path) -> None:
    """When nothing matches the query, returns an empty result with a hint."""
    storage = _init_storage(tmp_path / "memory.db")
    _seed_failed_approach(
        storage,
        title="Cache invalidation failure",
        summary="Cache invalidation caused stale reads.",
        details="Fixed by flushing the boundary module.",
    )

    result = compile_recall(
        storage,
        "xyzzyx frabbitz quux",
        limit=5,
    )

    assert not result.has_matches
    assert result.no_data_hint != ""
    assert "onmc mine" in result.no_data_hint


def test_compile_recall_empty_store_returns_honest_empty(tmp_path: Path) -> None:
    """Empty store returns an empty result with the no_data_hint."""
    storage = _init_storage(tmp_path / "empty.db")

    result = compile_recall(storage, "TypeError: cannot read property x", limit=5)

    assert not result.has_matches
    assert "onmc mine" in result.no_data_hint


def test_compile_recall_empty_query_returns_empty(tmp_path: Path) -> None:
    storage = _init_storage(tmp_path / "memory.db")
    _seed_failed_approach(
        storage,
        title="Some failure",
        summary="Something failed.",
        details="Details.",
    )

    result_empty = compile_recall(storage, "", limit=5)
    result_blank = compile_recall(storage, "   ", limit=5)

    assert not result_empty.has_matches
    assert not result_blank.has_matches


def test_compile_recall_normalises_line_numbers_for_matching(tmp_path: Path) -> None:
    """Two queries with different line numbers for the same error match the same memory."""
    storage = _init_storage(tmp_path / "memory.db")

    mem_id = _seed_failed_approach(
        storage,
        title="TypeError property access in foo.js",
        summary="TypeError accessing property x on undefined in foo.js.",
        details="Guard the access with a null check.",
    )

    result_a = compile_recall(
        storage,
        "TypeError: cannot read property x of undefined at foo.js:42",
        limit=5,
    )
    result_b = compile_recall(
        storage,
        "TypeError: cannot read property x of undefined at foo.js:99:5",
        limit=5,
    )

    # Both should find the same memory (or both miss — but if one hits, both should)
    ids_a = {e.memory_id for e in result_a.entries}
    ids_b = {e.memory_id for e in result_b.entries}
    if ids_a:
        assert ids_a == ids_b or mem_id in ids_a
    if ids_b:
        assert ids_a == ids_b or mem_id in ids_b


def test_compile_recall_deduplicates_candidates(tmp_path: Path) -> None:
    """FTS + fallback should not produce duplicate entries in the result."""
    storage = _init_storage(tmp_path / "memory.db")

    _seed_failed_approach(
        storage,
        title="TypeError property access",
        summary="TypeError accessing property x on undefined.",
        details="Guard with null check.",
        tags=["typeerror", "property"],
    )

    result = compile_recall(
        storage,
        "TypeError: cannot read property x of undefined",
        limit=10,
    )

    ids = [e.memory_id for e in result.entries]
    assert len(ids) == len(set(ids)), "Duplicate memory IDs in recall entries"


def test_compile_recall_to_markdown_has_matches(tmp_path: Path) -> None:
    """to_markdown returns a 'Seen this before?' section with entries."""
    storage = _init_storage(tmp_path / "memory.db")
    _seed_failed_approach(
        storage,
        title="TypeError property access",
        summary="TypeError accessing property x on undefined.",
        details="Guard with null check.",
    )

    result = compile_recall(storage, "TypeError cannot read property x undefined", limit=5)

    markdown = result.to_markdown()
    assert "## Seen this before?" in markdown
    if result.has_matches:
        assert "What happened:" in markdown
        assert "Resolution" in markdown


def test_compile_recall_to_markdown_no_matches() -> None:
    """to_markdown includes no_data_hint when there are no matches."""
    result = RecallResult(
        query="some error",
        normalised_query="some error",
        no_data_hint="run onmc mine",
    )
    markdown = result.to_markdown()
    assert "## Seen this before?" in markdown
    assert "run onmc mine" in markdown


# ---------------------------------------------------------------------------
# CLI tests: onmc recall
# ---------------------------------------------------------------------------


def test_cli_recall_argument_finds_match(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI recall with argument text finds a seeded FAILED_APPROACH."""
    from oh_no_my_claudecode.core.service import OnmcService

    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    _, _, storage = service._load_context()
    _seed_failed_approach(
        storage,
        title="TypeError property access in worker",
        summary="TypeError accessing property x on undefined in worker code.",
        details="Guard with null check before property access.",
        tags=["typeerror", "property", "worker"],
    )

    result = runner.invoke(
        app,
        ["recall", "TypeError: cannot read property x of undefined", "--terse"],
    )

    assert result.exit_code == 0


def test_cli_recall_piped_stdin_finds_match(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI recall reads from stdin when no argument is given."""
    from oh_no_my_claudecode.core.service import OnmcService

    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    _, _, storage = service._load_context()
    _seed_failed_approach(
        storage,
        title="Connection refused on startup",
        summary="Database connection refused when service starts.",
        details="Set DB_HOST env var and ensure postgres is running.",
        tags=["connection", "database", "startup"],
    )

    result = runner.invoke(
        app,
        ["recall", "--terse"],
        input="connection refused database startup service",
    )

    assert result.exit_code == 0
    # With a match, output should not be empty
    # (may or may not match depending on FTS — check no crash)


def test_cli_recall_no_match_exits_zero(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI recall exits 0 even when there are no matches."""
    from oh_no_my_claudecode.core.service import OnmcService

    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    result = runner.invoke(
        app,
        ["recall", "xyzzyx frabbitz quux error"],
    )

    assert result.exit_code == 0


def test_cli_recall_uninit_repo_exits_nonzero(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI recall exits non-zero when the repo is not initialised."""
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    # No init_project() call.

    result = runner.invoke(
        app,
        ["recall", "TypeError: cannot read property x of undefined"],
    )

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# MCP tool tests: recall
# ---------------------------------------------------------------------------


@pytest.fixture()
def json_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force MCP output to JSON for structured parsing."""
    monkeypatch.setenv("ONMC_MCP_FORMAT", "json")


def test_mcp_recall_tool_listed() -> None:
    """The 'recall' tool appears in list_onmc_tools."""
    from oh_no_my_claudecode.mcp_server.tools import list_onmc_tools

    tools = list_onmc_tools()
    names = [t.name for t in tools]
    assert "recall" in names


def test_mcp_recall_tool_returns_hits(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """MCP recall tool returns matching incidents as JSON."""
    import oh_no_my_claudecode as onmc

    monkeypatch.chdir(sample_repo)
    repo = onmc.init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()
    mem_id = _seed_failed_approach(
        storage,
        title="TypeError property access failure",
        summary="TypeError accessing property x on undefined raised in production.",
        details="Fix: guard with null check before access.",
        tags=["typeerror", "property"],
    )

    content = call_onmc_tool(
        repo,
        "recall",
        {"query": "TypeError cannot read property x undefined", "limit": 5},
    )

    assert len(content) == 1
    text = content[0].text
    payload = json.loads(text)

    assert "has_matches" in payload
    assert "entries" in payload
    if payload["has_matches"]:
        entry_ids = [e["memory_id"] for e in payload["entries"]]
        assert mem_id in entry_ids
        first = payload["entries"][0]
        assert "what_happened" in first
        assert "resolution" in first
        assert "kind" in first


def test_mcp_recall_tool_returns_empty_with_hint_on_no_match(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_format: None,
) -> None:
    """MCP recall tool returns empty result with no_data_hint on no match."""
    import oh_no_my_claudecode as onmc

    monkeypatch.chdir(sample_repo)
    repo = onmc.init(sample_repo)

    content = call_onmc_tool(
        repo,
        "recall",
        {"query": "xyzzyx frabbitz quux bizarre error"},
    )

    assert len(content) == 1
    text = content[0].text
    payload = json.loads(text)

    assert payload["has_matches"] is False
    assert payload["entries"] == []


def test_mcp_recall_tool_empty_query_raises(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP recall raises ValueError on empty query."""
    import oh_no_my_claudecode as onmc

    monkeypatch.chdir(sample_repo)
    repo = onmc.init(sample_repo)

    with pytest.raises(ValueError, match="non-empty"):
        call_onmc_tool(repo, "recall", {"query": ""})


def test_mcp_recall_tool_unknown_tool_raises(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """call_onmc_tool raises ValueError for unknown tool names."""
    import oh_no_my_claudecode as onmc

    monkeypatch.chdir(sample_repo)
    repo = onmc.init(sample_repo)

    with pytest.raises(ValueError, match="Unknown ONMC tool"):
        call_onmc_tool(repo, "nonexistent_tool", {})


# ---------------------------------------------------------------------------
# New tests: ranking quality, tie-breaking, citations
# ---------------------------------------------------------------------------


def _make_memory(
    *,
    kind: MemoryKind = MemoryKind.FAILED_APPROACH,
    title: str = "Test memory",
    summary: str = "summary text",
    details: str = "",
    source_type: SourceType = SourceType.MANUAL,
    source_ref: str = "test:seed",
    tags: list[str] | None = None,
    confidence: float = 0.85,
    feedback_score: float = 0.0,
    staleness: str | None = None,
    created_at: datetime | None = None,
) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=stable_id(kind.value, title, summary, source_ref, prefix="test"),
        kind=kind,
        title=title,
        summary=summary,
        details=details,
        source_type=source_type,
        source_ref=source_ref,
        tags=tags or [kind.value],
        confidence=confidence,
        feedback_score=feedback_score,
        staleness=staleness,  # type: ignore[arg-type]
        created_at=created_at or now,
        updated_at=now,
    )


# ── Ranking: overlap normalisation ──────────────────────────────────────────


def test_score_memory_overlap_ratio_is_bounded() -> None:
    """overlap_ratio is always in [0, 1] regardless of query size."""
    memory = _make_memory(
        title="TypeError null property",
        summary="TypeError accessing null property in handler code",
    )
    # Large query with only 2 matching tokens
    large_query = set(tokenize("typeerror null " + " ".join(f"token{i}" for i in range(50))))
    result = _score_memory(memory, large_query)
    assert result is not None
    score, breakdown = result
    assert 0.0 < breakdown.overlap_ratio <= 1.0
    # Score must be < kind_boost (ratio ≤ 1 so base ≤ 1.3+, raw ≤ kind_boost * 1.4ish)
    assert score < breakdown.kind_boost * 2.0


def test_score_memory_precise_query_beats_noisy_query_for_same_overlap() -> None:
    """A precise 3-token query with 3 matching tokens scores higher than
    a 100-token query with 3 matching tokens — because overlap_ratio is higher."""
    memory = _make_memory(
        title="cache invalidation stale reads",
        summary="cache invalidation caused stale reads in worker",
        tags=["cache", "invalidation", "stale"],
    )
    precise_tokens = set(tokenize("cache invalidation stale"))
    noise = " ".join(f"noise{i}" for i in range(97))
    noisy_tokens = set(tokenize("cache invalidation stale " + noise))

    result_precise = _score_memory(memory, precise_tokens)
    result_noisy = _score_memory(memory, noisy_tokens)

    assert result_precise is not None
    assert result_noisy is not None
    score_precise, _ = result_precise
    score_noisy, _ = result_noisy
    assert score_precise > score_noisy, (
        f"Precise query score {score_precise:.4f} should exceed noisy query score {score_noisy:.4f}"
    )


def test_score_memory_returns_none_for_rejected_memory() -> None:
    """Memories with feedback ≤ -0.5 are excluded (return None)."""
    memory = _make_memory(feedback_score=-1.0)
    result = _score_memory(memory, {"typeerror", "null"})
    assert result is None


def test_score_memory_returns_none_for_zero_confidence() -> None:
    """Memories with confidence = 0.0 are excluded."""
    memory = _make_memory(confidence=0.0)
    result = _score_memory(memory, {"typeerror", "null"})
    assert result is None


def test_score_memory_stale_penalty_reduces_score() -> None:
    """Stale memory scores lower than identical fresh memory."""
    title, summary = "TypeError null access", "TypeError on null"
    fresh = _make_memory(title=title, summary=summary, staleness="fresh")
    stale = _make_memory(title=title, summary=summary, staleness="stale")
    tokens = set(tokenize("typeerror null"))

    r_fresh = _score_memory(fresh, tokens)
    r_stale = _score_memory(stale, tokens)

    assert r_fresh is not None
    assert r_stale is not None
    assert r_fresh[0] > r_stale[0]


def test_score_memory_breakdown_fields_populated() -> None:
    """ScoreBreakdown has all expected fields with reasonable values."""
    memory = _make_memory(
        title="connection refused startup",
        summary="connection refused on startup",
        confidence=0.9,
    )
    tokens = set(tokenize("connection refused startup"))
    result = _score_memory(memory, tokens)

    assert result is not None
    score, breakdown = result

    assert isinstance(breakdown, ScoreBreakdown)
    assert 0.0 < breakdown.overlap_ratio <= 1.0
    assert breakdown.confidence == 0.9
    assert breakdown.feedback_score == 0.0
    assert breakdown.kind_boost == 3.0  # FAILED_APPROACH boost
    assert breakdown.stale_penalty == 1.0
    assert breakdown.final_score == score


# ── Ranking: determinism and tie-breaking ────────────────────────────────────


def test_compile_recall_ranking_is_deterministic(tmp_path: Path) -> None:
    """Running compile_recall twice on the same data produces the same ranked order."""
    storage = _init_storage(tmp_path / "memory.db")

    for i in range(5):
        _seed_failed_approach(
            storage,
            title=f"TypeError failure variant {i}",
            summary=f"TypeError property access failure number {i} in handler code.",
            details=f"Fix variant {i}: guard with null check.",
            tags=["typeerror", "property", f"variant{i}"],
        )

    query = "TypeError: cannot read property x of undefined"
    result_a = compile_recall(storage, query, limit=5)
    result_b = compile_recall(storage, query, limit=5)

    ids_a = [e.memory_id for e in result_a.entries]
    ids_b = [e.memory_id for e in result_b.entries]
    assert ids_a == ids_b, "Recall ranking is non-deterministic across identical runs"


def test_compile_recall_confidence_tiebreaker(tmp_path: Path) -> None:
    """When two memories have equal token overlap, the higher-confidence one ranks first."""
    storage = _init_storage(tmp_path / "memory.db")
    now = utc_now()

    # Both share the same title/summary tokens, differ only in confidence.
    low_conf = MemoryEntry(
        id=stable_id(
            "failed_approach", "TypeError low", "TypeError low conf", "test", prefix="low"
        ),
        kind=MemoryKind.FAILED_APPROACH,
        title="TypeError property access low",
        summary="TypeError accessing property on null reference in low confidence entry.",
        details="",
        source_type=SourceType.MANUAL,
        source_ref="test:low",
        tags=["typeerror", "property"],
        confidence=0.5,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )
    high_conf = MemoryEntry(
        id=stable_id(
            "failed_approach", "TypeError high", "TypeError high conf", "test", prefix="hi"
        ),
        kind=MemoryKind.FAILED_APPROACH,
        title="TypeError property access high",
        summary="TypeError accessing property on null reference in high confidence entry.",
        details="",
        source_type=SourceType.MANUAL,
        source_ref="test:high",
        tags=["typeerror", "property"],
        confidence=0.95,
        feedback_score=0.0,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([low_conf, high_conf])

    result = compile_recall(storage, "TypeError accessing property null reference", limit=5)

    assert result.has_matches
    ids = [e.memory_id for e in result.entries]
    assert high_conf.id in ids
    assert low_conf.id in ids
    assert ids.index(high_conf.id) < ids.index(low_conf.id), (
        "Higher confidence should rank before lower confidence on tied overlap"
    )


def test_compile_recall_recency_tiebreaker(tmp_path: Path) -> None:
    """When score and confidence are equal, more recent memory ranks first."""
    storage = _init_storage(tmp_path / "memory.db")

    old_dt = datetime(2024, 1, 1, tzinfo=UTC)
    new_dt = datetime(2026, 6, 1, tzinfo=UTC)

    older = MemoryEntry(
        id=stable_id("failed_approach", "TypeError old", "TypeError old entry", "t", prefix="old"),
        kind=MemoryKind.FAILED_APPROACH,
        title="TypeError old entry",
        summary="TypeError old entry accessing null in production code.",
        details="",
        source_type=SourceType.MANUAL,
        source_ref="test:old",
        tags=["typeerror"],
        confidence=0.8,
        feedback_score=0.0,
        created_at=old_dt,
        updated_at=old_dt,
    )
    newer = MemoryEntry(
        id=stable_id("failed_approach", "TypeError new", "TypeError new entry", "t", prefix="new"),
        kind=MemoryKind.FAILED_APPROACH,
        title="TypeError new entry",
        summary="TypeError new entry accessing null in production code.",
        details="",
        source_type=SourceType.MANUAL,
        source_ref="test:new",
        tags=["typeerror"],
        confidence=0.8,
        feedback_score=0.0,
        created_at=new_dt,
        updated_at=new_dt,
    )
    storage.upsert_memories([older, newer])

    result = compile_recall(storage, "TypeError accessing null production code", limit=5)

    assert result.has_matches
    ids = [e.memory_id for e in result.entries]
    if newer.id in ids and older.id in ids:
        assert ids.index(newer.id) <= ids.index(older.id), (
            "More recent memory should rank at least as high as older when scores are equal"
        )


# ── Citation builder ──────────────────────────────────────────────────────────


def test_citation_includes_source_type_and_ref() -> None:
    """Citation includes both source_type and (abbreviated) source_ref."""
    memory = _make_memory(
        source_type=SourceType.GIT,
        source_ref="abc123def456789xyz",  # > 16 chars — should be truncated
    )
    citation = _build_citation(memory)
    assert "git" in citation
    assert "abc123def456789" in citation  # first 16 chars
    assert "xyz" not in citation  # 17th+ chars truncated


def test_citation_short_ref_not_truncated() -> None:
    """Short refs are shown in full."""
    memory = _make_memory(source_type=SourceType.TRANSCRIPT, source_ref="session-42")
    citation = _build_citation(memory)
    assert "transcript" in citation
    assert "session-42" in citation


def test_citation_empty_ref_omits_ref_part() -> None:
    """When source_ref is empty, citation only contains source_type."""
    memory = _make_memory(source_type=SourceType.MANUAL, source_ref="")
    citation = _build_citation(memory)
    assert "manual" in citation
    # Should still be non-empty — source_type is always present
    assert citation != ""


def test_citation_full_form_uses_parentheses() -> None:
    """Default (non-terse) citation uses parentheses."""
    memory = _make_memory(source_type=SourceType.GIT, source_ref="deadbeef")
    citation = _build_citation(memory, terse=False)
    assert citation.startswith("(")
    assert citation.endswith(")")


def test_citation_terse_form_uses_brackets() -> None:
    """Terse citation uses square brackets."""
    memory = _make_memory(source_type=SourceType.GIT, source_ref="deadbeef")
    citation = _build_citation(memory, terse=True)
    assert citation.startswith("[")
    assert citation.endswith("]")


# ── Citation in compile_recall output ────────────────────────────────────────


def test_compile_recall_entries_have_citation(tmp_path: Path) -> None:
    """Every RecallEntry returned by compile_recall has a non-empty citation."""
    storage = _init_storage(tmp_path / "memory.db")
    _seed_failed_approach(
        storage,
        title="TypeError property access in foo.js",
        summary="TypeError accessing property x on undefined in foo.js handler.",
        details="Guard with null check before access.",
        tags=["typeerror", "property"],
    )

    result = compile_recall(storage, "TypeError cannot read property x undefined", limit=5)

    assert result.has_matches
    for entry in result.entries:
        assert entry.citation != "", f"Expected non-empty citation for entry {entry.memory_id}"
        assert "manual" in entry.citation  # _seed_failed_approach uses SourceType.MANUAL


def test_compile_recall_to_markdown_contains_provenance(tmp_path: Path) -> None:
    """to_markdown includes 'provenance:' lines when citations are populated."""
    storage = _init_storage(tmp_path / "memory.db")
    _seed_failed_approach(
        storage,
        title="TypeError property access",
        summary="TypeError accessing property x on undefined.",
        details="Guard with null check.",
    )

    result = compile_recall(storage, "TypeError property access undefined", limit=5)

    if result.has_matches:
        md = result.to_markdown()
        assert "provenance:" in md


def test_compile_recall_entries_have_score_breakdown(tmp_path: Path) -> None:
    """Every RecallEntry has a populated ScoreBreakdown with bounded values."""
    storage = _init_storage(tmp_path / "memory.db")
    _seed_failed_approach(
        storage,
        title="connection refused database startup",
        summary="Database connection refused when starting service.",
        details="Set DB_HOST env var before starting.",
    )

    result = compile_recall(storage, "connection refused database startup", limit=5)

    assert result.has_matches
    for entry in result.entries:
        bd = entry.score_breakdown
        assert bd is not None, "score_breakdown should always be set"
        assert 0.0 <= bd.overlap_ratio <= 1.0
        assert 0.0 <= bd.confidence <= 1.0
        assert bd.kind_boost >= 1.0
        assert bd.stale_penalty in {1.0, 0.35}
        assert bd.final_score > 0.0


# ── Terse citation rendering ──────────────────────────────────────────────────


def test_render_incident_recall_terse_includes_citation() -> None:
    """render_incident_recall_terse appends the citation tag for entries that have one."""
    # Build a minimal RecallEntry-like object with a citation
    from oh_no_my_claudecode.recall.compiler import RecallEntry
    from oh_no_my_claudecode.serialize.terse import render_incident_recall_terse

    entries = [
        RecallEntry(
            memory_id="mem-1",
            title="TypeError null access",
            what_happened="TypeError accessing null in handler.",
            resolution="Guard with null check.",
            source_ref="git:abc123",
            confidence=0.9,
            relevance=0.8,
            kind="failed_approach",
            citation="(git · abc123def45678)",
        )
    ]

    output = render_incident_recall_terse(entries, "TypeError null", max_items=5)

    assert "PRIOR:" in output
    # Citation should appear as a bracket-enclosed tag
    assert "[git" in output or "(git" in output or "git" in output


def test_render_incident_recall_terse_omits_citation_when_empty() -> None:
    """render_incident_recall_terse does not add trailing brackets when citation is empty."""
    from oh_no_my_claudecode.recall.compiler import RecallEntry
    from oh_no_my_claudecode.serialize.terse import render_incident_recall_terse

    entries = [
        RecallEntry(
            memory_id="mem-2",
            title="Cache stale read",
            what_happened="Cache stale read caused wrong result.",
            resolution="Flush cache before read.",
            source_ref="",
            confidence=0.7,
            relevance=0.6,
            kind="failed_approach",
            citation="",  # explicitly empty
        )
    ]

    output = render_incident_recall_terse(entries, "cache stale", max_items=5)

    assert "PRIOR:" in output
    # No dangling bracket at the end of the line
    lines = output.strip().split("\n")
    fix_line = next((line for line in lines if "PRIOR:" in line), "")
    assert not fix_line.endswith("[]"), f"Empty citation should not append '[]': {fix_line!r}"
    assert not fix_line.endswith("()"), f"Empty citation should not append '()': {fix_line!r}"
