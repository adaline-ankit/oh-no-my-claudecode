from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.llm import LLMConfigurationError
from oh_no_my_claudecode.models import LLMProviderType, TaskOutputType


def test_solve_persists_task_linked_output_with_mock_provider(
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
        max_tokens=512,
    )
    task = service.start_task(
        title="Fix cache invalidation bug",
        description="Trace the invalidation boundary and preserve prior task memory.",
        labels=["bug"],
    )

    _, record, output = service.solve(
        task="Fix cache invalidation bug by checking the shared boundary first.",
        task_id=task.task_id,
    )

    assert record.task_id == task.task_id
    assert record.type == TaskOutputType.SOLVE_OUTPUT
    assert record.provider == "mock"
    assert Path(record.markdown_path).exists()
    assert output.approach_summary
    assert output.files_to_inspect == ["src/cache.py", "tests/test_cache.py"]

    persisted = service.get_task_output(record.output_id)
    assert persisted is not None
    assert persisted.output_id == record.output_id

    task_outputs = service.list_task_outputs_for_task(task.task_id)
    assert [item.output_id for item in task_outputs] == [record.output_id]


def test_review_persists_unlinked_output_and_uses_external_input(
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
        max_tokens=512,
    )

    _, record, output = service.review(
        task="Review a proposed fix for cache invalidation.",
        external_input="Plan: change src/cache.py and update tests/test_cache.py.",
    )

    assert record.task_id is None
    assert record.type == TaskOutputType.REVIEW_OUTPUT
    assert Path(record.markdown_path).exists()
    assert output.required_tests == ["tests/test_cache.py"]

    markdown = Path(record.markdown_path).read_text(encoding="utf-8")
    assert "ONMC Review Output" in markdown
    assert "Prompt Sections" in markdown


def test_solve_requires_configured_provider(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    with pytest.raises(LLMConfigurationError, match="not configured"):
        service.solve(task="Fix cache invalidation bug")


def test_cli_llm_modes_use_mock_provider_and_link_outputs(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)

    assert runner.invoke(app, ["init"]).exit_code == 0
    assert runner.invoke(app, ["ingest"]).exit_code == 0

    llm_configure_result = runner.invoke(
        app,
        [
            "llm",
            "configure",
            "--provider",
            "mock",
            "--model",
            "mock-model",
        ],
    )
    assert llm_configure_result.exit_code == 0

    task_start_result = runner.invoke(
        app,
        [
            "task",
            "start",
            "--title",
            "Fix cache invalidation bug",
            "--description",
            "Investigate the invalidation boundary before changing worker code.",
        ],
    )
    assert task_start_result.exit_code == 0
    task_match = re.search(r"task-[0-9a-f]+", task_start_result.stdout)
    assert task_match is not None
    task_id = task_match.group(0)

    solve_result = runner.invoke(
        app,
        [
            "solve",
            "--task",
            "Fix cache invalidation bug by starting at the shared boundary.",
            "--task-id",
            task_id,
        ],
    )
    assert solve_result.exit_code == 0
    assert "Solve" in solve_result.stdout
    output_match = re.search(r"output-[0-9a-f]+", solve_result.stdout)
    assert output_match is not None
    output_id = output_match.group(0)

    input_file = tmp_path / "review-notes.md"
    input_file.write_text("Plan: touch src/cache.py and tests/test_cache.py.", encoding="utf-8")
    review_result = runner.invoke(
        app,
        [
            "review",
            "--task",
            "Review the proposed cache invalidation change.",
            "--input-file",
            str(input_file),
        ],
    )
    assert review_result.exit_code == 0
    assert "Required Tests" in review_result.stdout

    teach_result = runner.invoke(
        app,
        [
            "teach",
            "--task",
            "Teach the cache invalidation reasoning path for this bug.",
            "--task-id",
            task_id,
        ],
    )
    assert teach_result.exit_code == 0
    assert "Mental Model Upgrade" in teach_result.stdout

    task_show_result = runner.invoke(app, ["task", "show", task_id])
    assert task_show_result.exit_code == 0
    assert "LLM outputs:" in task_show_result.stdout
    assert output_id in task_show_result.stdout

    task_list_result = runner.invoke(app, ["task", "list"])
    assert task_list_result.exit_code == 0
    assert task_id in task_list_result.stdout
