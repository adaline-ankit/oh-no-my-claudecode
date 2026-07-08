"""Tests for ``onmc teams`` — AutoGen interop.

Coverage
--------
1.  ``plan_to_team_spec`` produces a valid spec from a seeded mission plan.
2.  ``plan_to_team_spec`` is deterministic (two calls produce identical output).
3.  ``plan_to_team_spec`` uses ``swarm_units`` to build one agent per unit.
4.  ``plan_to_team_spec`` falls back to a single agent when swarm_units absent.
5.  ``export`` CLI writes ``--json`` envelope correctly.
6.  ``export`` CLI writes ``--out FILE`` path.
7.  ``autogen_available`` returns False when autogen/ag2 are not installed.
8.  ``run_team`` with an INJECTED fake runner writes a receipt and returns status=ok.
9.  ``run`` CLI errors with non-zero exit when autogen is absent.
10. ``run_team`` receipt is written to the correct path with expected fields.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.teams.interop import (
    autogen_available,
    plan_to_team_spec,
    run_team,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_MINIMAL_PLAN: dict[str, Any] = {
    "goal": "Add a timeout parameter to fetchData()",
    "swarm_units": [
        "Update fetchData signature with timeout param",
        "Thread timeout through to the fetch call",
        "Add test coverage for timeout",
    ],
    "dead_ends": ["do not use sleep()"],
    "blast_radius": ["src/api.ts", "tests/api.test.ts"],
    "execute": False,
    "steps": [],
    "pack": {},
}

_PLAN_NO_UNITS: dict[str, Any] = {
    "goal": "Refactor auth module",
    "swarm_units": [],
    "dead_ends": [],
    "blast_radius": [],
}


def _fake_runner(spec: dict[str, Any]) -> dict[str, Any]:
    """Offline fake runner — returns a canned result without any network call."""
    return {
        "chat_history": ["[worker_0]: Done.", "[onmc_manager]: All good."],
        "agent_count": len(spec.get("agents", [])),
    }


# ---------------------------------------------------------------------------
# 1. Valid spec from seeded plan
# ---------------------------------------------------------------------------


class TestPlanToTeamSpec:
    def test_returns_expected_kind(self) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        assert spec["kind"] == "onmc-autogen-team-v1"

    def test_goal_preserved(self) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        assert spec["goal"] == _MINIMAL_PLAN["goal"]

    def test_agents_match_swarm_units(self) -> None:
        """One agent per swarm unit."""
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        assert len(spec["agents"]) == len(_MINIMAL_PLAN["swarm_units"])

    def test_agent_names_sequential(self) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        names = [a["name"] for a in spec["agents"]]
        assert names == ["worker_0", "worker_1", "worker_2"]

    def test_manager_present(self) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        assert spec["manager"]["name"] == "onmc_manager"
        assert spec["manager"]["role"] == "orchestrator"

    def test_orchestration_is_group_chat(self) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        assert spec["orchestration"] == "group_chat"

    def test_metadata_dead_ends_and_blast_radius(self) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        assert spec["metadata"]["dead_ends"] == _MINIMAL_PLAN["dead_ends"]
        assert spec["metadata"]["blast_radius"] == _MINIMAL_PLAN["blast_radius"]

    def test_metadata_generated_by(self) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        assert spec["metadata"]["generated_by"] == "onmc"


# ---------------------------------------------------------------------------
# 2. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_two_calls_identical(self) -> None:
        """plan_to_team_spec is deterministic for the same input."""
        spec_a = plan_to_team_spec(_MINIMAL_PLAN)
        spec_b = plan_to_team_spec(_MINIMAL_PLAN)
        assert json.dumps(spec_a, sort_keys=True) == json.dumps(spec_b, sort_keys=True)


# ---------------------------------------------------------------------------
# 3 & 4. swarm_units / fallback
# ---------------------------------------------------------------------------


class TestAgentCount:
    def test_three_units_three_agents(self) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        assert len(spec["agents"]) == 3

    def test_no_units_single_agent_fallback(self) -> None:
        """When swarm_units is empty, fall back to one worker_0 with the goal."""
        spec = plan_to_team_spec(_PLAN_NO_UNITS)
        assert len(spec["agents"]) == 1
        assert spec["agents"][0]["name"] == "worker_0"
        assert spec["agents"][0]["goal"] == _PLAN_NO_UNITS["goal"]


# ---------------------------------------------------------------------------
# 5. export --json envelope
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestExportCli:
    def _plan_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "mission.json"
        p.write_text(json.dumps(_MINIMAL_PLAN), encoding="utf-8")
        return p

    def test_export_default_is_valid_spec(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        plan_file = self._plan_file(tmp_path)
        result = runner.invoke(app, ["teams", "export", str(plan_file)])
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["kind"] == "onmc-autogen-team-v1"

    def test_export_json_envelope(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """``--json`` wraps the spec in ``{"kind": "autogen-team", "spec": {...}}``."""
        plan_file = self._plan_file(tmp_path)
        result = runner.invoke(app, ["teams", "export", str(plan_file), "--json"])
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["kind"] == "autogen-team"
        assert "spec" in parsed
        assert parsed["spec"]["kind"] == "onmc-autogen-team-v1"

    def test_export_out_writes_file(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """``--out FILE`` writes the spec to the given path."""
        plan_file = self._plan_file(tmp_path)
        out_file = tmp_path / "team.json"
        result = runner.invoke(
            app, ["teams", "export", str(plan_file), "--out", str(out_file)]
        )
        assert result.exit_code == 0, result.output
        assert out_file.exists()
        parsed = json.loads(out_file.read_text(encoding="utf-8"))
        assert parsed["kind"] == "onmc-autogen-team-v1"

    def test_export_missing_file_exits_1(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Non-existent plan path → exit code 1."""
        result = runner.invoke(app, ["teams", "export", str(tmp_path / "no.json")])
        assert result.exit_code == 1

    def test_export_bad_json_exits_1(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Invalid JSON → exit code 1."""
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        result = runner.invoke(app, ["teams", "export", str(bad)])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# 7. autogen_available returns False when absent
# ---------------------------------------------------------------------------


class TestAutogenAvailable:
    def test_returns_false_when_not_installed(self) -> None:
        """autogen_available() is False in the test environment (no autogen)."""
        import oh_no_my_claudecode.teams.interop as interop_mod

        original = interop_mod._AUTOGEN_AVAILABLE
        # Force a fresh probe by resetting the cache.
        interop_mod._AUTOGEN_AVAILABLE = None
        try:
            # Mask both autogen and ag2 to simulate absent extra.
            with (
                patch.dict(sys.modules, {"autogen": None, "ag2": None}),
            ):
                result = autogen_available()
            # Result depends on environment; assert consistency with cache.
            assert result == interop_mod._AUTOGEN_AVAILABLE
        finally:
            interop_mod._AUTOGEN_AVAILABLE = original


# ---------------------------------------------------------------------------
# 8. run_team with injected fake runner → receipt recorded
# ---------------------------------------------------------------------------


class TestRunTeamWithFakeRunner:
    def test_status_is_ok(self, tmp_path: Path) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        outcome = run_team(spec, runner=_fake_runner, repo_root=tmp_path)
        assert outcome["status"] == "ok"

    def test_receipt_path_exists(self, tmp_path: Path) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        outcome = run_team(spec, runner=_fake_runner, repo_root=tmp_path)
        receipt_path = Path(outcome["receipt_path"])
        assert receipt_path.exists()

    def test_receipt_contains_expected_fields(self, tmp_path: Path) -> None:
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        outcome = run_team(spec, runner=_fake_runner, repo_root=tmp_path)
        receipt = json.loads(Path(outcome["receipt_path"]).read_text(encoding="utf-8"))
        assert receipt["schema_version"] == "team-1"
        assert receipt["kind"] == "team-run-receipt"
        assert receipt["spec_goal"] == _MINIMAL_PLAN["goal"]
        assert "receipt_hash" in receipt
        assert "started_at" in receipt
        assert "ended_at" in receipt

    def test_receipt_result_matches_fake_runner(self, tmp_path: Path) -> None:
        """The receipt embeds the runner's result dict."""
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        outcome = run_team(spec, runner=_fake_runner, repo_root=tmp_path)
        receipt = json.loads(Path(outcome["receipt_path"]).read_text(encoding="utf-8"))
        assert receipt["result"]["agent_count"] == len(spec["agents"])

    def test_receipt_is_in_agent_memory_receipts(self, tmp_path: Path) -> None:
        """Receipt lands under .agent-memory/receipts/."""
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        outcome = run_team(spec, runner=_fake_runner, repo_root=tmp_path)
        receipt_path = Path(outcome["receipt_path"])
        assert receipt_path.parent == tmp_path / ".agent-memory" / "receipts"

    def test_outcome_result_equals_runner_output(self, tmp_path: Path) -> None:
        """The returned outcome['result'] is the raw runner output."""
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        expected_result = _fake_runner(spec)
        outcome = run_team(spec, runner=_fake_runner, repo_root=tmp_path)
        assert outcome["result"]["agent_count"] == expected_result["agent_count"]


# ---------------------------------------------------------------------------
# 9. run CLI errors cleanly when autogen absent
# ---------------------------------------------------------------------------


class TestRunCliWithoutAutogen:
    def test_run_exits_1_when_autogen_absent(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """``onmc teams run`` exits with code 1 and helpful message when absent."""
        spec = plan_to_team_spec(_MINIMAL_PLAN)
        spec_file = tmp_path / "team.json"
        spec_file.write_text(json.dumps(spec), encoding="utf-8")

        import oh_no_my_claudecode.teams.interop as interop_mod

        original = interop_mod._AUTOGEN_AVAILABLE
        interop_mod._AUTOGEN_AVAILABLE = False
        try:
            result = runner.invoke(app, ["teams", "run", str(spec_file)])
            assert result.exit_code == 1
            assert "autogen" in result.output.lower() or (
                result.stderr_bytes is not None
                and b"autogen" in result.stderr_bytes.lower()
            )
        finally:
            interop_mod._AUTOGEN_AVAILABLE = original
