from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app


def test_cli_happy_path(sample_repo: Path, monkeypatch: object) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)

    init_result = runner.invoke(app, ["init"])
    assert init_result.exit_code == 0
    assert (sample_repo / ".onmc" / "config.yaml").exists()

    ingest_result = runner.invoke(app, ["ingest"])
    assert ingest_result.exit_code == 0
    assert "Ingest Summary" in ingest_result.stdout

    status_result = runner.invoke(app, ["status"])
    assert status_result.exit_code == 0
    assert "repo_root" in status_result.stdout

    memory_result = runner.invoke(app, ["memory", "list"])
    assert memory_result.exit_code == 0
    assert "Stored Memory" in memory_result.stdout

    brief_result = runner.invoke(app, ["brief", "--task", "fix flaky cache invalidation bug"])
    assert brief_result.exit_code == 0
    assert "Wrote brief:" in brief_result.stdout
    assert list((sample_repo / ".onmc" / "compiled").glob("*-brief.md"))
