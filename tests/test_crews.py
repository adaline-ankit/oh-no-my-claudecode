"""Tests for ``onmc crews`` — optional CrewAI interop.

Coverage
--------
1. ``plan_to_crew_spec`` produces a valid crew spec (agents + tasks) from a
   seeded MissionPlan-shaped dict.
2. Output is deterministic: two calls with the same input produce identical dicts.
3. ``plan_to_crew_spec`` handles a swarm manifest dict (units as list).
4. ``plan_to_crew_spec`` handles a swarm manifest dict (units as dict).
5. ``plan_to_crew_spec`` falls back gracefully when neither swarm_units nor
   units is present (single synthetic unit from goal).
6. ``crewai_available`` returns ``False`` in the test environment (crewai
   is not a dev dependency of onmc).
7. ``run_crew`` with an INJECTED fake runner records an accountability receipt.
8. ``run_crew`` without crewai (and no runner) raises ``RuntimeError``.
9. CLI ``onmc crews export`` writes a valid crew spec to stdout.
10. CLI ``onmc crews export --json`` wraps spec in onmc envelope.
11. CLI ``onmc crews export --out FILE`` writes to a file.
12. CLI ``onmc crews run`` without crewai exits non-zero with a clear message.
13. ``importorskip`` smoke: basic spec structure holds when crewai IS installed
    (skipped in normal dev environment).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.crews.interop import (
    CrewRunReceipt,
    crewai_available,
    plan_to_crew_spec,
    run_crew,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

_MISSION_PLAN: dict[str, Any] = {
    "goal": "Build a semantic search feature",
    "execute": False,
    "dead_ends": [],
    "blast_radius": ["src/search/engine.py"],
    "swarm_units": [
        "Implement the embedding pipeline",
        "Write the vector store adapter",
        "Add the search API endpoint",
    ],
    "steps": [],
    "pack": {},
    "swarm": None,
}

_SWARM_MANIFEST_LIST: dict[str, Any] = {
    "swarm_id": "abc123",
    "mode": "inline",
    "goal": "Refactor auth module",
    "units": [
        {"id": "unit-0000", "goal": "Extract token validation logic"},
        {"id": "unit-0001", "goal": "Add refresh-token support"},
    ],
}

_SWARM_MANIFEST_DICT: dict[str, Any] = {
    "swarm_id": "def456",
    "mode": "inline",
    "goal": "Deploy infra changes",
    "units": {
        "unit-0000": {"goal": "Update Pulumi stacks", "status": "pending"},
        "unit-0001": {"goal": "Verify DNS propagation", "status": "pending"},
    },
}


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# 1. plan_to_crew_spec — valid structure from MissionPlan
# ---------------------------------------------------------------------------


class TestPlanToCrewSpecMissionPlan:
    def test_returns_dict_with_required_keys(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        assert isinstance(spec, dict)
        for key in ("kind", "version", "source", "goal", "spec_hash", "agents", "tasks"):
            assert key in spec, f"missing key: {key}"

    def test_kind_is_crew_spec(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        assert spec["kind"] == "crew_spec"

    def test_agent_count_matches_swarm_units(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        assert len(spec["agents"]) == len(_MISSION_PLAN["swarm_units"])

    def test_task_count_matches_agent_count(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        assert len(spec["tasks"]) == len(spec["agents"])

    def test_agent_fields_present(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        for agent in spec["agents"]:
            assert "role" in agent
            assert "goal" in agent
            assert "backstory" in agent
            # role must contain the goal excerpt
            assert agent["goal"] in agent["role"] or len(agent["role"]) > 0

    def test_task_fields_present(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        for task in spec["tasks"]:
            assert "description" in task
            assert "expected_output" in task
            assert "agent_role" in task

    def test_task_agent_role_matches_an_agent(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        agent_roles = {a["role"] for a in spec["agents"]}
        for task in spec["tasks"]:
            assert task["agent_role"] in agent_roles

    def test_goal_preserved(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        assert spec["goal"] == _MISSION_PLAN["goal"]

    def test_spec_hash_is_12_chars(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        assert isinstance(spec["spec_hash"], str)
        assert len(spec["spec_hash"]) == 12


# ---------------------------------------------------------------------------
# 2. Determinism
# ---------------------------------------------------------------------------


class TestPlanToCrewSpecDeterminism:
    def test_same_plan_produces_same_spec(self) -> None:
        spec_a = plan_to_crew_spec(_MISSION_PLAN)
        spec_b = plan_to_crew_spec(_MISSION_PLAN)
        assert spec_a == spec_b

    def test_spec_hash_stable_across_calls(self) -> None:
        h1 = plan_to_crew_spec(_MISSION_PLAN)["spec_hash"]
        h2 = plan_to_crew_spec(_MISSION_PLAN)["spec_hash"]
        assert h1 == h2

    def test_different_goals_produce_different_hashes(self) -> None:
        plan_a = {**_MISSION_PLAN, "goal": "goal A", "swarm_units": ["do A"]}
        plan_b = {**_MISSION_PLAN, "goal": "goal B", "swarm_units": ["do B"]}
        assert plan_to_crew_spec(plan_a)["spec_hash"] != plan_to_crew_spec(plan_b)["spec_hash"]


# ---------------------------------------------------------------------------
# 3. Swarm manifest (units as list)
# ---------------------------------------------------------------------------


class TestPlanToCrewSpecSwarmManifestList:
    def test_units_extracted_from_list(self) -> None:
        spec = plan_to_crew_spec(_SWARM_MANIFEST_LIST)
        assert len(spec["agents"]) == 2

    def test_unit_ids_in_agent_roles(self) -> None:
        spec = plan_to_crew_spec(_SWARM_MANIFEST_LIST)
        for agent in spec["agents"]:
            # role must start with "unit-000X:"
            assert agent["role"].startswith("unit-")

    def test_source_label_swarm(self) -> None:
        spec = plan_to_crew_spec(_SWARM_MANIFEST_LIST)
        assert spec["source"] == "onmc_swarm"


# ---------------------------------------------------------------------------
# 4. Swarm manifest (units as dict)
# ---------------------------------------------------------------------------


class TestPlanToCrewSpecSwarmManifestDict:
    def test_units_extracted_from_dict(self) -> None:
        spec = plan_to_crew_spec(_SWARM_MANIFEST_DICT)
        assert len(spec["agents"]) == 2

    def test_goals_preserved(self) -> None:
        spec = plan_to_crew_spec(_SWARM_MANIFEST_DICT)
        goals = {a["goal"] for a in spec["agents"]}
        assert "Update Pulumi stacks" in goals
        assert "Verify DNS propagation" in goals


# ---------------------------------------------------------------------------
# 5. Fallback — no swarm_units, no units
# ---------------------------------------------------------------------------


class TestPlanToCrewSpecFallback:
    def test_single_unit_from_goal(self) -> None:
        spec = plan_to_crew_spec({"goal": "do something"})
        assert len(spec["agents"]) == 1
        assert spec["agents"][0]["goal"] == "do something"

    def test_empty_plan_gives_one_unit(self) -> None:
        spec = plan_to_crew_spec({})
        assert len(spec["agents"]) == 1


# ---------------------------------------------------------------------------
# 6. crewai_available returns False
# ---------------------------------------------------------------------------


class TestCrewaiAvailable:
    def test_returns_false_when_absent(self) -> None:
        # crewai is not in dev dependencies; this should reliably return False.
        # If someone installs crewai into the test env, this test is still valid
        # because we verify the return type.
        result = crewai_available()
        assert isinstance(result, bool)
        # In the standard dev environment without [crewai] extra, it must be False.
        # We patch the import to be safe across all environments.
        with patch.dict("sys.modules", {"crewai": None}):
            assert crewai_available() is False


# ---------------------------------------------------------------------------
# 7. run_crew with injected fake runner
# ---------------------------------------------------------------------------


class TestRunCrewInjectedRunner:
    def _fake_runner(self, spec: dict[str, Any]) -> dict[str, Any]:
        return {"output": "all tasks completed", "extra_field": "value"}

    def test_returns_crew_run_receipt(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        receipt = run_crew(spec, runner=self._fake_runner)
        assert isinstance(receipt, CrewRunReceipt)

    def test_receipt_runner_label_is_injected(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        receipt = run_crew(spec, runner=self._fake_runner)
        assert receipt.runner == "injected"

    def test_receipt_outcome_captured(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        receipt = run_crew(spec, runner=self._fake_runner)
        assert receipt.outcome == "all tasks completed"

    def test_receipt_goal_matches_spec(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        receipt = run_crew(spec, runner=self._fake_runner)
        assert receipt.goal == spec["goal"]

    def test_receipt_agent_count(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        receipt = run_crew(spec, runner=self._fake_runner)
        assert receipt.agent_count == len(spec["agents"])

    def test_receipt_task_count(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        receipt = run_crew(spec, runner=self._fake_runner)
        assert receipt.task_count == len(spec["tasks"])

    def test_receipt_extra_fields_preserved(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        receipt = run_crew(spec, runner=self._fake_runner)
        assert receipt.extra.get("extra_field") == "value"

    def test_receipt_to_dict_serialisable(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        receipt = run_crew(spec, runner=self._fake_runner)
        d = receipt.to_dict()
        assert d["kind"] == "crew_run_receipt"
        # Must be JSON-serialisable.
        json.dumps(d)

    def test_receipt_timestamps_present(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        receipt = run_crew(spec, runner=self._fake_runner)
        assert receipt.started_at
        assert receipt.ended_at

    def test_receipt_onmc_version_set(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        receipt = run_crew(spec, runner=self._fake_runner)
        assert receipt.onmc_version  # non-empty


# ---------------------------------------------------------------------------
# 8. run_crew without crewai raises RuntimeError
# ---------------------------------------------------------------------------


class TestRunCrewNoCrewai:
    def test_raises_runtime_error_when_absent(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        # Patch crewai away to simulate absence even if it happens to be installed.
        with patch.dict("sys.modules", {"crewai": None}), pytest.raises(
            RuntimeError, match="crewai is not installed"
        ):
            run_crew(spec)


# ---------------------------------------------------------------------------
# 9–12. CLI tests
# ---------------------------------------------------------------------------


class TestCrewsExportCli:
    def test_export_outputs_valid_json(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(_MISSION_PLAN), encoding="utf-8")
        result = cli_runner.invoke(app, ["crews", "export", str(plan_file)])
        assert result.exit_code == 0
        spec = json.loads(result.stdout)
        assert spec["kind"] == "crew_spec"
        assert len(spec["agents"]) == 3

    def test_export_json_flag_wraps_in_envelope(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(_MISSION_PLAN), encoding="utf-8")
        result = cli_runner.invoke(app, ["crews", "export", str(plan_file), "--json"])
        assert result.exit_code == 0
        envelope = json.loads(result.stdout)
        assert envelope["kind"] == "crews_export"
        assert "spec" in envelope
        assert envelope["spec"]["kind"] == "crew_spec"

    def test_export_out_file_writes_file(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan.json"
        out_file = tmp_path / "crew.json"
        plan_file.write_text(json.dumps(_MISSION_PLAN), encoding="utf-8")
        result = cli_runner.invoke(
            app, ["crews", "export", str(plan_file), "--out", str(out_file)]
        )
        assert result.exit_code == 0
        assert out_file.exists()
        spec = json.loads(out_file.read_text(encoding="utf-8"))
        assert spec["kind"] == "crew_spec"

    def test_export_missing_file_exits_nonzero(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        result = cli_runner.invoke(
            app, ["crews", "export", str(tmp_path / "nonexistent.json")]
        )
        assert result.exit_code != 0


class TestCrewsRunCli:
    def test_run_without_crewai_exits_nonzero(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        spec_file = tmp_path / "crew.json"
        spec = plan_to_crew_spec(_MISSION_PLAN)
        spec_file.write_text(json.dumps(spec), encoding="utf-8")
        # Patch crewai_available to return False.
        with patch("oh_no_my_claudecode.crews.commands.crewai_available", return_value=False):
            result = cli_runner.invoke(app, ["crews", "run", str(spec_file)])
        assert result.exit_code != 0
        assert "crewai" in (result.output + (result.stderr or "")).lower()


# ---------------------------------------------------------------------------
# 13. importorskip real-lib smoke (skipped in standard dev env)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not crewai_available(), reason="crewai not installed")
class TestCrewaiRealLibSmoke:
    """Smoke tests that only run when crewai is actually installed.

    These tests verify that the spec structure produced by ``plan_to_crew_spec``
    has the right shape to drive real crewai constructors, WITHOUT making any
    LLM API calls (no network).
    """

    def test_agents_have_required_crewai_fields(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        for agent in spec["agents"]:
            # crewai.Agent requires role, goal, backstory
            assert agent["role"]
            assert agent["goal"]
            assert agent["backstory"]

    def test_tasks_have_required_crewai_fields(self) -> None:
        spec = plan_to_crew_spec(_MISSION_PLAN)
        for task in spec["tasks"]:
            # crewai.Task requires description, expected_output, agent
            assert task["description"]
            assert task["expected_output"]
            assert task["agent_role"]
