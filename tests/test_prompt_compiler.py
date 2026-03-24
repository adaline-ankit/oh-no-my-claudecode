from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.llm import provider_from_settings
from oh_no_my_claudecode.models import (
    AgentMode,
    AttemptKind,
    AttemptStatus,
    LLMProviderType,
    LLMSettings,
    MemoryArtifactType,
    ReviewModeOutput,
    SolveModeOutput,
    TeachModeOutput,
)


def test_compiled_prompt_includes_expected_sections(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    task = service.start_task(
        title="Fix flaky cache invalidation bug",
        description="Investigate worker refresh flow and repeated cache failures.",
        labels=["bug", "cache"],
    )
    service.add_attempt(
        task.task_id,
        summary="Try a narrow cache-only patch first.",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.REJECTED,
        reasoning_summary="The cache module showed the strongest churn.",
        evidence_for="The file history clustered around src/cache.py.",
        evidence_against="The worker refresh path still failed.",
        files_touched=["src/cache.py"],
    )
    service.add_memory_artifact(
        task.task_id,
        artifact_type=MemoryArtifactType.DESIGN_CONFLICT,
        title="Do not bypass the shared cache boundary",
        summary="A direct worker-side invalidation conflicts with the documented boundary.",
        why_it_matters=(
            "The architecture doc treats the shared cache boundary as a repo constraint."
        ),
        apply_when=None,
        avoid_when="The task touches worker refresh behavior.",
        evidence="docs/architecture.md states workers should not bypass the cache boundary.",
        related_files=["src/cache.py", "src/worker.py"],
        related_modules=["cache", "worker"],
        confidence=0.9,
    )

    prompt = service.compile_task_prompt(task.task_id, AgentMode.SOLVE)

    assert prompt.task_id == task.task_id
    assert prompt.section_titles == [
        "Mode",
        "Instructions",
        "Task",
        "Repo Context",
        "Relevant Repo Memory",
        "Prior Attempts",
        "Negative Memory",
        "Validation Guidance",
        "Provenance",
        "Output Contract",
    ]
    assert "## Negative Memory" in prompt.prompt
    assert "Do not bypass the shared cache boundary" in prompt.prompt
    assert "Try a narrow cache-only patch first." in prompt.prompt
    assert "## Validation Guidance" in prompt.prompt


def test_prompt_modes_change_system_prompt_and_contract(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    task = service.start_task(
        title="Explain cache behavior",
        description="Use the task memory to teach and review the fix path.",
        labels=["docs"],
    )

    solve = service.compile_task_prompt(task.task_id, AgentMode.SOLVE)
    review = service.compile_task_prompt(task.task_id, AgentMode.REVIEW)
    teach = service.compile_task_prompt(task.task_id, AgentMode.TEACH)

    assert "next best engineering approach" in solve.system_prompt
    assert "critique" in review.system_prompt
    assert "staff engineer" in teach.system_prompt

    assert "approach_summary" in solve.output_contract
    assert "required_tests" in review.output_contract
    assert "mental_model_upgrade" in teach.output_contract


def test_prompt_contains_provenance_aware_context(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    task = service.start_task(
        title="Review cache boundary",
        description="Review the architecture and risk of worker-side cache edits.",
        labels=["review"],
    )
    service.add_memory_artifact(
        task.task_id,
        artifact_type=MemoryArtifactType.DID_NOT_WORK,
        title="Cache-only patch missed the worker path",
        summary="A narrow cache edit did not touch the failing caller flow.",
        why_it_matters="Future agents should not repeat a cache-only patch for this bug class.",
        apply_when=None,
        avoid_when="The task involves worker refresh logic.",
        evidence="The worker test still failed after the narrow cache change.",
        related_files=["src/cache.py"],
        related_modules=["cache"],
        confidence=0.8,
    )

    prompt = service.compile_task_prompt(task.task_id, AgentMode.REVIEW)

    assert "Source:" in prompt.prompt
    assert "Task artifact: did_not_work:" in prompt.prompt
    assert "Avoid because:" in prompt.prompt


def test_compiled_prompt_works_with_mock_provider(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    task = service.start_task(
        title="Teach cache invalidation reasoning",
        description="Summarize the reasoning map for the cache boundary.",
        labels=["teach"],
    )
    solve_prompt = service.compile_task_prompt(task.task_id, AgentMode.SOLVE)
    review_prompt = service.compile_task_prompt(task.task_id, AgentMode.REVIEW)
    teach_prompt = service.compile_task_prompt(task.task_id, AgentMode.TEACH)

    solve_provider = provider_from_settings(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        mock_response_text=(
            '{"approach_summary":"Inspect cache boundary first","files_to_inspect":'
            '["src/cache.py"],"risks":["worker coupling"],"validations":["pytest"],'
            '"confidence":"medium"}'
        ),
    )
    review_provider = provider_from_settings(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        mock_response_text=(
            '{"concerns":["boundary bypass"],"assumptions":["tests are representative"],'
            '"likely_regressions":["worker refresh"],"required_tests":["tests/test_cache.py"]}'
        ),
    )
    teach_provider = provider_from_settings(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        mock_response_text=(
            '{"reasoning_map":["trace caller path","check invariant"],'
            '"system_lesson":"Shared boundaries matter",'
            '"false_lead_analysis":["cache-only patch"],'
            '"mental_model_upgrade":"Start from execution boundaries, not local churn."}'
        ),
    )

    solve_result = solve_provider.generate_structured(
        solve_prompt.to_generation_request(),
        SolveModeOutput,
    )
    review_result = review_provider.generate_structured(
        review_prompt.to_generation_request(),
        ReviewModeOutput,
    )
    teach_result = teach_provider.generate_structured(
        teach_prompt.to_generation_request(),
        TeachModeOutput,
    )

    assert solve_result.approach_summary == "Inspect cache boundary first"
    assert review_result.required_tests == ["tests/test_cache.py"]
    assert teach_result.system_lesson == "Shared boundaries matter"
