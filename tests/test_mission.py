"""Tests for the ``mission`` feature — one-command grounded mission plan.

Covers the auto-discovery ``onmc mission`` command and the underlying
:func:`oh_no_my_claudecode.mission.planner.compile_mission`:

- a seeded dead-end + decision and a real repo surface in the plan (dead-ends,
  context files, a route decision, suggested units, a next-command string);
- a fresh (empty) brain still yields a valid, non-crashing plan;
- the ``--json`` CLI surface has the documented shape;
- output is deterministic across repeated calls;
- the CLI exercises the real flags (never asserts Rich ``--help`` text).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode import init
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.mission.planner import MissionPlan, compile_mission
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

runner = CliRunner()


# ---------------------------------------------------------------------------
# Seeding helpers (mirrors tests/test_pack.py)
# ---------------------------------------------------------------------------


def _seed_memory(
    storage: SQLiteStorage,
    *,
    kind: MemoryKind,
    title: str,
    summary: str,
    details: str,
) -> str:
    now = utc_now()
    entry = MemoryEntry(
        id=stable_id(kind.value, title, summary, "test:seed", prefix="test"),
        kind=kind,
        title=title,
        summary=summary,
        details=details,
        source_type=SourceType.MANUAL,
        source_ref="test:seed",
        tags=[kind.value],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return entry.id


def _storage(sample_repo: Path) -> SQLiteStorage:
    repo = init(sample_repo)
    repo.ingest()
    _, _, storage = repo._service._load_context()
    return storage


# ---------------------------------------------------------------------------
# compile_mission: content surfacing
# ---------------------------------------------------------------------------


def test_compile_mission_surfaces_grounding(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    _seed_memory(
        storage,
        kind=MemoryKind.FAILED_APPROACH,
        title="Bypass cache via direct Redis writes",
        summary="Tried writing cache invalidation keys directly to Redis.",
        details="Bypassing the cache module broke invalidation consistency.",
    )
    _seed_memory(
        storage,
        kind=MemoryKind.DECISION,
        title="Cache invalidation goes through the cache module",
        summary="All cache invalidation must flow through invalidate_cache.",
        details="Keeps the invalidation boundary single-sourced.",
    )

    plan = compile_mission(storage, sample_repo, "fix cache invalidation bug")

    # dead-end surfaced (KNOWN dead-end to avoid)
    assert any("bypass" in title.lower() for title, _why in plan.dead_ends)
    # context file surfaced (tiny relevant file set)
    assert plan.context_files
    assert any("cache" in path.lower() for path in plan.context_files)
    # a route decision was made
    assert plan.route is not None
    assert plan.route.agent
    assert plan.route.strategy in {"single", "loop", "swarm"}
    # suggested unit breakdown
    assert plan.suggested_units
    # the exact swarm command to run next
    assert plan.next_command.startswith("onmc swarm plan ")
    assert "--task" in plan.next_command
    assert plan.next_command.endswith("--json")
    # the brief grounds the mission
    assert "cache invalidation" in plan.brief.lower()


def test_compile_mission_route_matches_intent(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    # "migration"/"production" should route to the careful/nomistakes path.
    plan = compile_mission(storage, sample_repo, "run a risky production migration")
    assert plan.route is not None
    assert plan.route.gate == "nomistakes"


def test_suggested_units_have_an_integration_unit(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    plan = compile_mission(storage, sample_repo, "refactor the cache worker module")
    # When context files exist, the last unit converges the fan-out.
    if len(plan.context_files) > 0:
        assert any("integrate and verify" in u.lower() for u in plan.suggested_units)
    # Each unit feeds a --task in the next command.
    assert plan.next_command.count("--task") == len(plan.suggested_units)


# ---------------------------------------------------------------------------
# Empty brain / empty goal: graceful degradation
# ---------------------------------------------------------------------------


def test_compile_mission_empty_brain_does_not_crash(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)  # nothing seeded beyond ambient ingest

    plan = compile_mission(storage, sample_repo, "fix cache invalidation bug")

    # No dead-ends were seeded.
    assert plan.dead_ends == []
    # Still a complete, runnable plan.
    assert plan.route is not None
    assert plan.suggested_units
    assert plan.next_command.startswith("onmc swarm plan ")


def test_compile_mission_empty_goal_is_graceful(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    plan = compile_mission(storage, sample_repo, "   ")

    assert plan.goal == ""
    assert plan.dead_ends == []
    assert plan.context_files == []
    assert plan.suggested_units == []
    # Nothing to run when there is no goal.
    assert plan.next_command == ""
    assert "No goal" in plan.brief


def test_compile_mission_unknown_goal_yields_single_unit(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    # A goal with no token overlap with the repo → no context files, one unit.
    plan = compile_mission(storage, sample_repo, "zzqq nonexistent quantum widget")
    assert plan.context_files == []
    assert plan.suggested_units == ["zzqq nonexistent quantum widget"]
    assert plan.next_command.count("--task") == 1


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compile_mission_is_deterministic(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    first = compile_mission(storage, sample_repo, "cache worker tests")
    second = compile_mission(storage, sample_repo, "cache worker tests")
    assert first == second
    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# JSON shape & dataclass serialisation
# ---------------------------------------------------------------------------


def test_mission_plan_to_dict_shape() -> None:
    from oh_no_my_claudecode.route.router import route_task

    plan = MissionPlan(
        goal="g",
        brief="b",
        dead_ends=[("t", "w")],
        context_files=["a.py"],
        route=route_task("build a feature"),
        suggested_units=["g — focus on a.py"],
        next_command="onmc swarm plan --task 'g' --json",
    )
    d = plan.to_dict()
    assert set(d) == {
        "goal",
        "brief",
        "dead_ends",
        "context_files",
        "route",
        "suggested_units",
        "next_command",
    }
    assert d["dead_ends"] == [{"title": "t", "why": "w"}]
    assert isinstance(d["route"], dict)
    assert d["route"]["gate"]  # route serialised as a mapping


# ---------------------------------------------------------------------------
# CLI surface (exercise real flags — never assert Rich --help)
# ---------------------------------------------------------------------------


def test_cli_mission_json_shape(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    _storage(sample_repo)  # initialise the brain in-place

    result = runner.invoke(app, ["mission", "fix cache invalidation bug", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["goal"] == "fix cache invalidation bug"
    assert payload["next_command"].startswith("onmc swarm plan ")
    assert isinstance(payload["suggested_units"], list)
    assert isinstance(payload["context_files"], list)
    assert payload["route"] is not None


def test_cli_mission_markdown_render(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    _storage(sample_repo)

    result = runner.invoke(app, ["mission", "fix the cache worker", "--budget", "2000"])
    assert result.exit_code == 0, result.output
    assert "# Mission Plan" in result.output
    assert "Recommended route" in result.output
    assert "Run next" in result.output
    assert "onmc swarm plan" in result.output


def test_cli_mission_outside_repo_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["mission", "anything"])
    assert result.exit_code == 1
