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

    llm_status_result = runner.invoke(app, ["llm", "status"])
    assert llm_status_result.exit_code == 0
    assert "LLM Status" in llm_status_result.stdout
    assert "unconfigured" in llm_status_result.stdout

    llm_configure_result = runner.invoke(
        app,
        [
            "llm",
            "configure",
            "--provider",
            "anthropic",
            "--model",
            "claude-sonnet-4-5",
        ],
    )
    assert llm_configure_result.exit_code == 0
    assert "LLM Configuration Saved" in llm_configure_result.stdout

    llm_status_after_configure_result = runner.invoke(app, ["llm", "status"])
    assert llm_status_after_configure_result.exit_code == 0
    assert "anthropic" in llm_status_after_configure_result.stdout
    assert "ANTHROPIC_API_KEY" in llm_status_after_configure_result.stdout

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
    task_line = next(
        line for line in task_list_result.stdout.splitlines() if task_id in line
    )
    assert task_line.split()[0] == task_id

    task_show_result = runner.invoke(app, ["task", "show", task_id])
    assert task_show_result.exit_code == 0
    assert task_id in task_show_result.stdout

    attempt_add_result = runner.invoke(
        app,
        [
            "attempt",
            "add",
            task_id,
            "--summary",
            "Try a targeted cache fix and rerun the cache test.",
            "--kind",
            "fix_attempt",
            "--status",
            "tried",
            "--evidence-for",
            "The cache module has repeated churn.",
            "--file",
            "src/cache.py",
        ],
    )
    assert attempt_add_result.exit_code == 0
    assert "Attempt Added" in attempt_add_result.stdout
    attempt_match = re.search(r"attempt-[0-9a-f]+", attempt_add_result.stdout)
    assert attempt_match is not None
    attempt_id = attempt_match.group(0)

    attempt_list_result = runner.invoke(app, ["attempt", "list", task_id])
    assert attempt_list_result.exit_code == 0
    assert attempt_id in attempt_list_result.stdout

    attempt_show_result = runner.invoke(app, ["attempt", "show", attempt_id])
    assert attempt_show_result.exit_code == 0
    assert attempt_id in attempt_show_result.stdout

    attempt_update_result = runner.invoke(
        app,
        [
            "attempt",
            "update",
            attempt_id,
            "--status",
            "rejected",
            "--evidence-against",
            "The targeted change did not address the failing path.",
        ],
    )
    assert attempt_update_result.exit_code == 0
    assert "Attempt Updated" in attempt_update_result.stdout

    task_show_after_attempt_result = runner.invoke(app, ["task", "show", task_id])
    assert task_show_after_attempt_result.exit_code == 0
    assert attempt_id in task_show_after_attempt_result.stdout

    memory_add_result = runner.invoke(
        app,
        [
            "memory",
            "add",
            task_id,
            "--type",
            "did_not_work",
            "--title",
            "Cache-only fix missed the worker path",
            "--summary",
            "Tried narrowing the change to src/cache.py only.",
            "--why-it-matters",
            "Future agents should not repeat a cache-only patch for this failure mode.",
            "--avoid-when",
            "The failing path crosses the worker refresh flow.",
            "--evidence",
            "The worker test still failed after the narrow change.",
            "--file",
            "src/cache.py",
            "--module",
            "worker",
        ],
    )
    assert memory_add_result.exit_code == 0
    assert "Memory Artifact Added" in memory_add_result.stdout
    memory_match = re.search(r"artifact-[0-9a-f]+", memory_add_result.stdout)
    assert memory_match is not None
    memory_id = memory_match.group(0)

    memory_type_list_result = runner.invoke(app, ["memory", "list", "--type", "did_not_work"])
    assert memory_type_list_result.exit_code == 0
    assert "Task-Derived Memory Artifacts" in memory_type_list_result.stdout
    assert memory_id in memory_type_list_result.stdout

    memory_show_result = runner.invoke(app, ["memory", "show", memory_id])
    assert memory_show_result.exit_code == 0
    assert f"Task ID: {task_id}" in memory_show_result.stdout
    assert "Provenance: task-derived" in memory_show_result.stdout

    task_show_after_memory_result = runner.invoke(app, ["task", "show", task_id])
    assert task_show_after_memory_result.exit_code == 0
    assert memory_id in task_show_after_memory_result.stdout

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
