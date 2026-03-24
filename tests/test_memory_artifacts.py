from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryArtifactType


def test_memory_artifact_creation_persists(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    task = service.start_task(
        title="Capture a durable fix",
        description="Track the working cache invalidation fix.",
        labels=["memory"],
    )

    artifact = service.add_memory_artifact(
        task.task_id,
        artifact_type=MemoryArtifactType.FIX,
        title="Keep cache invalidation inside the shared boundary",
        summary="Route worker refresh logic through the cache boundary and update the paired test.",
        why_it_matters="This is the fix that actually stabilized the worker refresh path.",
        apply_when="A change touches cache invalidation behavior from worker code.",
        avoid_when=None,
        evidence="The paired worker test passed only after the shared boundary was used.",
        related_files=["src/cache.py", "tests/test_cache.py"],
        related_modules=["cache"],
        confidence=0.9,
    )

    persisted = service.get_memory_artifact(artifact.memory_id)
    assert persisted is not None
    assert persisted.memory_id.startswith("artifact-")
    assert persisted.task_id == task.task_id
    assert persisted.type == MemoryArtifactType.FIX
    assert persisted.related_files == ["src/cache.py", "tests/test_cache.py"]
    assert persisted.related_modules == ["cache"]


def test_memory_artifact_filtering_by_type(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    task = service.start_task(
        title="Capture mixed memory artifacts",
        description="Store both working and failed approaches.",
        labels=["memory"],
    )

    service.add_memory_artifact(
        task.task_id,
        artifact_type=MemoryArtifactType.FIX,
        title="Working fix",
        summary="Use the shared boundary.",
        why_it_matters="It matched the worker and test path.",
        apply_when=None,
        avoid_when=None,
        evidence="Tests passed after the boundary was restored.",
        related_files=[],
        related_modules=[],
        confidence=0.8,
    )
    failed = service.add_memory_artifact(
        task.task_id,
        artifact_type=MemoryArtifactType.DID_NOT_WORK,
        title="Cache-only patch",
        summary="Patch only the cache module without updating the caller path.",
        why_it_matters="Future agents should not repeat this narrow fix.",
        apply_when=None,
        avoid_when="The failing path still crosses worker refresh logic.",
        evidence="The worker-side test kept failing after the narrow cache edit.",
        related_files=["src/cache.py"],
        related_modules=["cache"],
        confidence=0.85,
    )

    artifacts = service.list_memory_artifacts(
        artifact_type=MemoryArtifactType.DID_NOT_WORK
    )

    assert [artifact.memory_id for artifact in artifacts] == [failed.memory_id]
    assert all(artifact.type == MemoryArtifactType.DID_NOT_WORK for artifact in artifacts)


def test_memory_artifacts_attach_to_their_task(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    first_task = service.start_task(
        title="First memory task",
        description="Record one task artifact.",
        labels=["one"],
    )
    second_task = service.start_task(
        title="Second memory task",
        description="Record a different task artifact.",
        labels=["two"],
    )
    first_artifact = service.add_memory_artifact(
        first_task.task_id,
        artifact_type=MemoryArtifactType.GOTCHA,
        title="Worker tests hide cache issues",
        summary="A passing unit test did not cover the worker call path.",
        why_it_matters="Task-scoped memory should stay attached to the relevant task.",
        apply_when="A task touches worker refresh flow.",
        avoid_when=None,
        evidence="The regression only appeared in the worker-driven test.",
        related_files=["tests/test_cache.py"],
        related_modules=["worker"],
        confidence=0.75,
    )
    service.add_memory_artifact(
        second_task.task_id,
        artifact_type=MemoryArtifactType.VALIDATION,
        title="Run cache tests after worker changes",
        summary="Changes to worker refresh logic should rerun the cache test file.",
        why_it_matters="It catches regressions that do not show up in static inspection.",
        apply_when="A task edits the worker/cache boundary.",
        avoid_when=None,
        evidence="The paired cache test failed before the worker change was corrected.",
        related_files=["tests/test_cache.py"],
        related_modules=["worker", "cache"],
        confidence=0.8,
    )

    first_task_artifacts = service.list_memory_artifacts_for_task(first_task.task_id)

    assert [artifact.memory_id for artifact in first_task_artifacts] == [first_artifact.memory_id]
    assert all(artifact.task_id == first_task.task_id for artifact in first_task_artifacts)
