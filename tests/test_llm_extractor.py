from __future__ import annotations

import sqlite3
from pathlib import Path

from oh_no_my_claudecode.config import default_config
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.ingest.llm_extractor import (
    _is_semantic_duplicate,
    batch_commits_for_llm,
    extract_llm_memories,
    get_batch_size,
)
from oh_no_my_claudecode.llm import provider_from_settings
from oh_no_my_claudecode.models import (
    LLMProviderType,
    LLMSettings,
    MemoryEntry,
    MemoryKind,
    SourceType,
)
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now


def test_commit_batching_keeps_stable_batch_sizes() -> None:
    commit_lines = [f"sha{i} | commit {i}" for i in range(123)]

    batches = batch_commits_for_llm(commit_lines)

    assert len(batches) == 3
    assert batches[0].count("\n") == 49
    assert batches[-1].count("\n") == 22
    assert "sha122 | commit 122" in batches[-1]


def test_get_batch_size_adapts_for_large_repos() -> None:
    assert get_batch_size(200) == 50
    assert get_batch_size(700) == 30
    assert get_batch_size(2000) == 20


def test_semantic_deduplication_uses_title_overlap() -> None:
    now = utc_now()
    existing = MemoryEntry(
        id="decision-1",
        kind=MemoryKind.DECISION,
        title="Shared cache boundary",
        summary="Existing summary",
        details="Existing summary",
        source_type=SourceType.DOC,
        source_ref="docs/architecture.md",
        tags=["cache", "boundary"],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    candidate = existing.model_copy(update={"id": "decision-2", "summary": "New summary"})

    assert _is_semantic_duplicate(candidate, [existing]) is True


def test_ingest_no_llm_falls_back_to_heuristic_only(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.configure_llm(
        provider=LLMProviderType.MOCK,
        model="mock-model",
        api_key_env_var=None,
        temperature=0.0,
        max_tokens=1200,
    )

    _, result = service.ingest(no_llm=True)

    assert result.memory_count > 0
    assert result.llm_new_memory_count == 0
    assert result.llm_deduped_count == 0


def test_extract_llm_memories_with_mock_provider(sample_repo: Path) -> None:
    provider = provider_from_settings(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        mock_response_text=(
            '[{"kind":"decision","title":"Shared cache boundary",'
            '"summary":"Use one boundary for invalidation.","confidence":0.91,'
            '"source_commits":["abc123"],"files_mentioned":["src/cache.py"]}]'
        ),
    )

    records, deduped, warnings = extract_llm_memories(
        repo_root=sample_repo,
        config=default_config(sample_repo),
        provider=provider,
        log_path=sample_repo / ".onmc" / "logs" / "llm-calls.jsonl",
        commit_lines=["abc123 | choose shared cache boundary | files: src/cache.py"],
        docs={},
        existing_memories=[],
    )

    assert deduped == 0
    assert len(records) == 1
    assert warnings == []
    assert records[0].source_type == SourceType.LLM_EXTRACTED
    assert records[0].kind == MemoryKind.DECISION


def test_extract_llm_memories_handles_malformed_json(sample_repo: Path) -> None:
    provider = provider_from_settings(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        mock_response_text="not json",
    )

    records, deduped, warnings = extract_llm_memories(
        repo_root=sample_repo,
        config=default_config(sample_repo),
        provider=provider,
        log_path=sample_repo / ".onmc" / "logs" / "llm-calls.jsonl",
        commit_lines=["abc123 | adjust cache boundary | files: src/cache.py"],
        docs={"docs/architecture.md": "We chose the shared cache boundary."},
        existing_memories=[],
    )

    assert records == []
    assert deduped == 0
    assert warnings == []


def test_memory_schema_columns_exist_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    storage = SQLiteStorage(db_path)

    storage.initialize()
    storage.initialize()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("PRAGMA table_info(memories)").fetchall()
    columns = {row[1] for row in rows}
    assert "confidence" in columns
    assert "source_type" in columns
