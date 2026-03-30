from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService


def test_ingest_files_updates_only_targeted_doc_memories(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    architecture_ids_before = {
        memory.id
        for memory in service.list_memories()
        if memory.source_ref == "docs/architecture.md"
    }
    readme_before = [
        memory.summary for memory in service.list_memories() if memory.source_ref == "README.md"
    ]
    assert architecture_ids_before
    assert readme_before

    (sample_repo / "README.md").write_text(
        """# Sample Repo

This service handles cache invalidation for worker jobs.

## Development

Always run tests before merging. Prefer cache-boundary changes before worker-specific patches.
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["ingest", "--files", "README.md"])

    assert result.exit_code == 0
    updated_service = OnmcService(sample_repo)
    architecture_ids_after = {
        memory.id
        for memory in updated_service.list_memories()
        if memory.source_ref == "docs/architecture.md"
    }
    readme_after = [
        memory.summary
        for memory in updated_service.list_memories()
        if memory.source_ref == "README.md"
    ]
    assert architecture_ids_after == architecture_ids_before
    assert any("cache-boundary" in summary for summary in readme_after)


def test_ingest_files_with_missing_path_warns_and_continues(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    result = runner.invoke(app, ["ingest", "--files", "missing.md", "README.md"])

    assert result.exit_code == 0
    assert "Skipped missing file: missing.md" in result.output


def test_ingest_install_hook_writes_expected_script(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    result = runner.invoke(app, ["ingest", "--install-hook"])

    assert result.exit_code == 0
    hook_path = sample_repo / ".git" / "hooks" / "post-commit"
    content = hook_path.read_text(encoding="utf-8")
    assert "# ONMC incremental ingest hook" in content
    assert "xargs -0 onmc ingest --files" in content
    assert "onmc sync --commit 2>/dev/null || true" in content


def test_ingest_install_hook_appends_existing_post_commit(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    hook_path = sample_repo / ".git" / "hooks" / "post-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)
    hook_path.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")

    result = runner.invoke(app, ["ingest", "--install-hook"])

    assert result.exit_code == 0
    content = hook_path.read_text(encoding="utf-8")
    assert "echo existing" in content
    assert "# ONMC incremental ingest hook" in content
