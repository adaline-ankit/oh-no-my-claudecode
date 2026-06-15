"""Tests for the `onmc spec` command and the spec validator.

Covers:
- `onmc spec validate` PASSES on a real .agent-memory/ produced by `onmc sync --commit`.
- `onmc spec validate` FAILS with a clear error on corrupted records.
- `onmc spec print` shows the spec version.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import AttemptKind, AttemptStatus, MemoryArtifactType, TaskStatus
from oh_no_my_claudecode.spec.validator import SPEC_VERSION, validate_agent_memory_dir

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _seed_and_sync(repo: Path) -> Path:
    """Initialize, ingest, and sync a sample repo; return the .agent-memory/ dir."""
    service = OnmcService(repo)
    service.init_project()
    service.ingest()
    task = service.start_task(
        title="Fix cache bug",
        description="Track the cache invalidation regression.",
        labels=["bug"],
    )
    service.add_attempt(
        task.task_id,
        summary="Try narrowing the invalidation window",
        kind=AttemptKind.FIX_ATTEMPT,
        status=AttemptStatus.REJECTED,
        reasoning_summary="Seemed targeted at the hot path.",
        evidence_for="README mentions the cache boundary.",
        evidence_against="Worker refresh still failed in integration.",
        files_touched=["src/cache.py"],
    )
    service.add_memory_artifact(
        task.task_id,
        artifact_type=MemoryArtifactType.DID_NOT_WORK,
        title="Narrow fix missed worker path",
        summary="A narrow cache-only change missed the worker refresh caller.",
        why_it_matters="Future fixes should trace the full call graph.",
        apply_when=None,
        avoid_when="The task crosses the worker refresh boundary.",
        evidence="Integration tests failed after the patch.",
        related_files=["src/cache.py"],
        related_modules=["cache"],
        confidence=0.75,
    )
    service.end_task(task.task_id, status=TaskStatus.ABANDONED, summary="Deprioritised.")
    _, result = service.sync_commit()
    assert result.memory_count >= 1
    return repo / ".agent-memory"


# ---------------------------------------------------------------------------
# spec print
# ---------------------------------------------------------------------------


def test_spec_print_shows_version(sample_repo: Path, monkeypatch: object) -> None:
    """onmc spec print exits 0 and includes the spec version string."""
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    runner = _runner()
    result = runner.invoke(app, ["spec", "print"])

    assert result.exit_code == 0, result.output
    assert SPEC_VERSION in result.output
    assert "Agent Memory Format Specification" in result.output


# ---------------------------------------------------------------------------
# spec validate — PASS on real output
# ---------------------------------------------------------------------------


def test_spec_validate_passes_on_real_sync_output(
    sample_repo: Path, monkeypatch: object
) -> None:
    """validate_agent_memory_dir returns passed=True on a freshly-synced .agent-memory/."""
    monkeypatch.chdir(sample_repo)
    agent_memory_dir = _seed_and_sync(sample_repo)

    report = validate_agent_memory_dir(agent_memory_dir)

    assert report.passed, f"Expected PASS but got errors: {report.errors}"
    assert report.memories_checked >= 1
    assert report.tasks_checked == 1
    assert report.errors == []


def test_spec_validate_cli_passes_on_real_sync_output(
    sample_repo: Path, monkeypatch: object
) -> None:
    """onmc spec validate exits 0 on a freshly-synced .agent-memory/ directory."""
    monkeypatch.chdir(sample_repo)
    _seed_and_sync(sample_repo)

    runner = _runner()
    result = runner.invoke(app, ["spec", "validate"])

    assert result.exit_code == 0, result.output
    assert "PASS" in result.output


# ---------------------------------------------------------------------------
# spec validate — FAIL on corrupted records
# ---------------------------------------------------------------------------


def test_spec_validate_fails_on_missing_manifest(tmp_path: Path) -> None:
    """validate_agent_memory_dir fails when manifest.json is missing."""
    agent_memory = tmp_path / ".agent-memory"
    agent_memory.mkdir()
    (agent_memory / "memories").mkdir()

    report = validate_agent_memory_dir(agent_memory)

    assert not report.passed
    assert any("manifest.json" in err for err in report.errors)


def test_spec_validate_fails_on_missing_required_memory_field(
    sample_repo: Path, monkeypatch: object
) -> None:
    """validate_agent_memory_dir fails with a clear error when a memory is missing 'kind'."""
    monkeypatch.chdir(sample_repo)
    agent_memory_dir = _seed_and_sync(sample_repo)

    # Corrupt the first memory file by removing the 'kind' field.
    mem_files = sorted(agent_memory_dir.glob("memories/*/*.json"))
    assert mem_files, "Expected at least one memory file"
    first = mem_files[0]
    data = json.loads(first.read_text(encoding="utf-8"))
    del data["memory"]["kind"]
    first.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    report = validate_agent_memory_dir(agent_memory_dir)

    assert not report.passed
    assert any("kind" in err and "missing" in err for err in report.errors)


def test_spec_validate_fails_on_bad_memory_kind_enum(
    sample_repo: Path, monkeypatch: object
) -> None:
    """validate_agent_memory_dir fails when a memory has an unknown 'kind' value."""
    monkeypatch.chdir(sample_repo)
    agent_memory_dir = _seed_and_sync(sample_repo)

    mem_files = sorted(agent_memory_dir.glob("memories/*/*.json"))
    assert mem_files
    first = mem_files[0]
    data = json.loads(first.read_text(encoding="utf-8"))
    data["memory"]["kind"] = "not_a_real_kind"
    first.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    report = validate_agent_memory_dir(agent_memory_dir)

    assert not report.passed
    error_text = " ".join(report.errors)
    assert "not_a_real_kind" in error_text
    assert "kind" in error_text


def test_spec_validate_fails_on_bad_task_status_enum(
    sample_repo: Path, monkeypatch: object
) -> None:
    """validate_agent_memory_dir fails when a task has an invalid 'status' value."""
    monkeypatch.chdir(sample_repo)
    agent_memory_dir = _seed_and_sync(sample_repo)

    task_files = sorted(agent_memory_dir.glob("tasks/*.json"))
    assert task_files, "Expected at least one task file"
    task_path = task_files[0]
    data = json.loads(task_path.read_text(encoding="utf-8"))
    data["task"]["status"] = "bogus_status"
    task_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    report = validate_agent_memory_dir(agent_memory_dir)

    assert not report.passed
    error_text = " ".join(report.errors)
    assert "bogus_status" in error_text


def test_spec_validate_cli_exits_one_on_corrupted_dir(
    sample_repo: Path, monkeypatch: object
) -> None:
    """onmc spec validate exits with code 1 and prints errors on a corrupted directory."""
    monkeypatch.chdir(sample_repo)
    agent_memory_dir = _seed_and_sync(sample_repo)

    # Remove the manifest — the most obvious failure mode.
    (agent_memory_dir / "manifest.json").unlink()

    runner = _runner()
    result = runner.invoke(app, ["spec", "validate"])

    assert result.exit_code == 1
    assert "manifest" in result.output.lower()


def test_spec_validate_fails_on_missing_task_required_field(
    sample_repo: Path, monkeypatch: object
) -> None:
    """validate_agent_memory_dir fails when a task is missing a required field."""
    monkeypatch.chdir(sample_repo)
    agent_memory_dir = _seed_and_sync(sample_repo)

    task_files = sorted(agent_memory_dir.glob("tasks/*.json"))
    assert task_files
    task_path = task_files[0]
    data = json.loads(task_path.read_text(encoding="utf-8"))
    del data["task"]["task_id"]
    task_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    report = validate_agent_memory_dir(agent_memory_dir)

    assert not report.passed
    assert any("task_id" in err and "missing" in err for err in report.errors)


def test_spec_validate_fails_on_nonexistent_directory() -> None:
    """validate_agent_memory_dir fails cleanly on a nonexistent path."""
    report = validate_agent_memory_dir(Path("/nonexistent/path/.agent-memory"))

    assert not report.passed
    assert any("does not exist" in err for err in report.errors)
