from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import LLMProviderType


def test_teach_generates_initial_output(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    task = service.start_task(
        title="Teach cache architecture",
        description="Explain the cache boundary before changing it.",
        labels=["teach"],
    )

    _, record, output = service.teach(
        task="explain the cache invalidation architecture",
        task_id=task.task_id,
        no_llm=True,
    )

    assert record.type.value == "teaching_output"
    assert output.current_implementation


def test_teach_followup_handles_question_with_mock_provider(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    service.configure_llm(
        provider=LLMProviderType.MOCK,
        model="mock-model",
        api_key_env_var=None,
        temperature=0.0,
        max_tokens=1200,
    )

    answer = service.teach_followup(
        task="explain the cache invalidation architecture",
        question="Why would a config-only approach fail?",
    )

    assert "config-only approach failed" in answer


def test_teach_interactive_exits_on_empty_input(sample_repo: Path, monkeypatch: object) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    service.configure_llm(
        provider=LLMProviderType.MOCK,
        model="mock-model",
        api_key_env_var=None,
        temperature=0.0,
        max_tokens=1200,
    )
    task = service.start_task(
        title="Teach cache architecture",
        description="Explain the cache boundary before changing it.",
        labels=["teach"],
    )

    result = runner.invoke(
        app,
        [
            "teach",
            "--task",
            "explain the cache invalidation architecture",
                "--task-id",
                task.task_id,
                "--interactive",
            ],
        input="\n",
    )

    assert result.exit_code == 0
    assert "Wrote output:" in result.stdout
