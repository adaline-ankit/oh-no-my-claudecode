"""Tests for the onmc check module and CLI command."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode import init
from oh_no_my_claudecode.check.engine import CheckResult, CheckSeverity, run_check
from oh_no_my_claudecode.check.git_hook import _ONMC_MARKER, install_pre_commit_hook
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.models.memory_artifact import MemoryArtifactRecord, MemoryArtifactType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_invariant(
    storage: SQLiteStorage,
    title: str,
    summary: str,
    source_ref: str,
) -> MemoryEntry:
    """Insert an INVARIANT memory and return it."""
    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(
            MemoryKind.INVARIANT.value,
            title,
            summary,
            source_ref,
            prefix="test",
        ),
        kind=MemoryKind.INVARIANT,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.MANUAL,
        source_ref=source_ref,
        tags=[MemoryKind.INVARIANT.value],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return entry


def _seed_failed_approach(
    storage: SQLiteStorage,
    title: str,
    summary: str,
    source_ref: str,
) -> MemoryEntry:
    """Insert a FAILED_APPROACH memory and return it."""
    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(
            MemoryKind.FAILED_APPROACH.value,
            title,
            summary,
            source_ref,
            prefix="test",
        ),
        kind=MemoryKind.FAILED_APPROACH,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.MANUAL,
        source_ref=source_ref,
        tags=[MemoryKind.FAILED_APPROACH.value],
        confidence=0.85,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return entry


def _seed_did_not_work_artifact(
    storage: SQLiteStorage,
    memory_id: str,
    task_id: str,
    title: str,
    evidence: str,
    related_files: list[str] | None = None,
) -> MemoryArtifactRecord:
    """Insert a DID_NOT_WORK artifact and return it."""
    artifact = MemoryArtifactRecord(
        memory_id=memory_id,
        task_id=task_id,
        type=MemoryArtifactType.DID_NOT_WORK,
        title=title,
        summary=f"Tried: {title}",
        why_it_matters="Avoid repeating this approach.",
        apply_when=None,
        avoid_when=None,
        evidence=evidence,
        related_files=related_files or [],
        related_modules=[],
        confidence=0.8,
        created_at=utc_now(),
    )
    storage.create_memory_artifact(artifact)
    return artifact


# ---------------------------------------------------------------------------
# Unit tests: run_check
# ---------------------------------------------------------------------------


def test_run_check_flags_file_with_invariant(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed file that touches an INVARIANT memory yields a warn finding."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()  # noqa: SLF001

    # Seed an INVARIANT that mentions src/cache.py.
    _seed_invariant(
        storage,
        title="Cache boundary must not be bypassed",
        summary="Do not write directly to cache keys from src/cache.py worker code.",
        source_ref="src/cache.py",
    )

    result = run_check(sample_repo, storage, ["src/cache.py"])

    assert isinstance(result, CheckResult)
    assert result.has_warnings
    assert result.warn_count >= 1
    findings = result.findings_for("src/cache.py")
    assert any(f.severity == CheckSeverity.WARN for f in findings)
    warn_findings = [f for f in findings if f.severity == CheckSeverity.WARN]
    assert any("Cache boundary" in f.title for f in warn_findings)


def test_run_check_clean_for_unrelated_file(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file with no warn-level memory coverage produces no warn findings."""
    monkeypatch.chdir(sample_repo)
    # Use a bare storage with no ingest to avoid cross-contamination from
    # doc memories that happen to mention README.md.
    repo = init(sample_repo)

    _, _, storage = repo._service._load_context()  # noqa: SLF001

    # Seed an INVARIANT referencing a different file.
    _seed_invariant(
        storage,
        title="Worker isolation invariant",
        summary="Workers must not share in-memory state via worker.py globals.",
        source_ref="src/worker.py",
    )

    # Check an unrelated file — should have no WARN findings.
    result = run_check(sample_repo, storage, ["README.md"])

    assert not result.has_warnings
    warn_findings = [
        f for f in result.findings_for("README.md") if f.severity == CheckSeverity.WARN
    ]
    assert warn_findings == []


def test_run_check_flags_failed_approach(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FAILED_APPROACH memory on a file is surfaced as a warn finding."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()  # noqa: SLF001

    _seed_failed_approach(
        storage,
        title="Direct Redis writes from cache.py",
        summary="Bypassing the cache module via src/cache.py broke invalidation.",
        source_ref="src/cache.py",
    )

    result = run_check(sample_repo, storage, ["src/cache.py"])

    assert result.has_warnings
    findings = [f for f in result.findings if f.kind == MemoryKind.FAILED_APPROACH.value]
    assert len(findings) >= 1


def test_run_check_enriches_with_dead_end_artifact_evidence(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DID_NOT_WORK artifact evidence appears in the finding summary."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()
    task = repo._service.start_task(
        title="Cache work",
        description="Fixing cache invalidation.",
        labels=[],
    )

    _, _, storage = repo._service._load_context()  # noqa: SLF001

    mem = _seed_failed_approach(
        storage,
        title="Monkey-patch cache in tests",
        summary="Tried monkey-patching src/cache.py for test isolation.",
        source_ref="src/cache.py",
    )
    _seed_did_not_work_artifact(
        storage,
        memory_id=mem.id,
        task_id=task.task_id,
        title="Monkey-patch cache",
        evidence="Tests fail in parallel due to shared state leaking from patched cache module.",
        related_files=["src/cache.py"],
    )

    result = run_check(sample_repo, storage, ["src/cache.py"])

    findings = [f for f in result.findings if f.memory_id == mem.id]
    assert findings
    # Evidence should be woven into summary.
    assert "parallel" in findings[0].summary.lower() or "Evidence" in findings[0].summary


def test_run_check_empty_files_list_returns_empty_result(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty file list produces an empty CheckResult without error."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()  # noqa: SLF001

    result = run_check(sample_repo, storage, [])

    assert result.findings == []
    assert not result.has_warnings


def test_run_check_no_duplicate_findings_per_memory(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each (file, memory_id) pair appears at most once in findings."""
    monkeypatch.chdir(sample_repo)
    repo = init(sample_repo)
    repo.ingest()

    _, _, storage = repo._service._load_context()  # noqa: SLF001

    _seed_invariant(
        storage,
        title="Cache invariant",
        summary="Don't bypass src/cache.py in cache.py",
        source_ref="src/cache.py",
    )

    result = run_check(sample_repo, storage, ["src/cache.py"])

    memory_ids = [f.memory_id for f in result.findings_for("src/cache.py")]
    assert len(memory_ids) == len(set(memory_ids)), "Duplicate memory_id in findings"


# ---------------------------------------------------------------------------
# CLI tests: onmc check --strict exit codes
# ---------------------------------------------------------------------------


def test_cli_check_strict_exits_nonzero_with_findings(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc check --strict`` exits 1 when warn-level findings exist."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    # Seed an invariant on src/cache.py via the service.
    svc = init(sample_repo)
    _, _, storage = svc._service._load_context()  # noqa: SLF001
    _seed_invariant(
        storage,
        title="Cache boundary invariant",
        summary="Do not bypass the cache module from src/cache.py.",
        source_ref="src/cache.py",
    )

    result = runner.invoke(app, ["check", "--file", "src/cache.py", "--strict"])

    assert result.exit_code == 1, (
        f"Expected exit 1, got {result.exit_code}. Output: {result.stdout}"
    )


def test_cli_check_strict_exits_zero_without_findings(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc check --strict`` exits 0 when there are no findings."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    result = runner.invoke(app, ["check", "--file", "README.md", "--strict"])

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. Output: {result.stdout}"
    )


def test_cli_check_default_exits_zero_even_with_findings(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc check`` (no --strict) exits 0 even when warn-level findings exist."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()
    runner.invoke(app, ["init"])
    runner.invoke(app, ["ingest"])

    svc = init(sample_repo)
    _, _, storage = svc._service._load_context()  # noqa: SLF001
    _seed_invariant(
        storage,
        title="Cache boundary invariant",
        summary="Do not bypass the cache module from src/cache.py.",
        source_ref="src/cache.py",
    )

    result = runner.invoke(app, ["check", "--file", "src/cache.py"])

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. Output: {result.stdout}"
    )
    # Should show the finding in output.
    stdout = result.stdout
    assert "WARNING" in stdout or "warning" in stdout.lower() or "Cache" in stdout


# ---------------------------------------------------------------------------
# Git hook installer tests
# ---------------------------------------------------------------------------


def _make_git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo in tmp_path and return its root."""
    repo = tmp_path / "hook-test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def test_install_hook_creates_new_file(tmp_path: Path) -> None:
    """``install_pre_commit_hook`` creates a new hook file when none exists."""
    repo = _make_git_repo(tmp_path)

    hook_path, was_created = install_pre_commit_hook(repo)

    assert hook_path == repo / ".git" / "hooks" / "pre-commit"
    assert hook_path.exists()
    assert was_created is True
    content = hook_path.read_text(encoding="utf-8")
    assert "#!/bin/sh" in content
    assert "onmc check --staged" in content
    assert _ONMC_MARKER in content
    # Executable
    import stat

    mode = hook_path.stat().st_mode
    assert bool(mode & stat.S_IXUSR), "Hook file is not executable"


def test_install_hook_is_idempotent(tmp_path: Path) -> None:
    """Installing twice produces exactly one onmc block in the hook."""
    repo = _make_git_repo(tmp_path)

    install_pre_commit_hook(repo)
    hook_path, was_created_second = install_pre_commit_hook(repo)

    content = hook_path.read_text(encoding="utf-8")
    # Exactly one occurrence of the marker.
    assert content.count(_ONMC_MARKER) == 1, "Duplicate onmc block after second install"
    # Second install is a no-op.
    assert was_created_second is False


def test_install_hook_preserves_existing_hook(tmp_path: Path) -> None:
    """An existing pre-commit hook is preserved and onmc block is appended."""
    repo = _make_git_repo(tmp_path)
    hook_path = repo / ".git" / "hooks" / "pre-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    pre_existing_content = "#!/bin/sh\n# my existing hook\necho 'running tests'\n"
    hook_path.write_text(pre_existing_content, encoding="utf-8")
    hook_path.chmod(0o755)

    returned_path, was_created = install_pre_commit_hook(repo)

    assert returned_path == hook_path
    assert was_created is False  # not created — appended

    content = hook_path.read_text(encoding="utf-8")
    # Original content must be present.
    assert "my existing hook" in content
    assert "echo 'running tests'" in content
    # onmc block must also be present.
    assert _ONMC_MARKER in content
    assert "onmc check --staged" in content


def test_install_hook_append_idempotent_with_existing(tmp_path: Path) -> None:
    """Appending to a pre-existing hook is also idempotent."""
    repo = _make_git_repo(tmp_path)
    hook_path = repo / ".git" / "hooks" / "pre-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    pre_existing_content = "#!/bin/sh\necho 'my hook'\n"
    hook_path.write_text(pre_existing_content, encoding="utf-8")
    hook_path.chmod(0o755)

    install_pre_commit_hook(repo)
    install_pre_commit_hook(repo)

    content = hook_path.read_text(encoding="utf-8")
    # Only one onmc block even after two calls with pre-existing hook.
    assert content.count(_ONMC_MARKER) == 1


# ---------------------------------------------------------------------------
# CLI: --install-hook
# ---------------------------------------------------------------------------


def test_cli_check_install_hook_creates_file(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc check --install-hook`` writes a .git/hooks/pre-commit file."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()

    result = runner.invoke(app, ["check", "--install-hook"])

    assert result.exit_code == 0, result.stdout
    hook_path = sample_repo / ".git" / "hooks" / "pre-commit"
    assert hook_path.exists()
    content = hook_path.read_text(encoding="utf-8")
    assert "onmc check --staged" in content


def test_cli_check_install_hook_idempotent_via_cli(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``onmc check --install-hook`` run twice is idempotent."""
    monkeypatch.chdir(sample_repo)
    runner = CliRunner()

    runner.invoke(app, ["check", "--install-hook"])
    result = runner.invoke(app, ["check", "--install-hook"])

    assert result.exit_code == 0, result.stdout
    hook_path = sample_repo / ".git" / "hooks" / "pre-commit"
    content = hook_path.read_text(encoding="utf-8")
    assert content.count(_ONMC_MARKER) == 1
