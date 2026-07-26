"""Tests for the ``mission`` feature — the keystone pipeline composer.

Covers :func:`oh_no_my_claudecode.mission.pipeline.plan_mission` /
:func:`~oh_no_my_claudecode.mission.pipeline.run_mission` and the auto-discovered
``onmc mission`` command:

- ``plan_mission`` composes a context pack + dead-ends + blast radius + swarm
  units for a seeded brain;
- a fresh (empty) brain yields a valid, non-crashing plan;
- the plan is deterministic across repeated builds;
- the default is plan-only — NO agent spawned, NO swarm manifest written;
- ``run_mission(execute=True)`` delegates to the real shared harness boundary;
- the ``--json`` CLI surface has the expected shape;
- CLI flags (``--execute``, ``--json``) are exercised (never ``--help``).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode import init
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.harness_run.controller import HarnessController
from oh_no_my_claudecode.harness_run.models import HarnessStatus, RunRequest
from oh_no_my_claudecode.harness_run.stages import StageName, StageRecord, StageStatus
from oh_no_my_claudecode.mission.pipeline import (
    MissionPlan,
    plan_mission,
    render_mission_markdown,
    run_mission,
)
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.runtime import RunSpec
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

runner = CliRunner()


# ---------------------------------------------------------------------------
# Seeding helpers
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


def _seed_dead_end(storage: SQLiteStorage) -> None:
    _seed_memory(
        storage,
        kind=MemoryKind.FAILED_APPROACH,
        title="Bypass cache via direct Redis writes",
        summary="Tried writing cache invalidation keys directly to Redis.",
        details="Bypassing the cache module broke invalidation consistency.",
    )


# ---------------------------------------------------------------------------
# plan_mission: composition
# ---------------------------------------------------------------------------


def test_plan_mission_composes_all_sources(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)
    _seed_dead_end(storage)

    plan = plan_mission(storage, sample_repo, "fix cache invalidation bug")

    # dead-end surfaced at the top level of the plan
    assert any("bypass" in title.lower() for title in plan.dead_ends)
    # the composed pack carries the same dead-end
    assert any("bypass" in d.title.lower() for d in plan.pack.dead_ends)
    # codegraph picked the cache module as a context file
    assert any("cache" in path.lower() for path in plan.pack.context_files)
    # blast radius = files that depend on the context files (worker + test),
    # excluding the context files themselves
    assert "src/worker.py" in plan.blast_radius
    assert all(path not in plan.pack.context_files for path in plan.blast_radius)
    # at least one swarm unit was derived, scoped to the goal
    assert plan.swarm_units
    assert all("cache" in u.lower() or "blast" in u.lower() for u in plan.swarm_units)
    # the ordered pipeline trace is present
    assert [s.name for s in plan.steps] == [
        "recall / guard",
        "pack",
        "codegraph",
        "compile harness",
        "execute / verify / prove",
        "learn candidate",
    ]


def test_plan_mission_default_is_plan_only(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    plan = plan_mission(storage, sample_repo, "fix cache invalidation")

    # plan mode never executes and never allocates a swarm manifest
    assert plan.execute is False
    assert plan.swarm is None
    # NO swarm state directory was created by plan mode
    assert not (sample_repo / ".onmc" / "swarm").exists()
    # all execution stages remain planned in dry-run mode
    assert {step.status for step in plan.steps} == {"planned"}


# ---------------------------------------------------------------------------
# Empty brain / graceful degradation
# ---------------------------------------------------------------------------


def test_plan_mission_empty_brain_does_not_crash(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)  # nothing seeded beyond ambient ingest

    plan = plan_mission(storage, sample_repo, "fix cache invalidation bug")

    assert plan.dead_ends == []  # no failed-approach memories seeded
    # the plan is still valid and renders
    markdown = render_mission_markdown(plan)
    assert "# Mission" in markdown
    assert markdown.endswith("\n")


def test_plan_mission_unknown_goal_yields_empty_plan(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    plan = plan_mission(storage, sample_repo, "zzqq nonexistent quantum widget")

    assert plan.dead_ends == []
    assert plan.blast_radius == []
    assert plan.pack.is_empty
    assert plan.is_empty
    # mission always derives at least one unit (falls back to the raw goal)
    assert plan.swarm_units == ["zzqq nonexistent quantum widget"]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_plan_mission_is_deterministic(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)
    _seed_dead_end(storage)

    first = render_mission_markdown(plan_mission(storage, sample_repo, "cache worker tests"))
    second = render_mission_markdown(plan_mission(storage, sample_repo, "cache worker tests"))
    assert first == second


# ---------------------------------------------------------------------------
# Execute mode: delegate to the shared harness
# ---------------------------------------------------------------------------


def test_run_mission_execute_delegates_to_harness(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)
    planned = HarnessController(sample_repo).run(
        RunRequest(task="fix cache invalidation", plan_only=True)
    )
    completed = replace(
        planned,
        status=HarnessStatus.COMPLETED,
        loop_converged=True,
        proof_complete=True,
        verified=True,
        stop_reason="converged",
    )
    seen: list[RunRequest] = []

    plan = run_mission(
        storage,
        sample_repo,
        "fix cache invalidation",
        execute=True,
        agent="codex",
        model="test-model",
        verifier="pytest -q",
        max_iterations=4,
        max_cost_usd=1.25,
        isolate=True,
        harness_runner=lambda request: (seen.append(request), completed)[1],
    )

    assert plan.execute is True
    assert plan.swarm is None
    assert plan.harness is not None
    assert plan.harness["status"] == "completed"
    assert plan.harness["verified"] is True
    assert plan.runtime_contract is not None
    assert plan.runtime_contract_digest == planned.plan.to_run_spec().digest
    assert len(seen) == 1
    request = seen[0]
    assert request.execute is True
    assert request.agent == "codex"
    assert request.model == "test-model"
    assert request.verifier == "pytest -q"
    assert request.max_iterations == 4
    assert request.max_cost_usd == 1.25
    assert request.isolation is True
    assert {
        step.status for step in plan.steps if step.name in {"execute / verify / prove"}
    } == {"completed"}
    assert not (sample_repo / ".onmc" / "swarm").exists()


def test_run_mission_reports_learning_stage_independently(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)
    planned = HarnessController(sample_repo).run(
        RunRequest(task="fix cache invalidation", plan_only=True)
    )
    failed_with_learning = replace(
        planned,
        status=HarnessStatus.FAILED,
        stop_reason="verification-failed",
        stages=(
            StageRecord(
                name=StageName.LEARN_CANDIDATE,
                status=StageStatus.SUCCEEDED,
                summary="recorded failed approach as a quarantined candidate",
            ),
        ),
    )

    plan = run_mission(
        storage,
        sample_repo,
        "fix cache invalidation",
        execute=True,
        harness_runner=lambda _request: failed_with_learning,
    )

    statuses = {step.name: step.status for step in plan.steps}
    assert statuses["execute / verify / prove"] == "failed"
    assert statuses["learn candidate"] == "succeeded"


def test_run_mission_execute_false_exposes_runtime_contract(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    via_run = run_mission(
        storage,
        sample_repo,
        "cache worker",
        execute=False,
        agent="codex",
        verifier="pytest tests/cache",
    )
    via_plan = plan_mission(storage, sample_repo, "cache worker")

    assert via_run.execute is False
    assert via_run.harness is None
    assert via_run.runtime_contract is not None
    assert via_run.runtime_contract_digest
    assert via_run.runtime_contract["run_id"] != ""
    assert via_run.runtime_contract["task"] == "cache worker"
    assert via_run.runtime_contract != via_plan.runtime_contract
    rendered = render_mission_markdown(via_run)
    assert "## Runtime contract" in rendered
    assert "pytest tests/cache" in json.dumps(via_run.runtime_contract)


def test_mission_view_and_run_compile_equivalent_run_specs(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)
    request = RunRequest(
        task="cache worker",
        plan_only=True,
        agent="codex",
        model="gpt-test",
        verifier="pytest tests/cache",
        max_iterations=4,
        max_cost_usd=1.5,
        isolation=True,
        context_budget=2_000,
    )
    direct = HarnessController(sample_repo).run(request).plan.to_run_spec()
    mission = run_mission(
        storage,
        sample_repo,
        request.task,
        execute=False,
        agent=request.agent,
        model=request.model,
        verifier=request.verifier,
        max_iterations=request.max_iterations,
        max_cost_usd=request.max_cost_usd,
        isolate=request.isolation,
        context_budget=request.context_budget,
    )

    assert mission.runtime_contract is not None
    assert RunSpec.from_dict(mission.runtime_contract).to_dict() == direct.to_dict()
    assert mission.runtime_contract_digest == direct.digest


# ---------------------------------------------------------------------------
# CLI surface (auto-discovered command) — never assert Rich --help
# ---------------------------------------------------------------------------


def test_mission_cli_json_shape(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_repo)
    _storage(sample_repo)

    result = runner.invoke(app, ["mission", "fix cache invalidation", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["goal"] == "fix cache invalidation"
    assert payload["execute"] is False
    assert payload["swarm"] is None
    for key in ("dead_ends", "blast_radius", "swarm_units", "steps", "pack"):
        assert key in payload
    assert isinstance(payload["swarm_units"], list)
    assert payload["runtime_contract"] is not None
    assert payload["runtime_contract_digest"]


def test_mission_cli_markdown_plan_mode(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    _storage(sample_repo)

    result = runner.invoke(app, ["mission", "fix cache invalidation"])
    assert result.exit_code == 0, result.stdout
    assert "# Mission" in result.stdout
    assert "PLAN (dry-run, no agents)" in result.stdout


# ---------------------------------------------------------------------------
# Deliverable-based decomposition (greenfield) vs per-file (change-work)
# ---------------------------------------------------------------------------


def _no_dupe_goals(units: list[str]) -> None:
    """No two swarm unit goal strings may be byte-identical."""
    assert len(units) == len(set(units)), f"duplicate unit goals: {units}"


def test_plan_mission_greenfield_decomposes_by_deliverable(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    goal = (
        "Build new modules: (1) add a rate limiter under src/limiter/ "
        "(2) create a metrics exporter under src/metrics/"
    )
    plan = plan_mission(storage, sample_repo, goal)

    # exactly two DISTINCT deliverable units (no verify unit — greenfield path
    # derives purely from the named deliverables)
    deliverable_units = [u for u in plan.swarm_units if "deliverable:" in u]
    assert len(deliverable_units) == 2, plan.swarm_units
    assert any("rate limiter" in u for u in deliverable_units)
    assert any("metrics exporter" in u for u in deliverable_units)
    # NO two units share an identical goal string (the degenerate case we fixed)
    _no_dupe_goals(plan.swarm_units)


def test_plan_mission_greenfield_and_split_no_dupes(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    # " and " split path, two distinct deliverables, none of which exist in repo
    goal = "Add a new module src/alpha/ and build a new module src/beta/"
    plan = plan_mission(storage, sample_repo, goal)

    deliverable_units = [u for u in plan.swarm_units if "deliverable:" in u]
    assert len(deliverable_units) == 2, plan.swarm_units
    _no_dupe_goals(plan.swarm_units)


def test_plan_mission_change_work_scopes_per_file_and_dedupes(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    # a change-work goal against real, existing files (the cache module lives here)
    plan = plan_mission(storage, sample_repo, "fix cache invalidation bug")

    # per-file scoping is preserved (no deliverable units)
    assert any("focus on" in u for u in plan.swarm_units)
    assert not any("deliverable:" in u for u in plan.swarm_units)
    # capped and deduped — no runaway fan-out, no byte-identical goals
    assert len(plan.swarm_units) <= 13  # _SWARM_UNIT_LIMIT (12) + 1 verify unit
    _no_dupe_goals(plan.swarm_units)


def test_plan_mission_build_verb_on_existing_path_is_change_work(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    # A build/create verb ("Add") that names a REAL existing file must be treated
    # as change-work, not greenfield (Sourcery bug_risk: markers + existing path).
    plan = plan_mission(storage, sample_repo, "Add rate limiting to src/cache.py")

    assert not any("deliverable:" in u for u in plan.swarm_units), plan.swarm_units
    assert any("focus on" in u for u in plan.swarm_units)


def test_plan_mission_greenfield_fan_out_is_capped(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    # 15 distinct greenfield deliverables must not reintroduce runaway fan-out —
    # the greenfield path is capped just like change-work (Sourcery bug_risk).
    clauses = " ".join(f"({i}) build a new module src/mod{i}/" for i in range(1, 16))
    plan = plan_mission(storage, sample_repo, f"Build new modules: {clauses}")

    deliverable_units = [u for u in plan.swarm_units if "deliverable:" in u]
    assert 0 < len(deliverable_units) <= 12  # _SWARM_UNIT_LIMIT
    _no_dupe_goals(plan.swarm_units)


def test_mission_cli_execute_flag(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)
    base = plan_mission(storage, sample_repo, "fix cache invalidation")
    completed = replace(
        base,
        execute=True,
        harness={
            "status": "completed",
            "verified": True,
            "stop_reason": "converged",
            "plan": {"run_id": "run-test"},
        },
    )
    seen: list[dict[str, object]] = []

    def _fake_run_mission(*args: object, **kwargs: object) -> MissionPlan:
        seen.append(dict(kwargs))
        return completed

    monkeypatch.setattr(
        "oh_no_my_claudecode.mission.commands.run_mission",
        _fake_run_mission,
    )

    result = runner.invoke(
        app,
        [
            "mission",
            "fix cache invalidation",
            "--execute",
            "--agent",
            "codex",
            "--verifier",
            "pytest -q",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["execute"] is True
    assert payload["swarm"] is None
    assert payload["harness"]["status"] == "completed"
    assert seen[0]["execute"] is True
    assert seen[0]["agent"] == "codex"
    assert seen[0]["verifier"] == "pytest -q"
