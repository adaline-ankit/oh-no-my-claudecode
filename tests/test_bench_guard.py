"""E8: history stripped only with consent; any protected-file drift voids the pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from oh_no_my_claudecode.evals.ab.bench_guard import (
    protected_digests,
    strip_history,
    verify_protected,
)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_x(): assert add(2, 3) == 5")
    return tmp_path


def test_history_exploit_closed_but_only_with_consent(workspace: Path) -> None:
    with pytest.raises(ValueError, match="irreversibly"):
        strip_history(workspace)
    assert strip_history(workspace, this_is_a_disposable_workspace=True) is True
    assert not (workspace / ".git").exists()
    assert strip_history(workspace, this_is_a_disposable_workspace=True) is False


def test_grader_tampering_voids_the_pass(workspace: Path) -> None:
    digests = protected_digests(workspace, ["tests/test_x.py", "tests/test_missing.py"])
    assert digests["tests/test_missing.py"] == "absent"
    assert verify_protected(workspace, digests) == ()  # untouched -> clean

    # Attack 1: weaken the existing test
    (workspace / "tests" / "test_x.py").write_text("def test_x(): assert True")
    # Attack 2: plant a trivial protected file that was absent at setup
    (workspace / "tests" / "test_missing.py").write_text("def test_m(): pass")
    tampered = verify_protected(workspace, digests)
    assert set(tampered) == {"tests/test_x.py", "tests/test_missing.py"}

    # Attack 3: delete the gate test entirely
    (workspace / "tests" / "test_x.py").unlink()
    assert "tests/test_x.py" in verify_protected(workspace, digests)
