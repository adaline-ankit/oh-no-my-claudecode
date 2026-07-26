"""Harbor adapter for ONMC external experiment manifests.

Harbor is an execution layer. ONMC keeps the canonical task, result, evidence,
and claim schemas here and translates at the boundary.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
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

RegressionHunk = tuple[str, str, str]
RemovalSpec = tuple[str, str]
PlantedFile = tuple[str, str]

__all__ = [
    "HarborExportSummary",
    "HarborSmokePlan",
    "HarborTrialImport",
    "export_portfolio_to_harbor",
    "harbor_task_payload",
    "import_harbor_results",
    "import_harbor_native_trial",
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
    *,
    regression_hunks: Mapping[str, Sequence[RegressionHunk]] | None = None,
    removals: Mapping[str, Sequence[RemovalSpec]] | None = None,
    planted_files: Mapping[str, Sequence[PlantedFile]] | None = None,
    test_deps: Mapping[str, Sequence[str]] | None = None,
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
        hunks, task_removals, task_planted = _task_seed_material(
            task,
            regression_hunks=regression_hunks,
            removals=removals,
            planted_files=planted_files,
        )
        deps = tuple(test_deps.get(task.repo.name, ())) if test_deps is not None else ()
        task_name = _harbor_task_name(task)
        task_names.append(task_name)
        task_dir = output_root / task_name
        (task_dir / "environment").mkdir(parents=True, exist_ok=True)
        (task_dir / "tests").mkdir(parents=True, exist_ok=True)
        (task_dir / "instruction.md").write_text(_instruction(task), encoding="utf-8")
        (task_dir / "task.toml").write_text(_task_toml(task, task_name), encoding="utf-8")
        has_seed = bool(hunks or task_removals or task_planted)
        (task_dir / "environment" / "Dockerfile").write_text(
            _dockerfile(task, has_seed=has_seed, test_deps=deps),
            encoding="utf-8",
        )
        seed_script = _seed_script(hunks, task_removals, task_planted)
        if seed_script is not None:
            (task_dir / "environment" / "onmc_seed.py").write_text(seed_script, encoding="utf-8")
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
    agent: str = "nop",
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
                    "--job-name",
                    _smoke_job_name(task_name, condition),
                    "-p",
                    str(task_path),
                    "-a",
                    agent,
                    "-m",
                    model,
                    "--env",
                    "docker",
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


def import_harbor_native_trial(
    data: Mapping[str, object],
    *,
    experiment_id: str,
    condition: Condition,
    task_id: str | None,
    trial: int,
    trajectory: Mapping[str, object],
    verifier: Mapping[str, object],
) -> HarborTrialImport:
    """Import one Harbor per-trial ``result.json`` with explicit proof artifacts.

    Harbor's native result file contains reward, timing, and agent usage, but it
    does not always contain an ATIF trajectory or standalone verifier artifact.
    ONMC therefore requires callers to provide content-addressed proof pointers
    before converting a native Harbor result into a claimable ``TrialResult``.
    """

    verifier_result = _mapping(data.get("verifier_result"), "harbor.verifier_result")
    rewards = _mapping(verifier_result.get("rewards"), "harbor.verifier_result.rewards")
    agent_result = _mapping(data.get("agent_result", {}), "harbor.agent_result")
    atif = atif_artifact_from_mapping(trajectory)
    verifier_ref = _artifact_ref(verifier, "harbor.verifier")
    resolved_task_id = task_id or _native_task_id(data)
    return HarborTrialImport(
        trial=TrialResult(
            run_id=RunId(
                experiment_id=experiment_id,
                condition=condition,
                task_id=resolved_task_id,
                trial=trial,
            ),
            passed=_reward_passed(rewards),
            metric_label=MetricLabel.MEASURED,
            cost_usd=_optional_number(agent_result.get("cost_usd"), "harbor.agent_result.cost_usd"),
            latency_ms=_native_latency_ms(data),
            turns=0,
            tool_calls=0,
            context_tokens=_native_context_tokens(agent_result),
            interventions=0,
            artifacts=(atif.ref, verifier_ref),
        ),
        trajectory=atif,
        verifier=verifier_ref,
    )


def _harbor_task_name(task: TaskSpec) -> str:
    return f"onmc/{task.task_id}"


def _smoke_job_name(task_name: str, condition: str) -> str:
    raw = f"onmc-smoke-{task_name}-{condition}"
    return "".join(char if char.isalnum() or char in "-_." else "-" for char in raw)


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


def _dockerfile(
    task: TaskSpec,
    *,
    has_seed: bool = False,
    test_deps: Sequence[str] = (),
) -> str:
    repo_url = _docker_shell_string(task.repo.url)
    pinned_sha = _docker_shell_string(task.repo.pinned_sha)
    pip_packages = ("pytest", *test_deps)
    lines = [
        "FROM python:3.12-slim",
        "RUN apt-get update \\",
        "    && apt-get install -y --no-install-recommends git \\",
        "    && rm -rf /var/lib/apt/lists/*",
        "RUN python -m pip install --no-cache-dir "
        + " ".join(map(_docker_shell_string, pip_packages)),
        "WORKDIR /workspace",
        f"RUN git clone {repo_url} /workspace \\",
        f"    && git checkout {pinned_sha}",
        *_seed_docker_lines(task, has_seed),
        "",
    ]
    return "\n".join(lines)


def _task_seed_material(
    task: TaskSpec,
    *,
    regression_hunks: Mapping[str, Sequence[RegressionHunk]] | None,
    removals: Mapping[str, Sequence[RemovalSpec]] | None,
    planted_files: Mapping[str, Sequence[PlantedFile]] | None,
) -> tuple[tuple[RegressionHunk, ...], tuple[RemovalSpec, ...], tuple[PlantedFile, ...]]:
    hunks = tuple(regression_hunks.get(task.task_id, ())) if regression_hunks is not None else ()
    removal_specs = tuple(removals.get(task.task_id, ())) if removals is not None else ()
    planted = tuple(planted_files.get(task.task_id, ())) if planted_files is not None else ()
    if (
        any(source is not None for source in (regression_hunks, removals, planted_files))
        and not hunks
        and not removal_specs
        and not planted
    ):
        raise ValueError(f"no supported regression seed available for {task.task_id}")
    return hunks, removal_specs, planted


def _seed_docker_lines(
    task: TaskSpec,
    has_seed: bool,
) -> list[str]:
    if not has_seed:
        return []
    message = _docker_shell_string(f"seed regression: {task.task_id}")
    return [
        "COPY onmc_seed.py /tmp/onmc_seed.py",
        "RUN python /tmp/onmc_seed.py",
        "RUN git config user.email eval@onmc.local \\",
        "    && git config user.name onmc-eval",
        f"RUN git commit --quiet --all -m {message}",
    ]


def _seed_script(
    regression_hunks: Sequence[RegressionHunk],
    removals: Sequence[RemovalSpec],
    planted_files: Sequence[PlantedFile],
) -> str | None:
    if not (regression_hunks or removals or planted_files):
        return None
    payload = {
        "regression_hunks": list(regression_hunks),
        "removals": list(removals),
        "planted_files": list(planted_files),
    }
    return "\n".join(
        (
            "from __future__ import annotations",
            "",
            "import ast",
            "import json",
            "from pathlib import Path",
            "",
            f"PAYLOAD = {json.dumps(payload, sort_keys=True)}",
            "",
            "",
            "def replace_text(rel: str, old: str, new: str) -> None:",
            "    target = Path(rel)",
            "    text = target.read_text(encoding='utf-8')",
            "    if old not in text:",
            "        raise RuntimeError(f'regression anchor not found: {rel}')",
            "    target.write_text(text.replace(old, new, 1), encoding='utf-8')",
            "",
            "",
            "def remove_function_body(source: str, dotted: str) -> str:",
            "    tree = ast.parse(source)",
            "    parts = dotted.split('.')",
            "    node: ast.AST = tree",
            "    target = None",
            "    for depth, name in enumerate(parts):",
            "        found = None",
            "        for child in ast.iter_child_nodes(node):",
            "            if (",
            "                isinstance(child, "
            "(ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))",
            "                and child.name == name",
            "            ):",
            "                found = child",
            "                break",
            "        if found is None:",
            "            raise RuntimeError(f'{dotted}: {name!r} not found')",
            "        node = found",
            "        if depth == len(parts) - 1:",
            "            if not isinstance(found, (ast.FunctionDef, ast.AsyncFunctionDef)):",
            "                raise RuntimeError(f'{dotted} is not a function')",
            "            target = found",
            "    if target is None:",
            "        raise RuntimeError(f'{dotted} not resolved')",
            "    lines = source.splitlines(keepends=True)",
            "    first = target.body[0]",
            "    start = first.lineno - 1",
            "    end = target.end_lineno",
            "    if end is None:",
            "        raise RuntimeError(f'{dotted}: missing end_lineno')",
            "    indent = ' ' * first.col_offset",
            "    replacement = f'{indent}raise NotImplementedError(\"REMOVED\")\\n'",
            "    return ''.join(lines[:start]) + replacement + ''.join(lines[end:])",
            "",
            "",
            "for rel, old, new in PAYLOAD['regression_hunks']:",
            "    replace_text(rel, old, new)",
            "",
            "for rel, dotted in PAYLOAD['removals']:",
            "    target = Path(rel)",
            "    source = target.read_text(encoding='utf-8')",
            "    target.write_text(remove_function_body(source, dotted), encoding='utf-8')",
            "",
            "for rel, content in PAYLOAD['planted_files']:",
            "    target = Path(rel)",
            "    if target.exists():",
            "        raise RuntimeError(f'planted file would overwrite upstream content: {rel}')",
            "    target.parent.mkdir(parents=True, exist_ok=True)",
            "    target.write_text(content, encoding='utf-8')",
            "",
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


def _optional_number(value: object, name: str) -> float:
    if value is None:
        return 0.0
    return _number(value, name)


def _native_latency_ms(data: Mapping[str, object]) -> float:
    started = _parse_harbor_timestamp(_string(data.get("started_at"), "harbor.started_at"))
    finished = _parse_harbor_timestamp(_string(data.get("finished_at"), "harbor.finished_at"))
    delta_ms = (finished - started).total_seconds() * 1000
    if delta_ms < 0:
        raise ValueError("harbor.finished_at must not be before harbor.started_at")
    return delta_ms


def _native_context_tokens(agent_result: Mapping[str, object]) -> int:
    total = 0
    for key in ("n_input_tokens", "n_cache_tokens", "n_output_tokens"):
        value = agent_result.get(key)
        if value is None:
            continue
        total += _integer(value, f"harbor.agent_result.{key}")
    return total


def _native_task_id(data: Mapping[str, object]) -> str:
    raw_task_name = data.get("task_name")
    if isinstance(raw_task_name, str) and raw_task_name.strip():
        return raw_task_name.rsplit("/", 1)[-1]
    trial_name = _string(data.get("trial_name"), "harbor.trial_name")
    return trial_name.split("__", 1)[0]


def _parse_harbor_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_multiline_string(value: str) -> str:
    return '"""' + value.replace('"""', '\\"\\"\\"') + '"""'


def _docker_shell_string(value: str) -> str:
    return shlex.quote(value)
