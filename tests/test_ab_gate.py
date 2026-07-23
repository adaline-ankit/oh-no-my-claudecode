"""The live A/B path must refuse to run without an explicit dangerous opt-in."""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.evals.ab.private_tasks import PRIVATE_KNOWLEDGE_TASKS
from oh_no_my_claudecode.evals.ab.runner import run_suite


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
