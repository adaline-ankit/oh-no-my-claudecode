from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.brief.compiler import compile_brief
from oh_no_my_claudecode.brief.llm_ranker import rerank_memories_with_llm
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.llm import provider_from_settings
from oh_no_my_claudecode.models import LLMProviderType, LLMSettings


def test_ranking_reorders_candidates_by_priority(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    memories = service.list_memories()[:3]
    provider = provider_from_settings(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        mock_response_text=(
            "["
            f'{{"memory_id":"{memories[1].id}","relevance_reason":"Best match","priority":10}},'
            f'{{"memory_id":"{memories[0].id}","relevance_reason":"Second best","priority":5}}'
            "]"
        ),
    )

    ranked, reasons = rerank_memories_with_llm(
        task="fix cache invalidation",
        candidates=memories,
        provider=provider,
        log_path=sample_repo / ".onmc" / "logs" / "llm-calls.jsonl",
    )

    assert [item.id for item in ranked[:2]] == [memories[1].id, memories[0].id]
    assert reasons[memories[1].id] == "Best match"


def test_brief_falls_back_without_provider(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    _, artifact = service.compile_brief("fix cache invalidation", no_llm=False)

    assert artifact.relevant_memories
    assert artifact.relevance_reasons == {}


def test_relevance_reason_appears_in_brief_output(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    repo_root, config, storage = service._load_context()
    memories = storage.list_memories()
    provider = provider_from_settings(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        mock_response_text=(
            "["
            f'{{"memory_id":"{memories[0].id}",'
            '"relevance_reason":"Directly constrains the fix path.",'
            '"priority":10}'
            "]"
        ),
    )

    artifact = compile_brief(
        repo_root,
        config,
        storage,
        "fix cache invalidation",
        provider=provider,
        log_path=sample_repo / ".onmc" / "logs" / "llm-calls.jsonl",
    )

    assert "Relevant because: Directly constrains the fix path." in artifact.to_markdown()
