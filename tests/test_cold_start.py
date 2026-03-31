from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.config import default_config
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.ingest.llm_extractor import (
    ExtractedKnowledgeItem,
    ExtractedKnowledgeList,
    extract_llm_memories,
    should_extract_file,
)
from oh_no_my_claudecode.llm import provider_from_settings
from oh_no_my_claudecode.models import LLMProviderType, LLMSettings, RepoFileRecord
from oh_no_my_claudecode.rendering.console import console
from oh_no_my_claudecode.setup.wizard import interactive_seed, should_seed_interactively


def test_should_extract_file_accepts_test_files_churn_and_todo(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_cache.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_example(): pass\n", encoding="utf-8")

    churn_file = tmp_path / "src" / "cache.py"
    churn_file.parent.mkdir(parents=True, exist_ok=True)
    churn_file.write_text("def invalidate(): pass\n", encoding="utf-8")

    todo_file = tmp_path / "src" / "worker.py"
    todo_file.write_text("# TODO: preserve worker invariant\n", encoding="utf-8")

    assert should_extract_file(test_file, []) is True
    assert should_extract_file(churn_file, [churn_file.as_posix()]) is True
    assert should_extract_file(todo_file, []) is True


def test_should_extract_file_rejects_generic_source_files(tmp_path: Path) -> None:
    source_file = tmp_path / "src" / "util.py"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("def helper(value: str) -> str:\n    return value\n", encoding="utf-8")

    assert should_extract_file(source_file, []) is False


def test_interactive_seed_stores_seeded_records(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    answers = iter(
        [
            "All LLM calls must go through the provider abstraction.",
            "Do not add a second database next to SQLite.",
            "src/oh_no_my_claudecode/cli.py",
        ]
    )
    monkeypatch.setattr(
        "oh_no_my_claudecode.setup.wizard.Prompt.ask",
        lambda *args, **kwargs: next(answers),
    )

    created = interactive_seed(console, service)
    memories = service.list_memories()

    assert created == 3
    assert {memory.kind.value for memory in memories} == {
        "invariant",
        "failed_approach",
        "hotspot",
    }
    assert all(memory.source_type.value == "manual_seed" for memory in memories)


def test_layer_two_runs_only_when_commit_layer_is_sparse(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    provider = provider_from_settings(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
    )
    repo_file = sample_repo / "src" / "cache.py"
    calls: list[int] = []

    def fake_generate(*args: object, **kwargs: object) -> ExtractedKnowledgeList:
        count = 7 if calls == [] else 8
        items = [
            ExtractedKnowledgeItem(
                kind="decision",
                title=f"Decision {index}",
                summary="Summary",
                confidence=0.8,
                source_commits=[f"sha{index}"],
                files_mentioned=["src/cache.py"],
            )
            for index in range(count)
        ]
        return ExtractedKnowledgeList(items)

    def fake_source_layer(**kwargs: object) -> list[object]:
        calls.append(1)
        return []

    monkeypatch.setattr(
        "oh_no_my_claudecode.ingest.llm_extractor.generate_structured_logged",
        fake_generate,
    )
    monkeypatch.setattr(
        "oh_no_my_claudecode.ingest.llm_extractor._extract_source_file_memories",
        fake_source_layer,
    )

    extract_llm_memories(
        repo_root=sample_repo,
        config=default_config(sample_repo),
        provider=provider,
        log_path=sample_repo / ".onmc" / "logs" / "llm-calls.jsonl",
        commit_lines=["sha1 | cache change | files: src/cache.py"],
        docs={},
        existing_memories=[],
        repo_files=[RepoFileRecord(path="src/cache.py")],
        git_churn_rank=["src/cache.py"],
    )
    assert len(calls) == 1

    calls.clear()
    monkeypatch.setattr(
        "oh_no_my_claudecode.ingest.llm_extractor.generate_structured_logged",
        lambda *args, **kwargs: ExtractedKnowledgeList(
            [
                ExtractedKnowledgeItem(
                    kind="decision",
                    title=f"Decision {index}",
                    summary="Summary",
                    confidence=0.8,
                    source_commits=[f"sha{index}"],
                    files_mentioned=["src/cache.py"],
                )
                for index in range(8)
            ]
        ),
    )
    extract_llm_memories(
        repo_root=sample_repo,
        config=default_config(sample_repo),
        provider=provider,
        log_path=sample_repo / ".onmc" / "logs" / "llm-calls.jsonl",
        commit_lines=["sha1 | cache change | files: src/cache.py"],
        docs={},
        existing_memories=[],
        repo_files=[RepoFileRecord(path=repo_file.relative_to(sample_repo).as_posix())],
        git_churn_rank=["src/cache.py"],
    )
    assert calls == []


def test_layer_three_only_triggers_for_tiny_memory_sets() -> None:
    assert should_seed_interactively(4, yes=False) is True
    assert should_seed_interactively(5, yes=False) is False
    assert should_seed_interactively(4, yes=True) is False
