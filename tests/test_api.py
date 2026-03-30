from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

import onmc
from oh_no_my_claudecode import OnmcRepo, init


def test_init_creates_repo_handle_and_state(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)

    repo = init(sample_repo)

    assert isinstance(repo, OnmcRepo)
    assert (sample_repo / ".onmc" / "config.yaml").exists()


def test_memory_api_add_and_list(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    memory = repo.memory.add(
        type="invariant",
        title="Keep cache boundary intact",
        summary="Do not bypass the shared cache boundary from worker flows.",
    )
    items = repo.memory.list(kind="invariant")

    assert any(item.id == memory.id for item in items if hasattr(item, "id"))


def test_task_api_start_and_end(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)

    task = repo.task.start(
        title="Fix cache invalidation",
        description="Track the flaky cache issue.",
        label="cache,bug",
    )
    ended = repo.task.end(task.task_id, "solved", "Fixed at the shared cache boundary.")

    assert task.status.value == "active"
    assert ended.status.value == "solved"
    assert ended.final_summary == "Fixed at the shared cache boundary."


def test_sync_api_commit_and_restore_round_trip(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    task = repo.task.start(title="Track cache issue", description="Capture memory state.")
    repo.memory.add(
        type="fix",
        task_id=task.task_id,
        title="Start at the cache boundary",
        summary="The shared cache boundary is the safest first patch point.",
    )

    export_dir = sample_repo / ".agent-memory"
    commit_result = repo.sync.commit(str(export_dir))
    shutil.rmtree(sample_repo / ".onmc")

    restored_repo = init(sample_repo)
    restore_result = restored_repo.sync.restore(str(export_dir))

    assert commit_result.task_count >= 1
    assert restore_result.task_count >= 1
    assert restored_repo.task.show(task.task_id) is not None


def test_memory_api_search_returns_ranked_results(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    results = repo.memory.search(files=["src/cache.py"])

    assert results


def test_py_typed_marker_is_packaged() -> None:
    marker = resources.files("oh_no_my_claudecode").joinpath("py.typed")

    assert marker.is_file()


def test_onmc_import_alias_exposes_public_api() -> None:
    assert onmc.OnmcRepo is OnmcRepo
    assert onmc.init is init
