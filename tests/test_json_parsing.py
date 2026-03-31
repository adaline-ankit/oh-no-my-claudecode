from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.llm import MockProvider, parse_llm_json
from oh_no_my_claudecode.models import LLMProviderType, LLMSettings


def test_parse_bare_json() -> None:
    assert parse_llm_json('{"key": "value"}') == {"key": "value"}


def test_parse_json_fence() -> None:
    assert parse_llm_json('```json\n{"key": "value"}\n```') == {"key": "value"}


def test_parse_plain_fence() -> None:
    assert parse_llm_json('```\n{"key": "value"}\n```') == {"key": "value"}


def test_parse_with_preamble() -> None:
    assert parse_llm_json('Here is the JSON:\n```json\n{"key": "value"}\n```') == {
        "key": "value"
    }


def test_parse_array() -> None:
    assert parse_llm_json('```json\n[{"kind": "decision"}]\n```') == [
        {"kind": "decision"}
    ]


def test_parse_invalid_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json("This is not JSON at all")


def test_solve_end_to_end_with_fence_response(sample_repo: Path, monkeypatch: object) -> None:
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
    fenced_provider = MockProvider(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        response_text=(
            "```json\n"
            '{"approach_summary":"Check the shared boundary first.",'
            '"files_to_inspect":["src/cache.py","tests/test_cache.py"],'
            '"risks":["Boundary coupling may be hidden."],'
            '"validations":["pytest","ruff check ."],'
            '"confidence":"medium"}'
            "\n```"
        ),
    )
    monkeypatch.setattr(service, "llm_provider", lambda: fenced_provider)

    _, record, output = service.solve(
        task="Fix cache invalidation bug by checking the shared boundary first.",
        task_id=task.task_id,
    )

    assert record.provider == "mock"
    assert output.approach_summary == "Check the shared boundary first."
    assert output.files_to_inspect == ["src/cache.py", "tests/test_cache.py"]
