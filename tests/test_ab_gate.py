"""Anti-leak and precheck tests for the private-knowledge A/B eval suite.

Anti-leak tests
---------------
For EVERY private-knowledge task, the rule_token (the specific string that
encodes the correct internal rule) must NOT appear in:
  - task.description  (what the agent reads as the task prompt)
  - task.setup_script (what creates the initial wrong-value file)

If the rule_token appeared in either field it would tell the agent the correct
answer, defeating the purpose of testing private knowledge.

The rule_token MUST appear in:
  - task.onmc_hint    (the ONMC-injected context)
  - task.grounding_doc (the documentation that grounds the rule)

Precheck tests
--------------
For EVERY private-knowledge task, the unmodified stub produced by
setup_script (before any agent interaction) MUST FAIL the gate_command.

This confirms:
  1. The setup actually plants the wrong value (not the correct one).
  2. The gate is meaningful — it would reject a no-op agent.

If the precheck passed it would mean the setup already has the correct value
and the task cannot distinguish cc_alone from cc_onmc.

Coverage
--------
- Anti-leak: 30 tasks × (description clean + setup_script clean) = 60 checks
- Anti-present: 30 tasks × (onmc_hint has token + grounding_doc has token) = 60 checks
- Precheck: 30 tasks × gate fails on unmodified stub = 30 checks
- Structural: all 30 tasks have non-empty rule_token and grounding_doc
- ID uniqueness: 30 task IDs are distinct
- Fixture completeness: fixtures.py covers all 30 tasks under both conditions
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oh_no_my_claudecode.evals.ab.fixtures import load_fixture_results
from oh_no_my_claudecode.evals.ab.private_tasks import (
    PRIVATE_KNOWLEDGE_TASKS,
    PrivateKnowledgeTask,
)
from oh_no_my_claudecode.evals.ab.runner import _run_gate, _run_setup

# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------


def test_private_tasks_count_at_least_30() -> None:
    assert len(PRIVATE_KNOWLEDGE_TASKS) >= 30, (
        f"Expected >= 30 private knowledge tasks but found {len(PRIVATE_KNOWLEDGE_TASKS)}"
    )


def test_private_tasks_are_private_knowledge_task_instances() -> None:
    for task in PRIVATE_KNOWLEDGE_TASKS:
        assert isinstance(task, PrivateKnowledgeTask), (
            f"Task {task.id!r} is not a PrivateKnowledgeTask"
        )


def test_private_task_ids_unique() -> None:
    ids = [t.id for t in PRIVATE_KNOWLEDGE_TASKS]
    assert len(ids) == len(set(ids)), (
        f"Duplicate task IDs in PRIVATE_KNOWLEDGE_TASKS: "
        f"{[x for x in ids if ids.count(x) > 1]}"
    )


def test_private_tasks_all_required_fields_non_empty() -> None:
    for task in PRIVATE_KNOWLEDGE_TASKS:
        assert task.id, "Task missing id"
        assert task.description, f"Task {task.id!r} missing description"
        assert task.setup_script, f"Task {task.id!r} missing setup_script"
        assert task.gate_command, f"Task {task.id!r} missing gate_command"
        assert task.onmc_hint, f"Task {task.id!r} missing onmc_hint"
        assert task.rule_token, f"Task {task.id!r} missing rule_token"
        assert task.grounding_doc, f"Task {task.id!r} missing grounding_doc"


# ---------------------------------------------------------------------------
# Anti-leak tests: rule_token must NOT appear in agent-visible content
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task", PRIVATE_KNOWLEDGE_TASKS, ids=lambda t: t.id)
def test_antileak_rule_token_not_in_description(task: PrivateKnowledgeTask) -> None:
    """The rule_token must not appear in the agent's task description."""
    assert task.rule_token not in task.description, (
        f"Task {task.id!r}: rule_token {task.rule_token!r} LEAKS into description!\n"
        f"Description: {task.description!r}"
    )


@pytest.mark.parametrize("task", PRIVATE_KNOWLEDGE_TASKS, ids=lambda t: t.id)
def test_antileak_rule_token_not_in_setup_script(task: PrivateKnowledgeTask) -> None:
    """The rule_token must not appear in the setup_script (agent-visible initial state)."""
    assert task.rule_token not in task.setup_script, (
        f"Task {task.id!r}: rule_token {task.rule_token!r} LEAKS into setup_script!\n"
        f"setup_script excerpt: {task.setup_script[:300]!r}"
    )


# ---------------------------------------------------------------------------
# Anti-present tests: rule_token MUST appear in ONMC-only content
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task", PRIVATE_KNOWLEDGE_TASKS, ids=lambda t: t.id)
def test_rule_token_present_in_onmc_hint(task: PrivateKnowledgeTask) -> None:
    """The rule_token must appear in onmc_hint so cc_onmc gets the correct value."""
    assert task.rule_token in task.onmc_hint, (
        f"Task {task.id!r}: rule_token {task.rule_token!r} not found in onmc_hint.\n"
        f"The hint must explicitly name the correct rule token."
    )


@pytest.mark.parametrize("task", PRIVATE_KNOWLEDGE_TASKS, ids=lambda t: t.id)
def test_rule_token_present_in_grounding_doc(task: PrivateKnowledgeTask) -> None:
    """The rule_token must appear in grounding_doc (the source-of-truth document)."""
    assert task.rule_token in task.grounding_doc, (
        f"Task {task.id!r}: rule_token {task.rule_token!r} not found in grounding_doc.\n"
        f"The grounding doc must state the rule that encodes the token."
    )


# ---------------------------------------------------------------------------
# Precheck tests: gate must FAIL on the unmodified stub
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task", PRIVATE_KNOWLEDGE_TASKS, ids=lambda t: t.id)
def test_precheck_gate_fails_on_unmodified_stub(
    task: PrivateKnowledgeTask,
    tmp_path: Path,
) -> None:
    """Gate must FAIL when the setup stub is present but no agent has run.

    This confirms setup_script plants the wrong value and the gate is meaningful.
    If the gate passed here it would mean the stub already has the correct value,
    making the task unable to distinguish cc_alone from cc_onmc.
    """
    # Plant the wrong-value stub
    _run_setup(task, tmp_path)

    # Gate must fail because rule_token is not in the file yet
    passed, output = _run_gate(task, tmp_path)
    assert passed is False, (
        f"Task {task.id!r}: gate PASSED on the unmodified stub!\n"
        f"This means the setup already plants rule_token {task.rule_token!r}.\n"
        f"Gate output: {output!r}"
    )


# ---------------------------------------------------------------------------
# Fixture completeness: all 30 tasks have cc_alone + cc_onmc fixture entries
# ---------------------------------------------------------------------------


def test_fixture_covers_all_private_tasks_cc_alone() -> None:
    fixture_map = load_fixture_results()
    missing = [
        task.id
        for task in PRIVATE_KNOWLEDGE_TASKS
        if (task.id, "cc_alone") not in fixture_map
    ]
    assert not missing, (
        f"Missing cc_alone fixture entries for: {missing}.  "
        f"Add them to fixtures.py _RAW list."
    )


def test_fixture_covers_all_private_tasks_cc_onmc() -> None:
    fixture_map = load_fixture_results()
    missing = [
        task.id
        for task in PRIVATE_KNOWLEDGE_TASKS
        if (task.id, "cc_onmc") not in fixture_map
    ]
    assert not missing, (
        f"Missing cc_onmc fixture entries for: {missing}.  "
        f"Add them to fixtures.py _RAW list."
    )


def test_fixture_has_at_least_one_onmc_win_in_private_tasks() -> None:
    """At least one private task must show ONMC wins — otherwise the suite is trivial."""
    fixture_map = load_fixture_results()
    # Real ONMC wins: cc_alone=fail, cc_onmc=pass
    real_wins = [
        task.id
        for task in PRIVATE_KNOWLEDGE_TASKS
        if (
            (task.id, "cc_alone") in fixture_map
            and (task.id, "cc_onmc") in fixture_map
            and not fixture_map[(task.id, "cc_alone")].passed
            and fixture_map[(task.id, "cc_onmc")].passed
        )
    ]
    assert real_wins, (
        "No ONMC wins (cc_alone=fail, cc_onmc=pass) found in private task fixtures.  "
        "The suite should demonstrate ONMC value on un-inferrable rules."
    )


def test_fixture_has_at_least_one_both_pass_in_private_tasks() -> None:
    """At least one private task must show both pass — proves not all tasks are rigged."""
    fixture_map = load_fixture_results()
    both_pass = [
        task.id
        for task in PRIVATE_KNOWLEDGE_TASKS
        if (
            (task.id, "cc_alone") in fixture_map
            and (task.id, "cc_onmc") in fixture_map
            and fixture_map[(task.id, "cc_alone")].passed
            and fixture_map[(task.id, "cc_onmc")].passed
        )
    ]
    assert both_pass, (
        "No 'both pass' tasks found in private task fixtures.  "
        "At least one task should be easy enough for cc_alone to pass "
        "(proves the baseline is not universally rigged)."
    )


def test_fixture_all_private_task_results_are_fixture_mode() -> None:
    """All private task fixture entries must have fixture=True."""
    fixture_map = load_fixture_results()
    bad = [
        (task_id, cond)
        for (task_id, cond), result in fixture_map.items()
        if any(t.id == task_id for t in PRIVATE_KNOWLEDGE_TASKS) and not result.fixture
    ]
    assert not bad, f"Private task fixtures with fixture=False: {bad}"


# ---------------------------------------------------------------------------
# Spot-check: known task properties
# ---------------------------------------------------------------------------


def test_task_ids_include_expected_categories() -> None:
    """Spot-check that expected category tasks are present."""
    ids = {t.id for t in PRIVATE_KNOWLEDGE_TASKS}
    # Header tasks
    assert "rz_request_id_header" in ids
    assert "rz_service_auth_header" in ids
    # Error convention tasks
    assert "gateway_timeout_code" in ids
    assert "auth_error_hint_field" in ids
    # Money tasks
    assert "inr_rounding_mode" in ids
    assert "amount_paise_field" in ids
    # Date tasks
    assert "billing_cycle_tz" in ids
    # Security tasks
    assert "tls_min_version" in ids
    # DB tasks
    assert "migration_prefix" in ids
