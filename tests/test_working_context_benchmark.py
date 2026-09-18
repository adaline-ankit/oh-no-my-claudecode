"""Benchmark integrity: independent delivery checks, percentiles, and grader controls."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from oh_no_my_claudecode.working_context.engine import WorkingContext

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def component(monkeypatch: pytest.MonkeyPatch):
    for key, value in (("ONMC_LEARNING", "1"), ("ONMC_EMBEDDINGS", "0"), ("ONMC_FIREWALL", "0")):
        monkeypatch.setenv(key, value)
    return runpy.run_path(str(SCRIPTS / "benchmark-working-context.py"))


def test_component_pairs_share_corpus_and_have_independent_delivery_checks(component):
    report = component["run"]([3], [7])
    assert len(report["rows"]) == 39
    assert len({r["corpus_sha256"] for r in report["rows"]}) == 1
    for row in report["rows"]:
        assert row["delivery_ok"] and row["constraints_retained"] and row["budget_ok"]
        if row["arm"] != "legacy_pinned":
            assert row["correct"]
    baseline = report["summary"][0]
    assert baseline["unsafe_claims"] == 2  # stale edit and deleted source, not quarantine


def test_silent_compiler_cannot_claim_perfect_delivery(component, tmp_path, monkeypatch):
    original = WorkingContext.context

    def silent(self, *args, **kwargs):
        return original(self, *args, **kwargs).model_copy(update={"injection": ""})

    monkeypatch.setattr(WorkingContext, "context", silent)
    rows = component["run_stream"](tmp_path / "repo", 3, 7, "adaptive")
    assert all(row["correct"] for row in rows)  # packet quality alone misses the bug
    assert sum(not row["delivery_ok"] for row in rows) == 8
    assert component["summarize"](rows)[0]["delivery_failures"] == 8


def test_latency_percentiles_use_percent_scale(component):
    rows = [
        {
            "size": 1,
            "arm": "adaptive",
            "event": "repeat_1",
            "latency_ms": value,
            "correct": True,
            "unsafe_claim": False,
            "missing_valid_claim": False,
            "constraints_retained": True,
            "budget_ok": True,
            "delivery_ok": True,
            "injected_chars": 0,
        }
        for value in range(1, 101)
    ]
    summary = component["summarize"](rows)[0]
    assert summary["latency_p50_ms"] == 50.5
    assert summary["latency_p95_ms"] == 95.05


def test_duplicate_streams_rejected(component):
    with pytest.raises(ValueError, match="Duplicate"):
        component["run"]([1, 1], [7])


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    monkeypatch.setenv("ONMC_LEARNING", "1")
    monkeypatch.setenv("ONMC_EMBEDDINGS", "0")
    return runpy.run_path(str(SCRIPTS / "benchmark-working-context-live.py"))


def test_all_live_graders_pass_reference_and_fail_stub_without_model_calls(live):
    results = live["check_fixtures"]()
    assert len(results) == 3
    assert all(r["reference"]["passed"] and r["reference"]["tests_run"] == 6 for r in results)
    assert all(not r["stub"]["passed"] and r["stub"]["tests_run"] == 6 for r in results)


@pytest.mark.parametrize("task_id", ["expiry", "ledger", "intervals"])
def test_live_graders_detect_contract_violations(live, tmp_path, task_id):
    task = next(t for t in live["TASKS"] if t["id"] == task_id)
    mutations = {
        "expiry": ("            del self.entries[key]\n", ""),
        "ledger": ("not isinstance(key, str) or not key", "not key"),
        "intervals": ("a < result[-1][1]", "a <= result[-1][1]"),
    }
    before, after = mutations[task_id]
    assert before in task["reference"]
    (tmp_path / "solution.py").write_text(task["reference"].replace(before, after))
    assert not live["grade"](tmp_path, task["tests"], tmp_path)["passed"]


def test_live_arms_start_with_same_facts_and_omit_missing_source(live, tmp_path, monkeypatch):
    monkeypatch.setenv("ONMC_LEARNING", "1")
    task = live["TASKS"][0]
    packet_a, hashes_a = live["prepare"](tmp_path / "baseline", task)
    packet_b, hashes_b = live["prepare"](tmp_path / "adaptive", task)
    assert hashes_a == hashes_b
    assert packet_a == packet_b
    assert task["contract"].strip() in packet_a
    assert task["stale"] not in packet_a


def test_live_grader_rejects_shadowed_zero_test_success(live, tmp_path):
    task = live["TASKS"][0]
    (tmp_path / "solution.py").write_text(task["stub"])
    (tmp_path / "unittest.py").write_text(
        "TestCase = object\ndef main(**kwargs): print('Ran 0 tests')\n"
    )
    verdict = live["grade"](tmp_path, task["tests"], tmp_path)
    assert not verdict["passed"]
    assert verdict["tests_run"] == 6


def test_live_provider_exceptions_remain_in_attempt_denominator(live, tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        def runner(*args, **kwargs):
            raise RuntimeError("provider unavailable")
        return runner

    globals_ = live["run"].__globals__
    monkeypatch.setitem(globals_, "make_agent_runner", unavailable)
    subprocess = globals_["subprocess"]
    original = subprocess.check_output

    def output(cmd, **kwargs):
        return "codex test-version" if cmd == ["codex", "--version"] else original(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "check_output", output)
    destination = tmp_path / "pilot"
    report = live["run"](destination, "fake-model", "medium", 1, 1)
    assert report["manifest"]["planned_attempts"] == len(report["rows"]) == 6
    assert all(not row["passed"] and "provider unavailable" in row["agent_error"]
               for row in report["rows"])
    assert json.loads((destination / "results.json").read_text()) == report
