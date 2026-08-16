"""Repo-bench compiler: mines a fix commit and replants a real, gated bug."""

from __future__ import annotations

import subprocess
from pathlib import Path

from oh_no_my_claudecode.evals.ab.repo_bench import compile_repo_bench, mine_fix_commits


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_history(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "test_calc.py").write_text(
        "from calc import add\n\ndef test_exists():\n    assert add\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "feat: add calc")
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fix: add() subtracted instead of adding")


def test_mines_and_compiles_a_replayable_bug(tmp_path: Path) -> None:
    _make_history(tmp_path)
    mined = mine_fix_commits(tmp_path)
    assert len(mined) == 1
    assert mined[0].source_paths == ("calc.py",)
    assert mined[0].test_paths == ("test_calc.py",)

    tasks = compile_repo_bench(tmp_path)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.gate_command == "python -m pytest test_calc.py -x -q"
    assert task.protected_paths == ("test_calc.py",)
    assert "test_calc.py" not in task.setup_patch  # reverts SOURCE only

    # Round-trip: patch re-plants the bug (gate fails), revert restores (gate passes).
    apply = subprocess.run(
        ["git", "-C", str(tmp_path), "apply", "-"],
        input=task.setup_patch,
        text=True,
        capture_output=True,
    )
    assert apply.returncode == 0, apply.stderr
    assert "return a - b" in (tmp_path / "calc.py").read_text()  # bug is back
    gate = subprocess.run(
        ["python", "-m", "pytest", "test_calc.py", "-x", "-q"],
        cwd=tmp_path,
        capture_output=True,
    )
    assert gate.returncode != 0  # fails with the bug planted
    _git(tmp_path, "checkout", "--", "calc.py")
    gate = subprocess.run(
        ["python", "-m", "pytest", "test_calc.py", "-x", "-q"],
        cwd=tmp_path,
        capture_output=True,
    )
    assert gate.returncode == 0  # passes once fixed
