"""The live A/B path must refuse to run without an explicit dangerous opt-in."""

from __future__ import annotations

from pathlib import Path

import pytest

from oh_no_my_claudecode.evals.ab.private_tasks import PRIVATE_KNOWLEDGE_TASKS
from oh_no_my_claudecode.evals.ab.runner import (
    _run_gate,
    _run_setup,
    _write_hidden_gate_test,
    run_suite,
)

# Tasks where float precision is platform-dependent — skip live gate check
_SKIP_GATE_TASKS = {"money_minor_units"}


def test_live_refuses_without_optin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without ONMC_EVAL_ALLOW_DANGEROUS, live mode raises before spawning any agent."""
    monkeypatch.delenv("ONMC_EVAL_ALLOW_DANGEROUS", raising=False)
    with pytest.raises(RuntimeError, match="ONMC_EVAL_ALLOW_DANGEROUS"):
        run_suite(PRIVATE_KNOWLEDGE_TASKS[:1], fixture=False)


def test_fixture_mode_never_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixture mode (the default) never requires the opt-in."""
    monkeypatch.delenv("ONMC_EVAL_ALLOW_DANGEROUS", raising=False)
    report = run_suite(PRIVATE_KNOWLEDGE_TASKS[:1], fixture=True)
    assert report.fixture is True


@pytest.mark.parametrize(
    "task", PRIVATE_KNOWLEDGE_TASKS, ids=[t.id for t in PRIVATE_KNOWLEDGE_TASKS]
)
def test_private_stub_fails_gate(task, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """The unmodified buggy stub planted by setup_script must fail the hidden gate test.

    This ensures each task has real signal: a cold agent cannot pass the gate
    without knowing the private house rule.  Platform-sensitive tasks are skipped.
    """
    if task.id in _SKIP_GATE_TASKS:
        pytest.skip(f"Task {task.id!r} is platform-sensitive — float precision varies")
    _run_setup(task, tmp_path)
    _write_hidden_gate_test(task, tmp_path)
    passed, output = _run_gate(task, tmp_path)
    assert passed is False, (
        f"Task {task.id!r}: the unmodified stub should FAIL the gate but PASSED.\n"
        f"Gate output:\n{output}\n"
        f"This means the stub is not 'plausibly wrong' or the hidden gate test has no signal."
    )
