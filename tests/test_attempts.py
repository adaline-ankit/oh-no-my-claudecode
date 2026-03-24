from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import AttemptKind, AttemptStatus


def test_attempt_creation_persists(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    task = service.start_task(
        title="Fix flaky cache invalidation bug",
        description="Track cache invalidation debugging.",
        labels=["bug"],
    )

    attempt = service.add_attempt(
        task.task_id,
        summary="Patch cache invalidation flow and rerun targeted tests.",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.TRIED,
        reasoning_summary="Recent churn points at the cache module.",
        evidence_for="The failing path hits src/cache.py repeatedly.",
        evidence_against=None,
        files_touched=["src/cache.py", "tests/test_cache.py"],
    )

    persisted = service.get_attempt(attempt.attempt_id)
    assert persisted is not None
    assert persisted.attempt_id.startswith("attempt-")
    assert persisted.task_id == task.task_id
    assert persisted.status == AttemptStatus.TRIED
    assert persisted.files_touched == ["src/cache.py", "tests/test_cache.py"]


def test_attempts_attach_to_valid_task(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    first_task = service.start_task(
        title="First task",
        description="First task description.",
        labels=["one"],
    )
    second_task = service.start_task(
        title="Second task",
        description="Second task description.",
        labels=["two"],
    )
    first_attempt = service.add_attempt(
        first_task.task_id,
        summary="Investigate cache path.",
        kind=AttemptKind.INVESTIGATION,
        status=AttemptStatus.PROPOSED,
        reasoning_summary=None,
        evidence_for=None,
        evidence_against=None,
        files_touched=[],
    )
    service.add_attempt(
        second_task.task_id,
        summary="Try a separate test strategy.",
        kind=AttemptKind.TEST_STRATEGY,
        status=AttemptStatus.TRIED,
        reasoning_summary=None,
        evidence_for=None,
        evidence_against=None,
        files_touched=["tests/test_cache.py"],
    )

    first_attempts = service.list_attempts_for_task(first_task.task_id)

    assert [attempt.attempt_id for attempt in first_attempts] == [first_attempt.attempt_id]
    assert all(attempt.task_id == first_task.task_id for attempt in first_attempts)


def test_attempt_status_update_persists(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    task = service.start_task(
        title="Refine test strategy",
        description="Track a failing test strategy attempt.",
        labels=["tests"],
    )
    attempt = service.add_attempt(
        task.task_id,
        summary="Run a narrower test selection first.",
        kind=AttemptKind.TEST_STRATEGY,
        status=AttemptStatus.TRIED,
        reasoning_summary="The broader suite is too noisy.",
        evidence_for=None,
        evidence_against=None,
        files_touched=["tests/test_cache.py"],
    )

    updated = service.update_attempt(
        attempt.attempt_id,
        status=AttemptStatus.REJECTED,
        evidence_against="The narrowed test run missed the real cache failure path.",
    )

    persisted = service.get_attempt(attempt.attempt_id)
    assert updated.status == AttemptStatus.REJECTED
    assert updated.closed_at is not None
    assert persisted is not None
    assert persisted.status == AttemptStatus.REJECTED
    assert persisted.evidence_against == updated.evidence_against


def test_attempt_listing_for_task_returns_newest_first(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    task = service.start_task(
        title="Track multiple attempts",
        description="Ensure attempts list newest first.",
        labels=["attempts"],
    )
    first = service.add_attempt(
        task.task_id,
        summary="First attempt.",
        kind=AttemptKind.OTHER,
        status=AttemptStatus.PROPOSED,
        reasoning_summary=None,
        evidence_for=None,
        evidence_against=None,
        files_touched=[],
    )
    second = service.add_attempt(
        task.task_id,
        summary="Second attempt.",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.TRIED,
        reasoning_summary=None,
        evidence_for=None,
        evidence_against=None,
        files_touched=["src/cache.py"],
    )

    attempts = service.list_attempts_for_task(task.task_id)

    assert [attempt.attempt_id for attempt in attempts[:2]] == [
        second.attempt_id,
        first.attempt_id,
    ]
