from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import TaskStatus


def test_task_creation_persists(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    task = service.start_task(
        title="Fix flaky cache invalidation bug",
        description="Investigate worker refresh flow and test churn.",
        labels=["bug", "cache"],
    )

    persisted = service.get_task(task.task_id)
    assert persisted is not None
    assert persisted.task_id.startswith("task-")
    assert persisted.status == TaskStatus.ACTIVE
    assert persisted.started_at is not None
    assert persisted.labels == ["bug", "cache"]
    assert persisted.repo_root == sample_repo.as_posix()


def test_task_status_transition_persists(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    task = service.start_task(
        title="Unblock cache worker",
        description="Track blocked work for cache worker refresh.",
        labels=["blocked"],
    )

    updated = service.update_task_status(task.task_id, TaskStatus.BLOCKED)

    assert updated.status == TaskStatus.BLOCKED
    assert updated.ended_at is None
    assert service.get_task(task.task_id) is not None
    assert service.get_task(task.task_id).status == TaskStatus.BLOCKED


def test_task_listing_returns_started_tasks(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    first = service.start_task(
        title="First task",
        description="First task description.",
        labels=["one"],
    )
    second = service.start_task(
        title="Second task",
        description="Second task description.",
        labels=["two"],
    )

    tasks = service.list_tasks()

    assert [task.task_id for task in tasks[:2]] == [second.task_id, first.task_id]


def test_task_end_persists_summary(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    task = service.start_task(
        title="Close cache bug",
        description="Resolve cache invalidation bug.",
        labels=["bug"],
    )

    ended = service.end_task(
        task.task_id,
        status=TaskStatus.SOLVED,
        summary="Fixed cache invalidation and updated the related test path.",
    )

    persisted = service.get_task(task.task_id)
    assert ended.status == TaskStatus.SOLVED
    assert ended.final_summary is not None
    assert ended.ended_at is not None
    assert persisted is not None
    assert persisted.status == TaskStatus.SOLVED
    assert persisted.final_summary == ended.final_summary
