"""Tests for the mission-bridge intake normalizer.

Covers :func:`oh_no_my_claudecode.missionbridge.intake.parse_intake`:

- a plain mention + goal yields the goal with no options;
- inline flag options (``--concurrency`` / ``--budget-usd``) parse and are
  stripped from the goal;
- natural-language option forms (``with N agents`` / ``budget $X`` / ``cap $X``)
  parse too;
- ``/onmc`` and ``onmc:`` command prefixes are handled;
- mention-only / empty messages return ``None``;
- parsing is deterministic.

Pure + offline: no CLI, no ``--help`` assertions.
"""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.missionbridge.intake import parse_intake
from oh_no_my_claudecode.missionbridge.models import IntakeTask


def test_plain_mention_and_goal() -> None:
    task = parse_intake("@onmc add OAuth to auth")
    assert task == IntakeTask(goal="add OAuth to auth", concurrency=None, budget_usd=None)


def test_flag_options_parse_and_strip() -> None:
    task = parse_intake("@onmc refactor X --concurrency 4 --budget-usd 3")
    assert task is not None
    assert task.goal == "refactor X"
    assert task.concurrency == 4
    assert task.budget_usd == 3.0


def test_concurrency_equals_form() -> None:
    task = parse_intake("@onmc tidy imports conc=6")
    assert task is not None
    assert task.goal == "tidy imports"
    assert task.concurrency == 6


def test_natural_language_agents_form() -> None:
    task = parse_intake("@onmc build the dashboard with 8 agents")
    assert task is not None
    assert task.goal == "build the dashboard"
    assert task.concurrency == 8


def test_natural_language_budget_dollar_form() -> None:
    task = parse_intake("@onmc ship the docs budget $5")
    assert task is not None
    assert task.goal == "ship the docs"
    assert task.budget_usd == 5.0


def test_natural_language_cap_dollar_form() -> None:
    task = parse_intake("@onmc migrate schema cap $12.50")
    assert task is not None
    assert task.goal == "migrate schema"
    assert task.budget_usd == 12.5


def test_slash_command_prefix() -> None:
    task = parse_intake("/onmc refactor the auth layer")
    assert task is not None
    assert task.goal == "refactor the auth layer"


def test_colon_command_prefix() -> None:
    task = parse_intake("onmc: do the thing")
    assert task is not None
    assert task.goal == "do the thing"


def test_mention_only_returns_none() -> None:
    assert parse_intake("@onmc") is None
    assert parse_intake("  @onmc   ") is None


def test_empty_message_returns_none() -> None:
    assert parse_intake("") is None
    assert parse_intake("     ") is None


def test_options_removed_from_goal() -> None:
    task = parse_intake("@onmc fix the flaky test with 3 agents --budget-usd 2")
    assert task is not None
    assert task.goal == "fix the flaky test"
    assert "--budget-usd" not in task.goal
    assert "agents" not in task.goal
    assert task.concurrency == 3
    assert task.budget_usd == 2.0


def test_bare_name_not_mistaken_inside_word() -> None:
    # "onmcify" must not be stripped as the bare "onmc" handle.
    task = parse_intake("onmcify the pipeline")
    assert task is not None
    assert task.goal == "onmcify the pipeline"


def test_goal_without_mention_is_kept() -> None:
    task = parse_intake("just do the work")
    assert task is not None
    assert task.goal == "just do the work"


def test_custom_mention_handle() -> None:
    task = parse_intake("@bot deploy it", mention="@bot")
    assert task is not None
    assert task.goal == "deploy it"


def test_options_only_returns_none() -> None:
    # A mention followed by nothing but options has no goal.
    assert parse_intake("@onmc --concurrency 4") is None


@pytest.mark.parametrize(
    "message",
    [
        "@onmc add OAuth to auth",
        "@onmc refactor X --concurrency 4 --budget-usd 3",
        "/onmc build with 8 agents budget $9",
    ],
)
def test_deterministic(message: str) -> None:
    assert parse_intake(message) == parse_intake(message)
