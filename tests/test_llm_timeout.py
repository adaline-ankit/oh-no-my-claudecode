from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.config import default_config
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.ingest.llm_extractor import (
    ExtractedKnowledgeItem,
    ExtractedKnowledgeList,
    batch_commits_for_llm,
    extract_llm_memories,
)
from oh_no_my_claudecode.llm import provider_from_settings
from oh_no_my_claudecode.models import LLMProviderType, LLMSettings


def test_timeout_in_one_batch_does_not_stop_full_extract(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    provider = provider_from_settings(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
    )
    calls = {"count": 0}

    def fake_generate(*args: object, **kwargs: object) -> ExtractedKnowledgeList:
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("read timed out")
        return ExtractedKnowledgeList(
            [
                ExtractedKnowledgeItem(
                    kind="decision" if calls["count"] == 2 else "invariant",
                    title=(
                        "Cache boundary rule"
                        if calls["count"] == 2
                        else "Worker retry invariant"
                    ),
                    summary="The shared cache boundary should stay intact.",
                    confidence=0.9,
                    source_commits=["sha2"],
                    files_mentioned=["src/cache.py"],
                )
            ]
        )

    monkeypatch.setattr(
        "oh_no_my_claudecode.ingest.llm_extractor.generate_structured_logged",
        fake_generate,
    )

    records, deduped, warnings = extract_llm_memories(
        repo_root=sample_repo,
        config=default_config(sample_repo),
        provider=provider,
        log_path=sample_repo / ".onmc" / "logs" / "llm-calls.jsonl",
        commit_lines=[f"sha{i} | commit {i} | files: src/cache.py" for i in range(60)],
        docs={},
        existing_memories=[],
        total_commit_count=1500,
    )

    assert deduped == 0
    assert len(records) == 2
    assert "timeout" in warnings[0].lower()


def test_commit_batching_caps_llm_window_at_500() -> None:
    commit_lines = [f"sha{i} | commit {i}" for i in range(700)]

    batches = batch_commits_for_llm(commit_lines, total_commits=2500)

    assert sum(batch.count("\n") + 1 for batch in batches) == 500


def test_timeout_warning_surfaces_in_ingest_notes(
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

    monkeypatch.setattr(
        "oh_no_my_claudecode.ingest.pipeline.extract_llm_memories",
        lambda **kwargs: ([], 0, ["LLM commit extraction skipped 1 batch due to timeout."]),
    )

    _, result = service.ingest()

    assert any("timed out" in note.lower() or "timeout" in note.lower() for note in result.notes)
