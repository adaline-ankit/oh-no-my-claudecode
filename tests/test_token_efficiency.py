from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import onmc
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService


def test_brief_supports_caveman_token_budget(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    artifact = service.compile_brief("fix flaky cache invalidation bug")[1]
    markdown = artifact.to_markdown(style="caveman")

    assert "# ONMC Brief Caveman" in markdown
    assert "## Files" in markdown
    assert "Output terse" in markdown
    assert len(markdown) < len(artifact.to_markdown())


def test_brief_cli_stdout_can_trim_for_paste_budget(
    sample_repo: Path, monkeypatch: object
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    result = runner.invoke(
        app,
        [
            "brief",
            "--task",
            "fix flaky cache invalidation bug",
            "--style",
            "caveman",
            "--max-tokens",
            "35",
            "--stdout",
        ],
    )

    assert result.exit_code == 0
    assert "# ONMC Brief Caveman" in result.stdout
    assert "[trimmed to 35 tokens]" in result.stdout
    assert "Task Brief" not in result.stdout


def test_codegraph_cli_returns_compact_repo_map(
    sample_repo: Path, monkeypatch: object
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    result = runner.invoke(app, ["codegraph", "--max-files", "3"])

    assert result.exit_code == 0
    assert "# ONMC Codegraph" in result.stdout
    assert "## Hot Files" in result.stdout
    assert "src/cache.py" in result.stdout
    assert "onmc brief --style caveman" in result.stdout


def test_public_api_exposes_compact_brief_and_codegraph(
    sample_repo: Path, monkeypatch: object
) -> None:
    monkeypatch.chdir(sample_repo)
    repo = onmc.init(sample_repo)
    repo.ingest()

    brief = repo.brief("fix flaky cache invalidation bug", max_tokens=50, style="compact")
    graph = repo.codegraph(max_files=2)

    assert "ONMC Compact Brief" in brief.markdown
    assert brief.truncated is True
    assert "# ONMC Codegraph" in graph
