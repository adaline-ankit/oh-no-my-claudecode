from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
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
    import_harbor_results,
    import_harbor_trial,
)
from oh_no_my_claudecode.experiment.portfolio import (
    PortfolioManifest,
    RepoRef,
    TaskKind,
    TaskSpec,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "import_harbor_results.py"
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


def _load_script() -> ModuleType:
    module_name = "_import_harbor_results_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
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
    assert "tests/test_cache.py" in test_script.read_text(encoding="utf-8")
    metadata = json.loads((task_dir / "onmc-task.json").read_text(encoding="utf-8"))
    assert metadata["task_id"] == "cache-bugfix"
    dataset = json.loads((tmp_path / "onmc-harbor-dataset.json").read_text(encoding="utf-8"))
    assert dataset["schema_version"] == "onmc-harbor-dataset/v1"
    assert dataset["tasks"] == [{"name": "onmc/cache-bugfix", "path": "onmc/cache-bugfix"}]


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


def test_import_harbor_results_script_writes_normalized_json(tmp_path: Path) -> None:
    script = _load_script()
    bundle = tmp_path / "harbor-results.json"
    out = tmp_path / "onmc-import.json"
    bundle.write_text(json.dumps({"trials": [_harbor_trial()]}), encoding="utf-8")

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exit_code = script.main(
            [str(bundle), "--experiment-id", "harbor-smoke", "--out", str(out)]
        )

    assert exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload == json.loads(stdout.getvalue())
    assert payload["schema_version"] == "onmc-harbor-import/v1"
    assert payload["trial_count"] == 1
    assert payload["trials"][0]["trial"]["run_id"] == (
        "harbor-smoke.onmc-current.cache-bugfix.t1"
    )
