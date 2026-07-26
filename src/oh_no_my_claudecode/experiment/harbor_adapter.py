"""Harbor adapter for ONMC external experiment manifests.

Harbor is an execution layer. ONMC keeps the canonical task, result, evidence,
and claim schemas here and translates at the boundary.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from oh_no_my_claudecode.experiment.atif import AtifArtifact, atif_artifact_from_mapping
from oh_no_my_claudecode.experiment.contracts import (
    ArtifactRef,
    Condition,
    MetricLabel,
    RunId,
    TrialResult,
)
from oh_no_my_claudecode.experiment.portfolio import PortfolioManifest, TaskSpec

__all__ = [
    "HarborExportSummary",
    "HarborSmokePlan",
    "HarborTrialImport",
    "export_portfolio_to_harbor",
    "harbor_task_payload",
    "import_harbor_results",
    "import_harbor_trial",
    "plan_harbor_smoke",
]


@dataclass(frozen=True, slots=True)
class HarborExportSummary:
    """Summary of exported Harbor task directories."""

    root: Path
    task_count: int
    task_names: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "task_count": self.task_count,
            "task_names": list(self.task_names),
        }


@dataclass(frozen=True, slots=True)
class HarborSmokePlan:
    """A bounded local Harbor smoke plan before any paid/cloud benchmark."""

    task_names: tuple[str, ...]
    conditions: tuple[str, ...]
    trials: int
    total_cells: int
    max_cells: int
    commands: tuple[tuple[str, ...], ...]

    @property
    def budget_ready(self) -> bool:
        return self.total_cells <= self.max_cells

    def to_dict(self) -> dict[str, object]:
        return {
            "task_names": list(self.task_names),
            "conditions": list(self.conditions),
            "trials": self.trials,
            "total_cells": self.total_cells,
            "max_cells": self.max_cells,
            "budget_ready": self.budget_ready,
            "commands": [list(command) for command in self.commands],
        }


@dataclass(frozen=True, slots=True)
class HarborTrialImport:
    """One imported Harbor trial plus required trajectory evidence."""

    trial: TrialResult
    trajectory: AtifArtifact
    verifier: ArtifactRef

    def to_dict(self) -> dict[str, object]:
        return {
            "trial": self.trial.to_dict(),
            "trajectory": self.trajectory.to_dict(),
            "verifier": self.verifier.to_dict(),
        }


def harbor_task_payload(task: TaskSpec) -> dict[str, object]:
    """Return the ONMC metadata embedded in one Harbor task."""

    return {
        "schema_version": "onmc-harbor-task/v1",
        "task_id": task.task_id,
        "repo": task.repo.to_dict(),
        "task_kind": task.task_kind.value,
        "verifier_argv": list(task.verifier_argv),
        "expected_outcome": task.expected_outcome,
    }


def export_portfolio_to_harbor(
    manifest: PortfolioManifest,
    output_root: Path,
) -> HarborExportSummary:
    """Write Harbor task directories for every ONMC portfolio task."""

    task_names: list[str] = []
    manifest_tasks: list[dict[str, str]] = []
    output_root.mkdir(parents=True, exist_ok=True)
    dataset_manifest = {
        "schema_version": "onmc-harbor-dataset/v1",
        "experiment": manifest.experiment.to_dict(),
        "audit_status": manifest.audit_status.value,
        "task_set_revision": manifest.experiment.task_set_revision,
        "tasks": manifest_tasks,
    }
    for task in manifest.tasks:
        task_name = _harbor_task_name(task)
        task_names.append(task_name)
        task_dir = output_root / task_name
        (task_dir / "environment").mkdir(parents=True, exist_ok=True)
        (task_dir / "tests").mkdir(parents=True, exist_ok=True)
        (task_dir / "instruction.md").write_text(_instruction(task), encoding="utf-8")
        (task_dir / "task.toml").write_text(_task_toml(task, task_name), encoding="utf-8")
        (task_dir / "environment" / "Dockerfile").write_text(_dockerfile(), encoding="utf-8")
        test_script = task_dir / "tests" / "test.sh"
        test_script.write_text(_test_script(task), encoding="utf-8")
        test_script.chmod(0o755)
        (task_dir / "onmc-task.json").write_text(
            json.dumps(harbor_task_payload(task), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_tasks.append({"name": task_name, "path": task_name})
    (output_root / "onmc-harbor-dataset.json").write_text(
        json.dumps(dataset_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return HarborExportSummary(
        root=output_root,
        task_count=len(task_names),
        task_names=tuple(task_names),
    )


def plan_harbor_smoke(
    task_names: Sequence[str],
    *,
    output_root: Path,
    conditions: Sequence[Condition] = (Condition.BARE_AGENT, Condition.ONMC_CURRENT),
    trials: int = 1,
    max_cells: int = 4,
    agent: str = "oracle",
    model: str = "local",
) -> HarborSmokePlan:
    """Build a no-cloud Harbor Docker smoke plan and enforce a hard cell budget."""

    if not task_names:
        raise ValueError("smoke plan needs at least one task")
    if trials < 1:
        raise ValueError("trials must be positive")
    if max_cells < 1:
        raise ValueError("max_cells must be positive")
    if not agent.strip():
        raise ValueError("agent must not be empty")
    if not model.strip():
        raise ValueError("model must not be empty")
    condition_values = tuple(condition.value for condition in conditions)
    total_cells = len(task_names) * len(condition_values) * trials
    if total_cells > max_cells:
        raise ValueError(
            f"harbor smoke has {total_cells} cell(s), exceeding max_cells={max_cells}"
        )
    commands: list[tuple[str, ...]] = []
    for task_name in task_names:
        task_path = output_root / task_name
        for condition in condition_values:
            commands.append(
                (
                    "harbor",
                    "run",
                    "-p",
                    str(task_path),
                    "-a",
                    agent,
                    "-m",
                    model,
                    "--env",
                    "docker",
                    "--metadata",
                    f"onmc_condition={condition}",
                )
            )
    return HarborSmokePlan(
        task_names=tuple(task_names),
        conditions=condition_values,
        trials=trials,
        total_cells=total_cells,
        max_cells=max_cells,
        commands=tuple(commands),
    )


def import_harbor_results(
    payload: Mapping[str, object],
    *,
    experiment_id: str,
) -> tuple[HarborTrialImport, ...]:
    """Import a Harbor result bundle into ONMC trial results."""

    trials = payload.get("trials")
    if not isinstance(trials, list):
        raise ValueError("harbor results must contain a trials list")
    return tuple(
        import_harbor_trial(_mapping(item, "trial"), experiment_id=experiment_id)
        for item in trials
    )


def import_harbor_trial(
    data: Mapping[str, object],
    *,
    experiment_id: str,
) -> HarborTrialImport:
    """Validate and normalize one Harbor trial output."""

    reward = _mapping(data.get("reward"), "trial.reward")
    passed = _reward_passed(reward)
    trajectory = atif_artifact_from_mapping(_mapping(data.get("trajectory"), "trial.trajectory"))
    verifier = _artifact_ref(_mapping(data.get("verifier"), "trial.verifier"), "trial.verifier")
    metrics = _mapping(data.get("metrics", {}), "trial.metrics")
    run_id = RunId(
        experiment_id=experiment_id,
        condition=Condition(_string(data.get("condition"), "trial.condition")),
        task_id=_string(data.get("task_id"), "trial.task_id"),
        trial=_integer(data.get("trial"), "trial.trial"),
    )
    return HarborTrialImport(
        trial=TrialResult(
            run_id=run_id,
            passed=passed,
            metric_label=MetricLabel.MEASURED,
            cost_usd=_number(metrics.get("cost_usd", 0.0), "trial.metrics.cost_usd"),
            latency_ms=_number(metrics.get("latency_ms", 0.0), "trial.metrics.latency_ms"),
            turns=_integer(metrics.get("turns", 0), "trial.metrics.turns"),
            tool_calls=_integer(metrics.get("tool_calls", 0), "trial.metrics.tool_calls"),
            context_tokens=_integer(
                metrics.get("context_tokens", 0),
                "trial.metrics.context_tokens",
            ),
            interventions=_integer(metrics.get("interventions", 0), "trial.metrics.interventions"),
            artifacts=(trajectory.ref, verifier),
        ),
        trajectory=trajectory,
        verifier=verifier,
    )


def _harbor_task_name(task: TaskSpec) -> str:
    return f"onmc/{task.task_id}"


def _instruction(task: TaskSpec) -> str:
    return (
        f"{task.prompt}\n\n"
        "Repository under test:\n"
        f"- name: {task.repo.name}\n"
        f"- url: {task.repo.url}\n"
        f"- pinned_sha: {task.repo.pinned_sha}\n\n"
        "Do not edit, delete, narrow, or skip verifier tests.\n"
    )


def _task_toml(task: TaskSpec, task_name: str) -> str:
    keywords = json.dumps(["onmc", task.task_kind.value])
    metadata = json.dumps(harbor_task_payload(task), sort_keys=True)
    return "\n".join(
        (
            'schema_version = "1.3"',
            "",
            "[task]",
            f"name = {_toml_string(task_name)}",
            f"description = {_toml_string(task.expected_outcome)}",
            f"keywords = {keywords}",
            "",
            "[metadata]",
            f"onmc = {_toml_multiline_string(metadata)}",
            "",
            "[environment]",
            'dockerfile = "environment/Dockerfile"',
            "",
        )
    )


def _dockerfile() -> str:
    return "\n".join(
        (
            "FROM python:3.12-slim",
            "RUN python -m pip install --no-cache-dir pytest",
            "WORKDIR /workspace",
            "",
        )
    )


def _test_script(task: TaskSpec) -> str:
    verifier = shlex.join(task.verifier_argv)
    return "\n".join(
        (
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "mkdir -p /logs/verifier",
            f"if {verifier}; then",
            "  printf '{\"reward\":1.0,\"passed\":true}\\n' > /logs/verifier/reward.json",
            "  printf '1.0\\n' > /logs/verifier/reward.txt",
            "else",
            "  printf '{\"reward\":0.0,\"passed\":false}\\n' > /logs/verifier/reward.json",
            "  printf '0.0\\n' > /logs/verifier/reward.txt",
            "  exit 1",
            "fi",
            "",
        )
    )


def _reward_passed(reward: Mapping[str, object]) -> bool:
    raw_passed = reward.get("passed")
    raw_reward = reward.get("reward")
    if isinstance(raw_passed, bool):
        return raw_passed
    if isinstance(raw_reward, (int, float)) and not isinstance(raw_reward, bool):
        return raw_reward > 0
    raise ValueError("trial.reward must include passed bool or numeric reward")


def _artifact_ref(data: Mapping[str, object], name: str) -> ArtifactRef:
    return ArtifactRef(
        sha256=_string(data.get("sha256"), f"{name}.sha256"),
        media_type=_string(data.get("media_type", "text/plain"), f"{name}.media_type"),
        size_bytes=_integer(data.get("size_bytes"), f"{name}.size_bytes"),
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _number(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return float(value)


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_multiline_string(value: str) -> str:
    return '"""' + value.replace('"""', '\\"\\"\\"') + '"""'
