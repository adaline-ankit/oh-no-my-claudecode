"""Tests for the `onmc why <path>` command and its compiler."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.why.compiler import compile_why, why_report_to_markdown

runner = CliRunner()


def _init_and_ingest(repo: Path) -> OnmcService:
    service = OnmcService(repo)
    service.init_project()
    service.ingest(no_llm=True)
    return service


def test_compile_why_surfaces_churn_and_git_history(sample_repo: Path) -> None:
    service = _init_and_ingest(sample_repo)
    _, config, storage = service._load_context()

    report = compile_why(sample_repo, storage, "README.md")

    assert report.path == "README.md"
    assert report.has_data, "an ingested file with git history should have data"
    # README is the most-churned file in the sample repo fixture.
    assert report.git_history is not None
    assert report.git_history.commit_count >= 1
    markdown = why_report_to_markdown(report)
    assert "Why does `README.md` look this way?" in markdown


def test_compile_why_normalizes_absolute_paths(sample_repo: Path) -> None:
    service = _init_and_ingest(sample_repo)
    _, _, storage = service._load_context()

    absolute = (sample_repo / "README.md").resolve()
    report = compile_why(sample_repo, storage, str(absolute))

    assert report.path == "README.md", "absolute paths must normalize to repo-relative"


def test_compile_why_unknown_path_is_honest(sample_repo: Path) -> None:
    service = _init_and_ingest(sample_repo)
    _, _, storage = service._load_context()

    report = compile_why(sample_repo, storage, "does/not/exist.py")

    assert not report.has_data
    markdown = why_report_to_markdown(report)
    assert "Nothing is known about this file yet" in markdown


def test_why_service_writes_artifact_deterministically(sample_repo: Path) -> None:
    service = _init_and_ingest(sample_repo)

    _, report = service.why("README.md", no_llm=True)

    assert report.output_path, "why must write a markdown artifact"
    artifact = Path(report.output_path)
    assert artifact.is_file()
    assert "why-README.md.md" in artifact.name
    assert report.llm_narrative == "", "no_llm must keep the report deterministic"
    assert "Why does `README.md` look this way?" in artifact.read_text(encoding="utf-8")


def test_why_cli_command(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    _init_and_ingest(sample_repo)

    result = runner.invoke(app, ["why", "README.md", "--no-llm"])

    assert result.exit_code == 0, result.output
    assert "onmc why" in result.output
    assert "Wrote why report" in result.output


def test_why_cli_unknown_path_still_succeeds(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)  # type: ignore[attr-defined]
    _init_and_ingest(sample_repo)

    result = runner.invoke(app, ["why", "totally/made/up.py", "--no-llm"])

    assert result.exit_code == 0, result.output
    assert "Nothing is known about this file yet" in result.output
