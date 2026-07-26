"""Tests for ``onmc commands`` — help tiering by category.

Coverage
--------
1. ``group_commands``: known commands map to the correct category.
2. ``group_commands``: unmapped command lands in "Other".
3. ``CORE_COMMANDS`` is non-empty and contains expected names.
4. ``group_commands`` output is deterministic (sorted, stable).
5. All ``CATEGORY_ORDER`` keys are present in the output of ``group_commands``.
6. Memory-specific commands group correctly.
7. Trust-specific commands group correctly.
8. ``onmc commands --json`` envelope has required keys (total, core, groups).
9. ``onmc commands --json`` total == sum of all group lengths.
10. ``onmc commands --json`` core list contains "setup".
11. ``onmc commands --all`` exits zero and shows content.
12. ``onmc commands --category Memory`` shows Memory commands.
13. ``onmc commands`` (default) shows "Core" in output.
14. ``onmc commands --category unknowncategory`` exits non-zero.
15. Category order: "Core" first, "Other" last.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.commands_help.core import (
    CATEGORY_MAP,
    CATEGORY_ORDER,
    CORE_COMMANDS,
    group_commands,
)


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Pure-function unit tests (no CLI runner, no I/O)
# ---------------------------------------------------------------------------


class TestGroupCommands:
    def test_known_commands_map_to_correct_category(self) -> None:
        """setup/recall/mission → Core; swarm → Orchestrate."""
        grouped = group_commands(["setup", "recall", "mission", "swarm"])
        assert "setup" in grouped["Core"]
        assert "recall" in grouped["Core"]
        assert "mission" in grouped["Core"]
        assert "swarm" in grouped["Orchestrate"]

    def test_unmapped_command_lands_in_other(self) -> None:
        """A brand-new name absent from CATEGORY_MAP → Other."""
        sentinel = "totally-new-command-xyz-9999"
        assert sentinel not in CATEGORY_MAP
        grouped = group_commands([sentinel])
        assert sentinel in grouped["Other"]

    def test_core_commands_list_non_empty_and_contains_expected(self) -> None:
        """CORE_COMMANDS has entries and includes the canonical set."""
        assert len(CORE_COMMANDS) >= 5
        assert len(CORE_COMMANDS) <= 14
        for name in ("run", "setup", "recall", "mission", "missioncontrol"):
            assert name in CORE_COMMANDS, f"{name!r} missing from CORE_COMMANDS"

    def test_output_is_deterministic_and_sorted_within_category(self) -> None:
        """Two calls with the same names produce identical, sorted results."""
        names = ["setup", "swarm", "mission", "wrap", "recall", "attest"]
        first = group_commands(names)
        second = group_commands(names)
        assert first == second
        for cat, cmds in first.items():
            assert cmds == sorted(cmds), f"Category {cat!r} not sorted: {cmds}"

    def test_all_category_keys_present(self) -> None:
        """group_commands always returns every key in CATEGORY_ORDER."""
        grouped = group_commands(["setup"])
        for cat in CATEGORY_ORDER:
            assert cat in grouped, f"Missing category key {cat!r}"

    def test_memory_commands_grouped_correctly(self) -> None:
        """Memory-tagged commands land in the Memory category."""
        memory_cmds = ["memstage", "membudget", "session-search", "memory", "memory-diff"]
        grouped = group_commands(memory_cmds)
        for cmd in memory_cmds:
            assert cmd in grouped["Memory"], f"{cmd!r} not in Memory"

    def test_trust_commands_grouped_correctly(self) -> None:
        """Trust-tagged commands land in the Trust category."""
        trust_cmds = ["attest", "badge", "registry", "scorecard"]
        grouped = group_commands(trust_cmds)
        for cmd in trust_cmds:
            assert cmd in grouped["Trust"], f"{cmd!r} not in Trust"

    def test_category_order_starts_with_core_ends_with_other(self) -> None:
        """Core is first, Other is last in CATEGORY_ORDER."""
        assert CATEGORY_ORDER[0] == "Core"
        assert CATEGORY_ORDER[-1] == "Other"

    def test_fun_commands_grouped_correctly(self) -> None:
        """Fun-tagged commands land in the Fun category."""
        fun_cmds = ["whip", "arena", "quest", "vibe", "bounty"]
        grouped = group_commands(fun_cmds)
        for cmd in fun_cmds:
            assert cmd in grouped["Fun"], f"{cmd!r} not in Fun"

    def test_integrations_commands_grouped_correctly(self) -> None:
        """Integration commands land in the Integrations category."""
        int_cmds = ["crews", "teams", "sbom", "llm"]
        grouped = group_commands(int_cmds)
        for cmd in int_cmds:
            assert cmd in grouped["Integrations"], f"{cmd!r} not in Integrations"

    def test_empty_input_returns_all_empty_categories(self) -> None:
        """No names → all categories present but empty."""
        grouped = group_commands([])
        for cat in CATEGORY_ORDER:
            assert grouped[cat] == [], f"Expected empty list for {cat!r}"


# ---------------------------------------------------------------------------
# CLI integration tests (CliRunner)
# ---------------------------------------------------------------------------


class TestCommandsCli:
    def test_json_envelope_has_required_keys(self, runner: CliRunner) -> None:
        """--json output contains 'total', 'core', and 'groups' keys."""
        result = runner.invoke(app, ["commands", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data: dict[str, Any] = json.loads(result.output)
        assert "total" in data, "Missing 'total' key"
        assert "core" in data, "Missing 'core' key"
        assert "groups" in data, "Missing 'groups' key"
        assert isinstance(data["total"], int)
        assert isinstance(data["core"], list)
        assert isinstance(data["groups"], dict)

    def test_json_total_equals_sum_of_groups(self, runner: CliRunner) -> None:
        """total in JSON equals the sum of all group lengths."""
        result = runner.invoke(app, ["commands", "--json"], catch_exceptions=False)
        assert result.exit_code == 0
        data: dict[str, Any] = json.loads(result.output)
        total_in_groups = sum(len(v) for v in data["groups"].values())
        assert data["total"] == total_in_groups

    def test_json_core_list_contains_setup(self, runner: CliRunner) -> None:
        """--json 'core' list includes 'setup'."""
        result = runner.invoke(app, ["commands", "--json"], catch_exceptions=False)
        assert result.exit_code == 0
        data: dict[str, Any] = json.loads(result.output)
        assert "setup" in data["core"], f"'setup' missing from core: {data['core']}"

    def test_json_groups_contains_all_categories(self, runner: CliRunner) -> None:
        """--json 'groups' dict has all expected category keys."""
        result = runner.invoke(app, ["commands", "--json"], catch_exceptions=False)
        assert result.exit_code == 0
        data: dict[str, Any] = json.loads(result.output)
        for cat in CATEGORY_ORDER:
            assert cat in data["groups"], f"Missing group key {cat!r}"

    def test_all_flag_exits_zero(self, runner: CliRunner) -> None:
        """--all exits with code 0."""
        result = runner.invoke(app, ["commands", "--all"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_all_flag_shows_orchestrate_commands(self, runner: CliRunner) -> None:
        """--all expands Orchestrate and shows 'mission'."""
        result = runner.invoke(app, ["commands", "--all"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "mission" in result.output

    def test_category_memory_filters_output(self, runner: CliRunner) -> None:
        """--category Memory shows Memory commands."""
        result = runner.invoke(
            app, ["commands", "--category", "Memory"], catch_exceptions=False
        )
        assert result.exit_code == 0
        assert "Memory" in result.output
        # At least one well-known Memory command must appear.
        assert any(
            cmd in result.output for cmd in ("session-search", "memstage", "membudget")
        )

    def test_default_shows_core_header(self, runner: CliRunner) -> None:
        """Default invocation shows the 'Core' category header."""
        result = runner.invoke(app, ["commands"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Core" in result.output

    def test_default_shows_setup_in_core(self, runner: CliRunner) -> None:
        """Default invocation lists 'setup' under Core."""
        result = runner.invoke(app, ["commands"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "setup" in result.output

    def test_unknown_category_exits_nonzero(self, runner: CliRunner) -> None:
        """--category with a bogus name exits with a non-zero code."""
        result = runner.invoke(app, ["commands", "--category", "Bogus"])
        assert result.exit_code != 0

    def test_category_case_insensitive(self, runner: CliRunner) -> None:
        """--category is case-insensitive (memory == Memory)."""
        result = runner.invoke(
            app, ["commands", "--category", "memory"], catch_exceptions=False
        )
        assert result.exit_code == 0
        assert "Memory" in result.output

    def test_json_groups_are_sorted_lists(self, runner: CliRunner) -> None:
        """Each group in --json output is a sorted list of strings."""
        result = runner.invoke(app, ["commands", "--json"], catch_exceptions=False)
        assert result.exit_code == 0
        data: dict[str, Any] = json.loads(result.output)
        for cat, cmds in data["groups"].items():
            assert isinstance(cmds, list), f"{cat} value is not a list"
            assert cmds == sorted(cmds), f"{cat} commands not sorted: {cmds}"
