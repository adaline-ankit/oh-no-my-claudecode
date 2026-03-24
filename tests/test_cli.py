from __future__ import annotations

import re
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

    task_start_result = runner.invoke(
        app,
        [
            "task",
            "start",
            "--title",
            "Fix flaky cache invalidation bug",
            "--description",
            "Track the cache invalidation investigation.",
            "--label",
            "bug",
        ],
    )
    assert task_start_result.exit_code == 0
    assert "Task Started" in task_start_result.stdout
    match = re.search(r"task-[0-9a-f]+", task_start_result.stdout)
    assert match is not None
    task_id = match.group(0)

    task_list_result = runner.invoke(app, ["task", "list"])
    assert task_list_result.exit_code == 0
    assert "Tasks" in task_list_result.stdout
    assert task_id in task_list_result.stdout

    task_show_result = runner.invoke(app, ["task", "show", task_id])
    assert task_show_result.exit_code == 0
    assert task_id in task_show_result.stdout

    task_end_result = runner.invoke(
        app,
        [
            "task",
            "end",
            task_id,
            "--status",
            "solved",
            "--summary",
            "Fixed the bug and documented the outcome.",
        ],
    )
    assert task_end_result.exit_code == 0
    assert "Task Ended" in task_end_result.stdout

    brief_result = runner.invoke(app, ["brief", "--task", "fix flaky cache invalidation bug"])
    assert brief_result.exit_code == 0
    assert "Wrote brief:" in brief_result.stdout
    assert list((sample_repo / ".onmc" / "compiled").glob("*-brief.md"))
