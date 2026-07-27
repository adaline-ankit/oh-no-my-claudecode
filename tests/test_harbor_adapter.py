from __future__ import annotations

import importlib.util
import io
import json
import os
import runpy
import subprocess
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from oh_no_my_claudecode.experiment.contracts import (
    BenchmarkAuditStatus,
    Condition,
    Environment,
    ExperimentId,
    ExperimentManifest,
)
from oh_no_my_claudecode.experiment.harbor_adapter import (
    export_portfolio_to_harbor,
    harbor_task_payload,
    import_harbor_native_trial,
    import_harbor_results,
    import_harbor_smoke_outputs,
    import_harbor_trial,
    materialize_nop_smoke_trajectory,
    plan_harbor_smoke,
    run_harbor_smoke,
    validate_harbor_seed_manifest,
)
from oh_no_my_claudecode.experiment.harbor_repro import (
    DEFAULT_HARBOR_DOCKER_IMAGE,
    HARBOR_REQUIRED_ARTIFACTS,
    load_harbor_repro_manifest,
)
from oh_no_my_claudecode.experiment.portfolio import (
    PortfolioManifest,
    RepoRef,
    TaskKind,
    TaskSpec,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORT_SCRIPT_PATH = REPO_ROOT / "scripts" / "import_harbor_results.py"
EXPORT_SCRIPT_PATH = REPO_ROOT / "scripts" / "export_harbor_tasks.py"
RUN_SCRIPT_PATH = REPO_ROOT / "scripts" / "run_harbor_smoke.py"
PORTFOLIO_V4_PATH = REPO_ROOT / "datasets" / "experiment" / "portfolio_external_v4.json"
HARBOR_REPRO_PATH = REPO_ROOT / "benchmarks" / "onmc" / "harbor-repro-v1.json"
SHA_A = "a" * 64
SHA_B = "b" * 64


def _portfolio() -> PortfolioManifest:
    task = TaskSpec(
        task_id="cache-bugfix",
        repo=RepoRef(
            name="demo",
            url="https://github.com/example/demo.git",
            pinned_sha="abcdef1234567890",
        ),
        prompt="Fix cache invalidation. Do not edit tests.",
        verifier_argv=("python", "-m", "pytest", "-q", "tests/test_cache.py"),
        task_kind=TaskKind.BUGFIX,
        expected_outcome="cache tests pass without test edits",
    )
    experiment = ExperimentManifest(
        experiment_id=ExperimentId("harbor-smoke"),
        task_set_revision="harbor-v1",
        conditions=(Condition.BARE_AGENT, Condition.ONMC_CURRENT),
        trials=2,
        seed=7,
        environment=Environment(
            code_sha="abc1234",
            config_hash="cfg",
            model="claude-cli-default",
            provider="anthropic",
            image="docker",
        ),
        audit_status=BenchmarkAuditStatus.VALID,
        leakage_notes="fixture",
    )
    return PortfolioManifest(
        experiment=experiment,
        tasks=(task,),
        audit_status=BenchmarkAuditStatus.VALID,
        leakage_notes="fixture",
    )


def _harbor_trial() -> dict[str, object]:
    return {
        "task_id": "cache-bugfix",
        "condition": "onmc-current",
        "trial": 1,
        "reward": {"reward": 1.0, "passed": True},
        "trajectory": {
            "schema": "atif",
            "path": "traces/cache-bugfix.atif.json",
            "sha256": SHA_A,
            "media_type": "application/json",
            "size_bytes": 321,
        },
        "verifier": {
            "sha256": SHA_B,
            "media_type": "text/plain",
            "size_bytes": 123,
        },
        "metrics": {
            "cost_usd": 0.25,
            "latency_ms": 1200.0,
            "turns": 3,
            "tool_calls": 7,
            "context_tokens": 456,
            "interventions": 0,
        },
    }


def _native_harbor_trial() -> dict[str, object]:
    return {
        "task_name": "onmc/cache-bugfix",
        "trial_name": "cache-bugfix__abc123",
        "agent_info": {
            "name": "nop",
            "version": "1.0.0",
            "model_info": {"name": "local", "provider": None},
        },
        "agent_result": {
            "n_input_tokens": 11,
            "n_cache_tokens": None,
            "n_output_tokens": 7,
            "cost_usd": 0.02,
        },
        "verifier_result": {"rewards": {"reward": 1.0, "passed": 1.0}},
        "started_at": "2026-07-26T17:14:00.000000Z",
        "finished_at": "2026-07-26T17:14:10.500000Z",
    }


def _artifact_payload(data: bytes, media_type: str = "application/json") -> dict[str, object]:
    from oh_no_my_claudecode.experiment.contracts import ArtifactRef

    return ArtifactRef.of(data, media_type).to_dict()


def _write_native_smoke_trial(
    jobs_dir: Path,
    *,
    job_name: str,
    task_name: str,
    with_trajectory: bool = True,
) -> Path:
    trial_dir = jobs_dir / job_name / f"{task_name.rsplit('/', 1)[-1]}__abc123"
    (trial_dir / "agent").mkdir(parents=True)
    (trial_dir / "verifier").mkdir()
    result = _native_harbor_trial()
    result["task_name"] = task_name
    (trial_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (trial_dir / "config.json").write_text(
        json.dumps(
            {
                "agent": {"name": "nop", "model_name": "local"},
            }
        ),
        encoding="utf-8",
    )
    (trial_dir / "lock.json").write_text(
        json.dumps(
            {
                "agent": {"name": "nop", "model_name": "local"},
                "environment": {"type": "docker"},
            }
        ),
        encoding="utf-8",
    )
    (trial_dir / "verifier" / "reward.json").write_text(
        '{"reward":1.0,"passed":true}\n', encoding="utf-8"
    )
    (trial_dir / "verifier" / "test-stdout.txt").write_text("1 passed\n", encoding="utf-8")
    if with_trajectory:
        (trial_dir / "agent" / "trajectory.json").write_text(
            json.dumps(
                {
                    "schema_version": "ATIF-v1.7",
                    "session_id": "smoke-session",
                    "agent": {"name": "nop", "version": "1.0.0", "model_name": "local"},
                    "steps": [
                        {
                            "step_id": 1,
                            "source": "agent",
                            "message": "No-op smoke agent performed no actions.",
                            "llm_call_count": 0,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    return trial_dir


def _load_script(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_harbor_task_payload_preserves_onmc_task_contract() -> None:
    task = _portfolio().tasks[0]

    payload = harbor_task_payload(task)

    assert payload["schema_version"] == "onmc-harbor-task/v1"
    assert payload["task_id"] == "cache-bugfix"
    assert payload["verifier_argv"] == ["python", "-m", "pytest", "-q", "tests/test_cache.py"]
    assert payload["repo"] == task.repo.to_dict()


def test_export_portfolio_to_harbor_writes_task_directory(tmp_path: Path) -> None:
    summary = export_portfolio_to_harbor(_portfolio(), tmp_path)

    assert summary.task_count == 1
    task_dir = tmp_path / "onmc" / "cache-bugfix"
    assert (task_dir / "instruction.md").exists()
    assert (task_dir / "task.toml").exists()
    assert (task_dir / "environment" / "Dockerfile").exists()
    test_script = task_dir / "tests" / "test.sh"
    assert test_script.exists()
    assert test_script.stat().st_mode & 0o111
    assert "Fix cache invalidation" in (task_dir / "instruction.md").read_text(encoding="utf-8")
    dockerfile = (task_dir / "environment" / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith(f"FROM {DEFAULT_HARBOR_DOCKER_IMAGE}\n")
    assert "git clone https://github.com/example/demo.git /workspace" in dockerfile
    assert "git checkout abcdef1234567890" in dockerfile
    assert "tests/test_cache.py" in test_script.read_text(encoding="utf-8")
    metadata = json.loads((task_dir / "onmc-task.json").read_text(encoding="utf-8"))
    assert metadata["task_id"] == "cache-bugfix"
    dataset = json.loads((tmp_path / "onmc-harbor-dataset.json").read_text(encoding="utf-8"))
    assert dataset["schema_version"] == "onmc-harbor-dataset/v1"
    assert dataset["environment"] == {
        "provider": "docker",
        "image": DEFAULT_HARBOR_DOCKER_IMAGE,
    }
    assert dataset["tasks"] == [{"name": "onmc/cache-bugfix", "path": "onmc/cache-bugfix"}]


def test_export_portfolio_to_harbor_rejects_mutable_container_tag(tmp_path: Path) -> None:
    output = tmp_path / "harbor"
    with pytest.raises(ValueError, match="immutable sha256 digest"):
        export_portfolio_to_harbor(
            _portfolio(),
            output,
            container_image="python:3.12-slim",
        )
    assert not output.exists()


def test_checked_in_harbor_repro_manifest_binds_portfolio_and_evidence() -> None:
    manifest = load_harbor_repro_manifest(
        HARBOR_REPRO_PATH,
        repository_root=REPO_ROOT,
        portfolio_path=PORTFOLIO_V4_PATH,
    )

    assert manifest.docker_image == DEFAULT_HARBOR_DOCKER_IMAGE
    assert manifest.harbor_version == "0.20.0"
    assert manifest.payload["artifact_contract"]["required"] == [
        {"kind": kind, "path": path, "media_type": media_type}
        for kind, path, media_type in HARBOR_REQUIRED_ARTIFACTS
    ]
    assert manifest.leakage_boundary["publication_eligible"] is False
    assert manifest.leakage_boundary["independent_audit"] == "missing"


def test_export_portfolio_to_harbor_can_seed_text_regression(tmp_path: Path) -> None:
    summary = export_portfolio_to_harbor(
        _portfolio(),
        tmp_path,
        regression_hunks={
            "cache-bugfix": (("src/cache.py", "return fresh", "return stale  # REGRESSION"),),
        },
    )

    assert summary.task_count == 1
    env_dir = tmp_path / "onmc" / "cache-bugfix" / "environment"
    dockerfile = (env_dir / "Dockerfile").read_text(encoding="utf-8")
    seed_script = (env_dir / "onmc_seed.py").read_text(encoding="utf-8")
    assert "COPY onmc_seed.py /tmp/onmc_seed.py" in dockerfile
    assert "regression anchor not found" in seed_script
    assert "return fresh" in seed_script
    assert "return stale  # REGRESSION" in seed_script
    assert "git commit --quiet --all -m 'seed regression: cache-bugfix'" in dockerfile


def test_export_portfolio_to_harbor_can_seed_removals_planted_files_and_deps(
    tmp_path: Path,
) -> None:
    export_portfolio_to_harbor(
        _portfolio(),
        tmp_path,
        removals={"cache-bugfix": (("src/cache.py", "Cache.refresh"),)},
        planted_files={"cache-bugfix": (("tests/test_structure.py", "def test_shape(): pass\n"),)},
        test_deps={"demo": ("hypothesis",)},
    )

    env_dir = tmp_path / "onmc" / "cache-bugfix" / "environment"
    dockerfile = (env_dir / "Dockerfile").read_text(encoding="utf-8")
    seed_script = (env_dir / "onmc_seed.py").read_text(encoding="utf-8")
    assert "pytest hypothesis" in dockerfile
    assert "Cache.refresh" in seed_script
    assert "tests/test_structure.py" in seed_script
    assert "def test_shape(): pass" in seed_script


def test_generated_seed_script_applies_all_seed_material(tmp_path: Path) -> None:
    export_portfolio_to_harbor(
        _portfolio(),
        tmp_path,
        regression_hunks={
            "cache-bugfix": (("src/cache.py", "return fresh", "return stale  # REGRESSION"),),
        },
        removals={"cache-bugfix": (("src/cache.py", "Cache.refresh"),)},
        planted_files={"cache-bugfix": (("tests/test_structure.py", "def test_shape(): pass\n"),)},
    )
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "cache.py").write_text(
        "def value():\n"
        "    return fresh\n"
        "\n"
        "class Cache:\n"
        "    def refresh(self):\n"
        "        return fresh\n",
        encoding="utf-8",
    )

    script = tmp_path / "onmc" / "cache-bugfix" / "environment" / "onmc_seed.py"
    old_cwd = Path.cwd()
    try:
        os.chdir(repo)
        runpy.run_path(str(script))
    finally:
        os.chdir(old_cwd)

    source = (repo / "src" / "cache.py").read_text(encoding="utf-8")
    assert "return stale  # REGRESSION" in source
    assert 'raise NotImplementedError("REMOVED")' in source
    assert (repo / "tests" / "test_structure.py").read_text(encoding="utf-8") == (
        "def test_shape(): pass\n"
    )


def test_export_portfolio_to_harbor_seed_regression_requires_supported_hunk(
    tmp_path: Path,
) -> None:
    output = tmp_path / "harbor"
    with pytest.raises(ValueError, match="no supported regression seed"):
        export_portfolio_to_harbor(_portfolio(), output, regression_hunks={})
    assert not output.exists()


def test_validate_harbor_seed_manifest_checks_full_coverage_before_export() -> None:
    portfolio = _portfolio()
    second = replace(portfolio.tasks[0], task_id="auth-bugfix")
    manifest = replace(portfolio, tasks=(*portfolio.tasks, second))

    validation = validate_harbor_seed_manifest(
        manifest,
        regression_hunks={"cache-bugfix": (("src/cache.py", "old", "new"),)},
        removals={"auth-bugfix": (("src/auth.py", "authenticate"),)},
        planted_files={},
        test_deps={"demo": ()},
    )

    assert validation.complete is True
    assert validation.task_count == 2
    assert validation.seeded_task_count == 2
    assert validation.seed_kinds == {
        "cache-bugfix": ("text-hunk",),
        "auth-bugfix": ("ast-removal",),
    }

    incomplete = validate_harbor_seed_manifest(
        manifest,
        regression_hunks={"cache-bugfix": (("src/cache.py", "old", "new"),)},
        removals={"unknown-task": (("src/auth.py", "authenticate"),)},
        planted_files={},
        test_deps={},
    )
    assert incomplete.complete is False
    assert incomplete.missing_seed_task_ids == ("auth-bugfix",)
    assert incomplete.unknown_seed_task_ids == ("unknown-task",)
    assert incomplete.missing_test_dependency_repos == ("demo",)


def test_plan_harbor_smoke_enforces_cell_budget(tmp_path: Path) -> None:
    plan = plan_harbor_smoke(
        ("onmc/cache-bugfix", "onmc/auth-bugfix"),
        output_root=tmp_path,
        trials=1,
        max_cells=4,
    )

    assert plan.budget_ready is True
    assert plan.total_cells == 4
    assert len(plan.commands) == 4
    assert plan.commands[0][:6] == (
        "harbor",
        "run",
        "--job-name",
        "onmc-smoke-onmc-cache-bugfix-bare-agent",
        "-p",
        str(tmp_path / "onmc/cache-bugfix"),
    )
    assert plan.commands[1][3] == "onmc-smoke-onmc-cache-bugfix-onmc-current"
    assert "--env" in plan.commands[0]
    assert "docker" in plan.commands[0]
    assert "--metadata" not in plan.commands[0]
    assert plan.claim_eligible is False
    assert "condition-label-only" in plan.limitations

    with pytest.raises(ValueError, match="exceeding max_cells"):
        plan_harbor_smoke(
            ("onmc/cache-bugfix", "onmc/auth-bugfix"),
            output_root=tmp_path,
            trials=2,
            max_cells=4,
        )


def test_plan_harbor_smoke_materializes_every_repeated_trial(tmp_path: Path) -> None:
    plan = plan_harbor_smoke(
        ("onmc/cache-bugfix", "onmc/auth-bugfix"),
        output_root=tmp_path,
        trials=2,
        max_cells=8,
    )

    assert plan.total_cells == 8
    assert len(plan.cells) == 8
    assert len(plan.commands) == 8
    assert plan.cells[0].trial == 0
    assert plan.cells[1].trial == 1
    assert plan.cells[0].job_name.endswith("-t0")
    assert plan.cells[1].job_name.endswith("-t1")
    assert plan.commands[0][-7:] == (
        "-n",
        "1",
        "-y",
        "--jobs-dir",
        str(plan.jobs_dir),
        "--max-retries",
        "0",
    )


def test_import_harbor_trial_requires_trajectory_and_verifier_artifacts() -> None:
    imported = import_harbor_trial(_harbor_trial(), experiment_id="harbor-smoke")

    assert imported.trial.run_id.slug == "harbor-smoke.onmc-current.cache-bugfix.t1"
    assert imported.trial.passed is True
    assert imported.trial.cost_usd == 0.25
    assert imported.trial.context_tokens == 456
    assert imported.trajectory.path == "traces/cache-bugfix.atif.json"
    assert imported.verifier.sha256 == SHA_B

    missing = dict(_harbor_trial())
    missing.pop("trajectory")
    with pytest.raises(ValueError, match="trial.trajectory"):
        import_harbor_trial(missing, experiment_id="harbor-smoke")


def test_import_harbor_results_normalizes_trials() -> None:
    bundle = {"trials": [_harbor_trial()]}

    imported = import_harbor_results(bundle, experiment_id="harbor-smoke")

    assert len(imported) == 1
    assert imported[0].trial.to_dict()["condition"] == "onmc-current"


def test_import_harbor_native_trial_requires_explicit_proof_artifacts() -> None:
    imported = import_harbor_native_trial(
        _native_harbor_trial(),
        experiment_id="harbor-smoke",
        condition=Condition.ONMC_CURRENT,
        task_id=None,
        trial=0,
        trajectory={
            "schema": "atif",
            "path": "traces/cache-bugfix.atif.json",
            **_artifact_payload(b'{"events":[]}'),
        },
        verifier=_artifact_payload(b'{"verifier_result":{"passed":1.0}}'),
    )

    assert imported.trial.run_id.slug == "harbor-smoke.onmc-current.cache-bugfix.t0"
    assert imported.trial.passed is True
    assert imported.trial.cost_usd == 0.02
    assert imported.trial.context_tokens == 18
    assert imported.trial.latency_ms == 10500.0

    with pytest.raises(ValueError, match="atif.path"):
        import_harbor_native_trial(
            _native_harbor_trial(),
            experiment_id="harbor-smoke",
            condition=Condition.ONMC_CURRENT,
            task_id="cache-bugfix",
            trial=0,
            trajectory={},
            verifier=_artifact_payload(b"{}"),
        )


def test_import_harbor_smoke_outputs_requires_complete_native_artifacts(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "jobs"
    plan = plan_harbor_smoke(
        ("onmc/cache-bugfix",),
        output_root=tmp_path / "tasks",
        conditions=(Condition.BARE_AGENT,),
        max_cells=1,
        jobs_dir=jobs_dir,
    )
    cell = plan.cells[0]
    trial_dir = _write_native_smoke_trial(
        jobs_dir,
        job_name=cell.job_name,
        task_name=cell.task_name,
    )

    imported = import_harbor_smoke_outputs(
        plan,
        experiment_id="harbor-smoke",
    )

    assert imported.complete is True
    assert imported.expected_cells == 1
    assert imported.imported_cells == 1
    assert imported.claim_eligible is False
    assert imported.trials[0].trial.run_id.slug == ("harbor-smoke.bare-agent.cache-bugfix.t0")
    assert len(imported.trials[0].trial.artifacts) == 6
    assert {artifact.kind for artifact in imported.trials[0].evidence} == {
        "trajectory",
        "verifier-reward",
        "verifier-stdout",
        "harbor-result",
        "harbor-config",
        "harbor-lock",
    }

    (trial_dir / "verifier" / "test-stdout.txt").unlink()
    with pytest.raises(ValueError, match="verifier/test-stdout.txt"):
        import_harbor_smoke_outputs(plan, experiment_id="harbor-smoke")
    (trial_dir / "verifier" / "test-stdout.txt").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact is empty"):
        import_harbor_smoke_outputs(plan, experiment_id="harbor-smoke")


def test_import_harbor_smoke_outputs_fails_closed_before_partial_import(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "jobs"
    plan = plan_harbor_smoke(
        ("onmc/cache-bugfix", "onmc/auth-bugfix"),
        output_root=tmp_path / "tasks",
        conditions=(Condition.BARE_AGENT,),
        max_cells=2,
        jobs_dir=jobs_dir,
    )
    _write_native_smoke_trial(
        jobs_dir,
        job_name=plan.cells[0].job_name,
        task_name=plan.cells[0].task_name,
    )
    _write_native_smoke_trial(
        jobs_dir,
        job_name=plan.cells[1].job_name,
        task_name=plan.cells[1].task_name,
        with_trajectory=False,
    )

    with pytest.raises(ValueError, match="agent/trajectory.json"):
        import_harbor_smoke_outputs(plan, experiment_id="harbor-smoke")


def test_materialize_nop_smoke_trajectory_is_explicitly_non_claimable(
    tmp_path: Path,
) -> None:
    trial_dir = _write_native_smoke_trial(
        tmp_path,
        job_name="job",
        task_name="onmc/cache-bugfix",
        with_trajectory=False,
    )

    trajectory = materialize_nop_smoke_trajectory(trial_dir)
    payload = json.loads(trajectory.read_text(encoding="utf-8"))

    assert payload["agent"]["name"] == "nop"
    assert payload["agent"]["extra"]["onmc_claim_eligible"] is False
    assert payload["steps"][0]["llm_call_count"] == 0
    assert payload["steps"][0]["extra"]["onmc_generated_nop_sentinel"] is True


def test_run_harbor_smoke_executes_and_imports_all_cells(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs_dir = tmp_path / "jobs"
    plan = plan_harbor_smoke(
        ("onmc/cache-bugfix",),
        output_root=tmp_path / "tasks",
        conditions=(Condition.BARE_AGENT,),
        max_cells=1,
        jobs_dir=jobs_dir,
    )
    seen: list[tuple[str, ...]] = []

    def fake_run(command: tuple[str, ...], *, check: bool) -> subprocess.CompletedProcess[str]:
        assert check is False
        seen.append(command)
        cell = plan.cells[0]
        _write_native_smoke_trial(
            jobs_dir,
            job_name=cell.job_name,
            task_name=cell.task_name,
            with_trajectory=False,
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(
        "oh_no_my_claudecode.experiment.harbor_adapter.subprocess.run",
        fake_run,
    )

    imported = run_harbor_smoke(plan, experiment_id="harbor-smoke")

    assert seen == [plan.commands[0]]
    assert imported.complete is True
    trajectory = jobs_dir / plan.cells[0].job_name
    assert list(trajectory.glob("*/agent/trajectory.json"))


def test_run_harbor_smoke_refuses_model_backed_agents(tmp_path: Path) -> None:
    plan = plan_harbor_smoke(
        ("onmc/cache-bugfix",),
        output_root=tmp_path / "tasks",
        conditions=(Condition.BARE_AGENT,),
        max_cells=1,
        agent="codex",
        model="gpt-5",
    )

    with pytest.raises(ValueError, match="separately approved workflow"):
        run_harbor_smoke(plan, experiment_id="harbor-smoke")


def test_import_harbor_results_script_writes_normalized_json(tmp_path: Path) -> None:
    script = _load_script(IMPORT_SCRIPT_PATH, "_import_harbor_results_under_test")
    bundle = tmp_path / "harbor-results.json"
    out = tmp_path / "onmc-import.json"
    bundle.write_text(json.dumps({"trials": [_harbor_trial()]}), encoding="utf-8")

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = script.main([str(bundle), "--experiment-id", "harbor-smoke", "--out", str(out)])

    assert exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload == json.loads(stdout.getvalue())
    assert payload["schema_version"] == "onmc-harbor-import/v1"
    assert payload["source_format"] == "onmc-bundle"
    assert payload["trial_count"] == 1
    assert payload["trials"][0]["trial"]["run_id"] == ("harbor-smoke.onmc-current.cache-bugfix.t1")


def test_import_harbor_results_script_imports_native_trial_json(tmp_path: Path) -> None:
    script = _load_script(IMPORT_SCRIPT_PATH, "_import_harbor_native_under_test")
    native = tmp_path / "result.json"
    trajectory = tmp_path / "trajectory.atif.json"
    verifier = tmp_path / "verifier.json"
    out = tmp_path / "onmc-import.json"
    native.write_text(json.dumps(_native_harbor_trial()), encoding="utf-8")
    trajectory.write_text('{"schema":"atif","events":[]}', encoding="utf-8")
    verifier.write_text('{"verifier_result":{"passed":1.0}}', encoding="utf-8")

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = script.main(
            [
                str(native),
                "--native-trial",
                "--experiment-id",
                "harbor-smoke",
                "--condition",
                "onmc-current",
                "--trial",
                "0",
                "--trajectory-file",
                str(trajectory),
                "--verifier-file",
                str(verifier),
                "--out",
                str(out),
            ]
        )

    assert exit_code == 0
    payload = json.loads(stdout.getvalue())
    assert payload == json.loads(out.read_text(encoding="utf-8"))
    assert payload["source_format"] == "harbor-native-trial"
    assert payload["trials"][0]["trial"]["run_id"] == ("harbor-smoke.onmc-current.cache-bugfix.t0")
    assert payload["trials"][0]["trial"]["context_tokens"] == 18


def test_export_harbor_tasks_script_writes_bundle_and_smoke_plan(tmp_path: Path) -> None:
    script = _load_script(EXPORT_SCRIPT_PATH, "_export_harbor_tasks_under_test")
    manifest = tmp_path / "portfolio.json"
    out = tmp_path / "harbor"
    manifest.write_text(_portfolio().to_json(), encoding="utf-8")

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = script.main(
            [
                str(manifest),
                "--out",
                str(out),
                "--limit-tasks",
                "1",
                "--smoke-plan",
                "--max-cells",
                "2",
            ]
        )

    assert exit_code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "onmc-harbor-export/v1"
    assert payload["export"]["task_count"] == 1
    assert payload["smoke_plan"]["total_cells"] == 2
    assert payload["smoke_plan"]["budget_ready"] is True
    assert (out / "onmc" / "cache-bugfix" / "task.toml").exists()


def test_run_harbor_smoke_script_validates_full_manifest_before_dry_run(
    tmp_path: Path,
) -> None:
    script = _load_script(RUN_SCRIPT_PATH, "_run_harbor_smoke_under_test")
    out = tmp_path / "tasks"
    jobs = tmp_path / "jobs"
    receipt = tmp_path / "receipt.json"

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = script.main(
            [
                str(PORTFOLIO_V4_PATH),
                "--out",
                str(out),
                "--jobs-dir",
                str(jobs),
                "--receipt",
                str(receipt),
                "--task-id",
                "six-bugfix-integer-types",
                "--task-id",
                "jmespath-refactor-dedup-key-func",
                "--condition",
                "bare-agent",
                "--max-cells",
                "2",
            ]
        )

    assert exit_code == 0
    payload = json.loads(stdout.getvalue())
    assert payload == json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["executed"] is False
    assert payload["reproduction"]["execution"]["harbor_version"] == "0.20.0"
    assert (
        payload["reproduction"]["execution"]["docker"]["image"]
        + "@"
        + payload["reproduction"]["execution"]["docker"]["digest"]
        == DEFAULT_HARBOR_DOCKER_IMAGE
    )
    assert payload["reproduction"]["artifact_contract"]["required"] == [
        {"kind": kind, "path": path, "media_type": media_type}
        for kind, path, media_type in HARBOR_REQUIRED_ARTIFACTS
    ]
    assert payload["reproduction"]["leakage_boundary"]["independent_audit"] == "missing"
    assert payload["full_seed_validation"]["complete"] is True
    assert payload["full_seed_validation"]["task_count"] == 28
    assert payload["full_seed_validation"]["seeded_task_count"] == 28
    assert payload["full_seed_validation"]["seed_kinds"]["six-bugfix-integer-types"] == [
        "text-hunk"
    ]
    assert payload["full_seed_validation"]["seed_kinds"]["jmespath-refactor-dedup-key-func"] == [
        "text-hunk",
        "planted-structural-grader",
    ]
    assert payload["claim_eligible"] is False
    assert "condition-label-only" in payload["limitations"]
    dockerfile = (
        out / "onmc" / "jmespath-refactor-dedup-key-func" / "environment" / "Dockerfile"
    ).read_text(encoding="utf-8")
    assert dockerfile.startswith(f"FROM {DEFAULT_HARBOR_DOCKER_IMAGE}\n")
    assert jobs.exists() is False


def test_run_harbor_smoke_script_rejects_harbor_version_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _load_script(RUN_SCRIPT_PATH, "_run_harbor_version_under_test")
    repro = load_harbor_repro_manifest(
        HARBOR_REPRO_PATH,
        repository_root=REPO_ROOT,
        portfolio_path=PORTFOLIO_V4_PATH,
    )
    monkeypatch.setattr(
        script.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout="0.21.0\n",
        ),
    )

    with pytest.raises(ValueError, match="expected 0.20.0, got 0.21.0"):
        script._verify_harbor_version(repro)
