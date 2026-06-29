"""Tests for the ``mission`` feature — the keystone pipeline composer.

Covers :func:`oh_no_my_claudecode.mission.pipeline.plan_mission` /
:func:`~oh_no_my_claudecode.mission.pipeline.run_mission` and the auto-discovered
``onmc mission`` command:

- ``plan_mission`` composes a context pack + dead-ends + blast radius + swarm
  units for a seeded brain;
- a fresh (empty) brain yields a valid, non-crashing plan;
- the plan is deterministic across repeated builds;
- the default is plan-only — NO agent spawned, NO swarm manifest written;
- ``run_mission(execute=True)`` materialises a swarm manifest but spawns nothing;
- the ``--json`` CLI surface has the expected shape;
- CLI flags (``--execute``, ``--json``) are exercised (never ``--help``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode import init
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.mission.pipeline import (
    plan_mission,
    render_mission_markdown,
    run_mission,
)
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.models.memory import MemoryEntry
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
        "plan swarm",
        "summary",
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
    # the swarm step is "planned", not "queued"
    swarm_step = next(s for s in plan.steps if s.name == "plan swarm")
    assert swarm_step.status == "planned"


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
# Execute mode: materialise the swarm manifest, spawn nothing
# ---------------------------------------------------------------------------


def test_run_mission_execute_allocates_swarm_but_spawns_nothing(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    plan = run_mission(
        storage,
        sample_repo,
        "fix cache invalidation",
        execute=True,
        swarm_id="deadbeefdeadbeef",
    )

    assert plan.execute is True
    assert plan.swarm is not None
    assert plan.swarm["swarm_id"] == "deadbeefdeadbeef"
    assert plan.swarm["mode"] == "inline"
    # the manifest was written...
    manifest_path = Path(plan.swarm["manifest_path"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # ...with every unit PENDING — no agent was spawned, none ran
    statuses = {u["status"] for u in manifest["units"].values()}
    assert statuses == {"pending"}
    # the swarm step is queued under execute
    swarm_step = next(s for s in plan.steps if s.name == "plan swarm")
    assert swarm_step.status == "queued"


def test_run_mission_execute_false_matches_plan_mission(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    storage = _storage(sample_repo)

    via_run = render_mission_markdown(
        run_mission(storage, sample_repo, "cache worker", execute=False)
    )
    via_plan = render_mission_markdown(plan_mission(storage, sample_repo, "cache worker"))
    assert via_run == via_plan


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


def test_mission_cli_markdown_plan_mode(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sample_repo)
    _storage(sample_repo)

    result = runner.invoke(app, ["mission", "fix cache invalidation"])
    assert result.exit_code == 0, result.stdout
    assert "# Mission" in result.stdout
    assert "PLAN (dry-run, no agents)" in result.stdout


def test_mission_cli_execute_flag(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(sample_repo)
    _storage(sample_repo)

    result = runner.invoke(
        app, ["mission", "fix cache invalidation", "--execute", "--json"]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["execute"] is True
    assert payload["swarm"] is not None
    assert payload["swarm"]["mode"] == "inline"
