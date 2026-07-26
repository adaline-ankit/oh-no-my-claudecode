"""Corpus-integrity tests for the external portfolio and its mutation tables.

These pin the properties that make the corpus *auditable* rather than merely
loadable. Each corresponds to a way a task corpus can be silently wrong:

- a manifest task with no mutation defined (the cell would fail as infra),
- a mutation table entry for a task that is neither in the manifest nor recorded
  in ``excluded_tasks`` (a silently dropped candidate),
- a planted structural grader that does not parse, or whose filename does not
  start with ``test_`` — which is what makes the runner's existing false-green
  detector cover tampering with it,
- a planted grader named explicitly in ``verifier_argv``, which would make
  validity gate 1 fail on the pristine tree (the file does not exist yet),
- a verifier argv the reference monitor would DENY, which zeroes the treatment
  arm while the control arm runs unimpeded,
- the v3 tasks drifting when v4 extended the corpus.

Nothing here clones a repository, spawns a subprocess, or contacts a provider.
Anchor text is verified against the real pinned sources by the ``--dry-run``
validity gates, not from memory here.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

SCRIPT_PATH = REPO_ROOT / "scripts" / "run_external_eval.py"
DATASETS = REPO_ROOT / "datasets" / "experiment"
V3_PATH = DATASETS / "portfolio_external_v3.json"
V4_PATH = DATASETS / "portfolio_external_v4.json"

#: Command prefixes the reference monitor allows for a verifier
#: (``_monitor_policy`` in ``harness_run/controller.py``).
ALLOWED_VERIFIER_PREFIXES = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("ruff",),
    ("mypy",),
)


def _load() -> ModuleType:
    module_name = "_run_external_eval_under_test"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner() -> ModuleType:
    return _load()


@pytest.fixture(scope="module")
def v4() -> dict[str, object]:
    return json.loads(V4_PATH.read_text(encoding="utf-8"))


def _tasks(manifest: dict[str, object]) -> list[dict[str, object]]:
    tasks = manifest["tasks"]
    assert isinstance(tasks, list)
    return tasks


def test_v4_loads_and_is_claim_ready() -> None:
    from oh_no_my_claudecode.experiment.portfolio import load_portfolio

    manifest = load_portfolio(V4_PATH)
    assert manifest.is_claim_ready
    assert manifest.claim_level().value == "external"


def test_trajectory_artifact_is_persisted_and_summarized(
    runner: ModuleType,
    tmp_path: Path,
) -> None:
    cfg = runner.EvalConfig(
        workdir=tmp_path,
        trials=1,
        dry_run=False,
        artifact_dir=tmp_path / "artifacts",
    )

    artifact = runner.write_text_artifact(
        cfg,
        "task-1.bare-agent.t1",
        "agent-trajectory.txt",
        "raw agent output",
        kind="raw-agent-trajectory",
        command="claude -p task",
    )

    assert artifact is not None
    assert artifact["kind"] == "raw-agent-trajectory"
    assert artifact["path"] == "artifacts/task-1.bare-agent.t1/agent-trajectory.txt"
    assert artifact["size_bytes"] == len(b"raw agent output")
    artifact_path = tmp_path / str(artifact["path"])
    assert artifact_path.read_text(encoding="utf-8") == "raw agent output"
    records = [
        runner.TrialRecord(
            "task-1",
            runner.Condition.BARE_AGENT.value,
            1,
            True,
            10.0,
            trajectory_artifact=artifact,
        ),
        runner.TrialRecord(
            "task-2",
            runner.Condition.BARE_AGENT.value,
            1,
            False,
            10.0,
            infra_error="agent unavailable",
            trajectory_artifact=artifact,
        ),
    ]

    summary = runner.trajectory_artifacts_report(records, [runner.Condition.BARE_AGENT])

    assert summary["overall"]["cells"] == 2
    assert summary["overall"]["usable_cells"] == 1
    assert summary["overall"]["artifact_cells"] == 1
    assert summary["overall"]["missing_artifacts"] == 0


def test_v4_carries_the_v3_tasks_over_unchanged() -> None:
    """v4 extends v3; it must not silently edit an already-measured task."""
    v3 = json.loads(V3_PATH.read_text(encoding="utf-8"))
    v4 = json.loads(V4_PATH.read_text(encoding="utf-8"))
    old = _tasks(v3)
    assert _tasks(v4)[: len(old)] == old


def test_every_manifest_task_has_a_mutation(runner: ModuleType, v4: dict[str, object]) -> None:
    """A task with no mutation fails ``inject_regression`` as infrastructure."""
    for task in _tasks(v4):
        task_id = task["task_id"]
        assert (
            task_id in runner.REGRESSIONS
            or task_id in runner.REMOVALS
            or task_id in runner.PLANTED_FILES
        ), f"{task_id} has no mutation defined"


def test_no_mutation_entry_is_silently_dropped(
    runner: ModuleType, v4: dict[str, object]
) -> None:
    """Every table entry is either measured or recorded with a reason."""
    live = {task["task_id"] for task in _tasks(v4)}
    excluded_raw = v4["excluded_tasks"]
    assert isinstance(excluded_raw, list)
    excluded = {row["task_id"] for row in excluded_raw}
    defined = set(runner.REGRESSIONS) | set(runner.REMOVALS) | set(runner.PLANTED_FILES)
    orphans = defined - live - excluded
    assert not orphans, f"mutation defined but neither measured nor excluded: {sorted(orphans)}"


def test_every_excluded_task_states_a_reason(v4: dict[str, object]) -> None:
    excluded_raw = v4["excluded_tasks"]
    assert isinstance(excluded_raw, list)
    for row in excluded_raw:
        reason = row["reason"]
        assert isinstance(reason, str)
        assert len(reason.strip()) > 20, f"{row['task_id']}: reason is not explanatory"


def test_verifier_argv_stays_within_the_monitor_allowlist(v4: dict[str, object]) -> None:
    """A non-allowlisted verifier is DENIED for ONMC and not for the bare arm."""
    for task in _tasks(v4):
        argv = task["verifier_argv"]
        assert isinstance(argv, list)
        assert any(
            tuple(argv[: len(prefix)]) == prefix for prefix in ALLOWED_VERIFIER_PREFIXES
        ), f"{task['task_id']}: verifier argv {argv} would be denied by the reference monitor"


def test_planted_graders_parse_and_are_named_like_tests(runner: ModuleType) -> None:
    for task_id, entries in runner.PLANTED_FILES.items():
        for rel, content in entries:
            base = rel.rsplit("/", 1)[-1]
            # The runner's false-green detector keys off this naming, so a planted
            # grader that is not named like a test could be edited unnoticed.
            assert base.startswith("test_"), f"{task_id}: {rel} is not named like a test"
            ast.parse(content)  # a grader that cannot be imported grades nothing


def test_planted_graders_are_not_named_in_verifier_argv(
    runner: ModuleType, v4: dict[str, object]
) -> None:
    """Gate 1 runs the verifier BEFORE injection, so the file does not exist yet.

    Naming it in ``verifier_argv`` makes the pristine run fail with "file not
    found" and the task is excluded as an infrastructure failure instead of run.
    """
    by_id = {task["task_id"]: task for task in _tasks(v4)}
    for task_id, entries in runner.PLANTED_FILES.items():
        task = by_id.get(task_id)
        if task is None:
            continue
        argv = task["verifier_argv"]
        assert isinstance(argv, list)
        for rel, _content in entries:
            assert rel not in argv, f"{task_id}: {rel} must not be named in verifier_argv"


def test_planted_grader_detects_the_seeded_shape_and_accepts_the_fixed_one(
    runner: ModuleType,
) -> None:
    """The refactor grader must FAIL on inlined duplicates and PASS once extracted.

    Without this the structural half of a refactor task could be vacuous — it
    would pass on the seeded tree and prove nothing about the agent's work.
    """
    grader = dict(runner.PLANTED_FILES["jmespath-refactor-dedup-key-func"])
    source = grader["tests/test_structure_dedup.py"]
    tree = ast.parse(source)
    names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert {
        "test_shared_key_function_helper_exists",
        "test_every_by_function_delegates_to_the_helper",
        "test_key_function_is_not_still_inlined",
    } <= names
    # The seed must remove the helper the grader looks for, otherwise the
    # structural assertions would already hold on the seeded tree.
    hunks = runner.REGRESSIONS["jmespath-refactor-dedup-key-func"]
    removals = [new for _rel, old, new in hunks if "_create_key_func(self" in old]
    assert removals == [""], "the refactor seed must delete the shared helper"


def test_repo_test_deps_cover_every_repo_in_the_manifest(
    runner: ModuleType, v4: dict[str, object]
) -> None:
    """A missing dep makes a cell fail as infra, never as evidence about an agent."""
    for task in _tasks(v4):
        repo = task["repo"]
        assert isinstance(repo, dict)
        assert repo["name"] in runner.REPO_TEST_DEPS, f"{repo['name']} has no recorded test deps"


def test_planted_file_injection_refuses_to_overwrite_upstream(
    runner: ModuleType, tmp_path: Path
) -> None:
    """Overwriting real upstream content would corrupt the corpus silently."""
    from oh_no_my_claudecode.experiment.portfolio import RepoRef, TaskKind, TaskSpec

    task = TaskSpec(
        task_id="jmespath-refactor-dedup-key-func",
        repo=RepoRef(
            name="jmespath.py",
            url="https://github.com/jmespath/jmespath.py.git",
            pinned_sha="2812594e69d43098ef60f81f4efc404c071b0418",
        ),
        prompt="stub",
        verifier_argv=("python", "-m", "pytest", "-q", "tests"),
        task_kind=TaskKind.REFACTOR,
        expected_outcome="stub",
    )
    (tmp_path / "jmespath").mkdir()
    (tmp_path / "jmespath" / "functions.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_structure_dedup.py").write_text("# upstream\n", encoding="utf-8")
    err = runner.inject_regression(task, tmp_path)
    assert err is not None
    assert "anchor not found" in err or "would overwrite" in err
