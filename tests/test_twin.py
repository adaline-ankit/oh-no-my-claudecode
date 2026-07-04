"""Tests for the ``onmc twin`` change-rehearsal engine.

Covers:
- dependents (blast radius) are populated from the neighbours lookup
- risk classification: "high" when dependents >= HIGH_RISK_DEPENDENTS, else "low"
- covering tests are surfaced per file and aggregated (deduped, sorted)
- total_blast counts distinct dependents and excludes co-touched siblings
- suggested_tests is deduped and deterministically ordered
- an empty graph is graceful (empty-but-valid plan + explanatory note)
- an unresolved path yields an empty low-risk entry + a note
- build_rehearsal works with an injected neighbors_fn (no real DB/graph needed)
- the real (default) path builds a graph from a tiny fake repo and finds edges
- the --json shape matches RehearsalPlan.to_dict()

Never asserts against Rich / ``--help`` output.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.codegraph import Neighbors
from oh_no_my_claudecode.twin.twin import (
    HIGH_RISK_DEPENDENTS,
    RehearsalPlan,
    TouchedFile,
    build_rehearsal,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Injected-neighbours helpers (pure — no real graph needed)
# ---------------------------------------------------------------------------


def _make_neighbors_fn(table: dict[str, Neighbors]):
    """Return a neighbors_fn backed by *table*; unknown targets are empty."""

    def _lookup(target: str) -> Neighbors:
        return table.get(target, Neighbors(target=target))

    return _lookup


def _neighbors(
    target: str,
    *,
    dependents: list[str] | None = None,
    tests: list[str] | None = None,
) -> Neighbors:
    """Construct a resolved Neighbors for a file target."""
    deps = dependents or []
    tsts = tests or []
    return Neighbors(
        target=target,
        target_files=[target],
        importers=[d for d in deps if d not in tsts],
        dependents=sorted(set(deps) | set(tsts)),
        tests=tsts,
        imports=[],
    )


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


def test_dependents_and_covering_tests_populated() -> None:
    fn = _make_neighbors_fn(
        {
            "src/cache.py": _neighbors(
                "src/cache.py",
                dependents=["src/app.py"],
                tests=["tests/test_cache.py"],
            ),
        }
    )
    plan = build_rehearsal(Path("/repo"), ["src/cache.py"], neighbors_fn=fn)

    assert len(plan.touched) == 1
    tf = plan.touched[0]
    assert tf.path == "src/cache.py"
    assert tf.resolved is True
    assert "src/app.py" in tf.dependents
    assert tf.covering_tests == ["tests/test_cache.py"]
    assert plan.suggested_tests == ["tests/test_cache.py"]
    assert plan.total_blast == 1


def test_risk_high_when_many_dependents() -> None:
    many = [f"src/dep_{i}.py" for i in range(HIGH_RISK_DEPENDENTS)]
    fn = _make_neighbors_fn({"src/hub.py": _neighbors("src/hub.py", dependents=many)})
    plan = build_rehearsal(Path("/repo"), ["src/hub.py"], neighbors_fn=fn)

    assert plan.touched[0].risk == "high"
    assert plan.high_risk == ["src/hub.py"]
    assert plan.total_blast == HIGH_RISK_DEPENDENTS


def test_risk_low_when_few_dependents() -> None:
    fn = _make_neighbors_fn(
        {"src/leaf.py": _neighbors("src/leaf.py", dependents=["src/one.py"])}
    )
    plan = build_rehearsal(Path("/repo"), ["src/leaf.py"], neighbors_fn=fn)

    assert plan.touched[0].risk == "low"
    assert plan.high_risk == []


def test_suggested_tests_deduped_and_sorted() -> None:
    fn = _make_neighbors_fn(
        {
            "src/a.py": _neighbors("src/a.py", tests=["tests/test_b.py", "tests/test_a.py"]),
            "src/b.py": _neighbors("src/b.py", tests=["tests/test_b.py"]),
        }
    )
    plan = build_rehearsal(Path("/repo"), ["src/a.py", "src/b.py"], neighbors_fn=fn)

    # Deduped (test_b appears twice) and sorted.
    assert plan.suggested_tests == ["tests/test_a.py", "tests/test_b.py"]


def test_co_touched_siblings_excluded_from_blast() -> None:
    # a and b import each other; editing both means neither is "breakage".
    fn = _make_neighbors_fn(
        {
            "src/a.py": _neighbors("src/a.py", dependents=["src/b.py", "src/c.py"]),
            "src/b.py": _neighbors("src/b.py", dependents=["src/a.py"]),
        }
    )
    plan = build_rehearsal(Path("/repo"), ["src/a.py", "src/b.py"], neighbors_fn=fn)

    a_tf = next(tf for tf in plan.touched if tf.path == "src/a.py")
    assert "src/b.py" not in a_tf.dependents  # sibling excluded
    assert a_tf.dependents == ["src/c.py"]
    assert plan.total_blast == 1  # only src/c.py


def test_duplicate_paths_deduped_preserving_order() -> None:
    fn = _make_neighbors_fn({"src/a.py": _neighbors("src/a.py")})
    plan = build_rehearsal(
        Path("/repo"), ["src/a.py", "./src/a.py", "src/a.py"], neighbors_fn=fn
    )
    assert [tf.path for tf in plan.touched] == ["src/a.py"]


def test_empty_graph_is_graceful() -> None:
    # No neighbors_fn injected + empty repo → empty-but-valid plan with a note.
    def _empty_lookup(target: str) -> Neighbors:  # pragma: no cover - unused
        return Neighbors(target=target)

    plan = build_rehearsal(Path("/repo"), [], neighbors_fn=_empty_lookup)
    assert plan.touched == []
    assert plan.total_blast == 0
    assert plan.high_risk == []
    assert plan.suggested_tests == []
    # No paths + injected fn → no note (fn owns the data, graph_empty=False).
    assert plan.note == ""


def test_unresolved_path_gets_note_and_empty_entry() -> None:
    fn = _make_neighbors_fn({})  # nothing resolves
    plan = build_rehearsal(Path("/repo"), ["src/ghost.py"], neighbors_fn=fn)

    tf = plan.touched[0]
    assert tf.resolved is False
    assert tf.dependents == []
    assert tf.risk == "low"
    assert "not found" in plan.note.lower()
    assert "src/ghost.py" in plan.note


def test_to_dict_shape_is_json_safe() -> None:
    fn = _make_neighbors_fn(
        {"src/a.py": _neighbors("src/a.py", dependents=["src/b.py"], tests=["tests/test_a.py"])}
    )
    plan = build_rehearsal(Path("/repo"), ["src/a.py"], neighbors_fn=fn)
    payload = plan.to_dict()

    # Round-trips through JSON with the documented keys.
    reloaded = json.loads(json.dumps(payload))
    assert set(reloaded) == {"touched", "total_blast", "high_risk", "suggested_tests", "note"}
    assert reloaded["touched"][0]["path"] == "src/a.py"
    assert reloaded["touched"][0]["risk"] == "low"
    assert reloaded["touched"][0]["resolved"] is True


def test_touched_file_dataclass_defaults() -> None:
    tf = TouchedFile(path="src/x.py")
    assert tf.dependents == []
    assert tf.covering_tests == []
    assert tf.risk == "low"
    assert tf.resolved is True
    assert isinstance(RehearsalPlan(), RehearsalPlan)


# ---------------------------------------------------------------------------
# Real (default) code-graph path against a tiny fake repo
# ---------------------------------------------------------------------------


def _write_fake_repo(root: Path) -> None:
    """Create a tiny repo: base.py, app.py (imports base), test_base.py."""
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "base.py").write_text("def core():\n    return 1\n", encoding="utf-8")
    (pkg / "app.py").write_text(
        "from pkg.base import core\n\n\ndef run():\n    return core()\n", encoding="utf-8"
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_base.py").write_text(
        "from pkg.base import core\n\n\ndef test_core():\n    assert core() == 1\n",
        encoding="utf-8",
    )


def test_real_graph_finds_dependents_and_tests(tmp_path: Path) -> None:
    _write_fake_repo(tmp_path)
    # No neighbors_fn → build_rehearsal builds the real graph from tmp_path.
    plan = build_rehearsal(tmp_path, ["pkg/base.py"])

    tf = plan.touched[0]
    assert tf.resolved is True
    assert "pkg/app.py" in tf.dependents
    assert "tests/test_base.py" in tf.covering_tests
    assert "tests/test_base.py" in plan.suggested_tests
    assert plan.note == ""


def test_real_empty_repo_notes_empty_graph(tmp_path: Path) -> None:
    # No source files at all → graph empty → explanatory note, no crash.
    plan = build_rehearsal(tmp_path, ["pkg/base.py"])
    assert "empty" in plan.note.lower()
    assert "onmc codegraph" in plan.note


# ---------------------------------------------------------------------------
# CLI smoke (behaviour, not help text)
# ---------------------------------------------------------------------------


def test_cli_plan_json_runs_in_fake_repo(tmp_path: Path, monkeypatch) -> None:
    _write_fake_repo(tmp_path)
    # discover_repo_root needs a git repo; make tmp_path one.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["twin", "plan", "pkg/base.py", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["touched"][0]["path"] == "pkg/base.py"
    assert "pkg/app.py" in payload["touched"][0]["dependents"]
