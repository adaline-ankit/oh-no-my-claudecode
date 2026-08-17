"""E7-harbor: emit repo-bench tasks in Harbor / Terminal-Bench 2 task format.

Harbor is the execution engine behind Terminal-Bench 2.0 — the independently
governed eval every major CLI agent publishes against. Emitting its task
layout means ONMC's private, repo-mined benchmarks run under the same
orchestrator the public ones do: one task directory per task, with

    <task-id>/
      task.toml              (metadata + verifier + agent sections)
      instruction.md         (what the agent is told)
      environment/Dockerfile (plants the bug via the task's setup script)
      environment/setup_task.py
      tests/test.sh          (the gate command — exit code is the verdict)

The verifier stays ours: the gate command is the repo's own test suite, so
Harbor orchestrates while ONMC's execution-based verdict still decides.
"""

from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.evals.ab.models import ABTask

_DOCKERFILE = """\
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest
WORKDIR /app
COPY setup_task.py /tmp/setup_task.py
RUN cd /app && python /tmp/setup_task.py
"""

_TASK_TOML = """\
[metadata]
id = "{task_id}"
origin = "onmc-repo-bench"
difficulty = "unknown"

[verifier]
timeout_sec = 300.0

[agent]
timeout_sec = 900.0
"""

_TEST_SH = """\
#!/bin/bash
# ONMC gate: the repo's own tests are the verdict. Bytecode is never trusted (H11).
cd /app
PYTHONDONTWRITEBYTECODE=1 {gate_command}
"""


def export_harbor_task(task: ABTask, out_root: Path) -> Path:
    """Write one Harbor-format task directory; returns its path."""
    root = Path(out_root) / task.id
    (root / "environment").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)

    (root / "task.toml").write_text(_TASK_TOML.format(task_id=task.id))
    (root / "instruction.md").write_text(task.description.strip() + "\n")
    (root / "environment" / "Dockerfile").write_text(_DOCKERFILE)
    (root / "environment" / "setup_task.py").write_text(task.setup_script)
    test_sh = root / "tests" / "test.sh"
    test_sh.write_text(_TEST_SH.format(gate_command=task.gate_command))
    test_sh.chmod(0o755)
    return root


def export_harbor_tasks(tasks: list[ABTask], out_root: Path) -> list[Path]:
    """Export a whole repo-bench corpus as a Harbor task set."""
    return [export_harbor_task(task, out_root) for task in tasks]


__all__ = ["export_harbor_task", "export_harbor_tasks"]
