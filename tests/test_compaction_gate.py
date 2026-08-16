"""R1 gate: governance decay is caught, named, and repairable — fail-closed."""

from __future__ import annotations

from oh_no_my_claudecode.context_engine.compaction_gate import (
    Constraint,
    ConstraintKind,
    check_compaction,
    repair_compaction,
)

CONSTRAINTS = [
    Constraint("no-outside-writes", "never write outside the repository"),
    Constraint("keep-verifier", r"verifier:\s*pytest", ConstraintKind.REGEX),
    Constraint("irrelevant", "quantum blockchain"),  # never held; must not trip
]

BEFORE = """\
Task: fix the billing webhook.
Policy: never write outside the repository.
verifier: pytest -x -q
...400 lines of exploration, tool output, dead ends...
"""

GOOD_SUMMARY = """\
Fixing billing webhook. Policy: never write outside the repository.
verifier: pytest -x -q. Root cause found in webhook retry handler.
"""

DECAYED_SUMMARY = """\
Fixing billing webhook. Root cause found in webhook retry handler.
"""


def test_faithful_compaction_accepted_with_savings_measured() -> None:
    verdict = check_compaction(BEFORE, GOOD_SUMMARY, CONSTRAINTS)
    assert verdict.accepted
    assert verdict.lost == ()
    assert verdict.checked == 2  # the never-held constraint imposed no obligation
    assert verdict.tokens_freed > 0


def test_governance_decay_is_caught_and_named() -> None:
    verdict = check_compaction(BEFORE, DECAYED_SUMMARY, CONSTRAINTS)
    assert not verdict.accepted  # fail-closed
    assert set(verdict.lost) == {"no-outside-writes", "keep-verifier"}


def test_repair_reinjects_original_lines_verbatim_then_passes() -> None:
    verdict = check_compaction(BEFORE, DECAYED_SUMMARY, CONSTRAINTS)
    repaired = repair_compaction(DECAYED_SUMMARY, BEFORE, verdict, CONSTRAINTS)
    assert "Policy: never write outside the repository." in repaired  # verbatim, no paraphrase
    assert "verifier: pytest -x -q" in repaired
    assert check_compaction(BEFORE, repaired, CONSTRAINTS).accepted


def test_gate_never_mutates_and_is_deterministic() -> None:
    first = check_compaction(BEFORE, DECAYED_SUMMARY, CONSTRAINTS)
    second = check_compaction(BEFORE, DECAYED_SUMMARY, CONSTRAINTS)
    assert first == second
