"""Tests for the Agent Trace Observatory (onmc trace).

Covers:
- compile_trace_report aggregates a seeded events list correctly:
  - counts tool calls
  - flags repeated file reads (same path ≥2)
  - detects a loop (tool+target recurring ≥ loop_threshold)
  - computes memory hit-rate from memory_hit / memory_miss events
  - computes tokens_saved_pct via an injected deterministic savings_estimator
  - empty events list → all-zero report, no divide-by-zero
- recall_surfaced notify events count as memory hits
- danger_blocked notify events count as tool failures
- start/stop session lifecycle: writes and closes the JSONL file
- current_session_id reflects open/closed state
- load_session_events returns session envelope + events
- CLI start/stop/report exit codes and output shapes
- CLI --json emits valid JSON with expected keys
- CLI --otel writes span dicts with gen_ai.* attributes
- Uninitialized repo: trace report exits non-zero (graceful failure)
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.trace.models import (
    TraceEvent,
    TraceEventKind,
    TraceReport,
    TraceSession,
)
from oh_no_my_claudecode.trace.recorder import (
    current_session_id,
    load_session_events,
    record_trace_event,
    start_session,
    stop_session,
)
from oh_no_my_claudecode.trace.report import compile_trace_report

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = time.time()


def _ev(kind: str, **payload: object) -> TraceEvent:
    return TraceEvent(kind=kind, ts=_NOW, payload=dict(payload))


def _session(sid: str = "tr_test01") -> TraceSession:
    return TraceSession(session_id=sid, started_at=_NOW, ended_at=None, label="test")


def _fixed_estimator(reduction: float) -> Callable[[], float]:
    """Return a savings estimator that always returns *reduction*."""

    def _est() -> float:
        return reduction

    return _est


# ---------------------------------------------------------------------------
# compile_trace_report — unit tests
# ---------------------------------------------------------------------------


class TestCompileTraceReport:
    def test_counts_tool_calls(self) -> None:
        events = [
            _ev(TraceEventKind.TOOL_CALL, tool="Read", target="src/foo.py"),
            _ev(TraceEventKind.TOOL_CALL, tool="Bash", target="ls"),
            _ev(TraceEventKind.TOOL_CALL, tool="Edit", target="src/bar.py"),
        ]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.0))
        assert report.tool_calls == 3

    def test_counts_tool_failures(self) -> None:
        events = [
            _ev(TraceEventKind.TOOL_FAILURE, tool="Bash", target="broken"),
        ]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.0))
        assert report.tool_failures == 1

    def test_flags_repeated_file_reads(self) -> None:
        path = "src/cache.py"
        events = [
            _ev(TraceEventKind.FILE_READ, target=path),
            _ev(TraceEventKind.FILE_READ, target=path),
            _ev(TraceEventKind.FILE_READ, target=path),
            _ev(TraceEventKind.FILE_READ, target="src/other.py"),  # only once → not repeated
        ]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.0))
        repeated_paths = [r.target for r in report.repeated_file_reads]
        assert path in repeated_paths
        assert "src/other.py" not in repeated_paths
        # Count should be 3
        match = next(r for r in report.repeated_file_reads if r.target == path)
        assert match.count == 3

    def test_repeated_reads_blocked_calculation(self) -> None:
        path = "src/cache.py"
        events = [
            _ev(TraceEventKind.FILE_READ, target=path),
            _ev(TraceEventKind.FILE_READ, target=path),
            _ev(TraceEventKind.FILE_READ, target=path),
        ]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.0))
        # count=3 → blocked = 3-1 = 2
        assert report.repeated_reads_blocked == 2

    def test_detects_loop(self) -> None:
        """A (tool, target) pair recurring ≥ loop_threshold is a loop signal."""
        events = [
            _ev(TraceEventKind.TOOL_CALL, tool="Read", target="src/foo.py"),
            _ev(TraceEventKind.TOOL_CALL, tool="Read", target="src/foo.py"),
            _ev(TraceEventKind.TOOL_CALL, tool="Read", target="src/foo.py"),
        ]
        report = compile_trace_report(
            events, savings_estimator=_fixed_estimator(0.0), loop_threshold=3
        )
        assert len(report.loops_detected) >= 1
        loop = report.loops_detected[0]
        assert loop.tool == "Read"
        assert loop.target == "src/foo.py"
        assert loop.count == 3

    def test_no_loop_below_threshold(self) -> None:
        events = [
            _ev(TraceEventKind.TOOL_CALL, tool="Read", target="src/foo.py"),
            _ev(TraceEventKind.TOOL_CALL, tool="Read", target="src/foo.py"),
        ]
        report = compile_trace_report(
            events, savings_estimator=_fixed_estimator(0.0), loop_threshold=3
        )
        assert report.loops_detected == []

    def test_memory_hit_rate(self) -> None:
        events = [
            _ev(TraceEventKind.MEMORY_HIT),
            _ev(TraceEventKind.MEMORY_HIT),
            _ev(TraceEventKind.MEMORY_HIT),
            _ev(TraceEventKind.MEMORY_MISS),
        ]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.0))
        assert report.memory_hits == 3
        assert report.memory_misses == 1
        assert abs(report.memory_hit_rate - 0.75) < 1e-6

    def test_recall_surfaced_counts_as_memory_hit(self) -> None:
        """notify recall_surfaced event maps to memory_hit."""
        events = [
            _ev(TraceEventKind.RECALL_SURFACED, title="memory recalled"),
        ]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.0))
        assert report.memory_hits == 1

    def test_danger_blocked_counts_as_tool_failure(self) -> None:
        """notify danger_blocked event maps to tool_failure."""
        events = [
            _ev(TraceEventKind.DANGER_BLOCKED, title="blocked dangerous command"),
        ]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.0))
        assert report.tool_failures == 1

    def test_tokens_saved_deterministic_with_injected_estimator(self) -> None:
        """With a fixed 50% estimator and 1000 tokens, est_without = 2000, saved = 50%."""
        events = [_ev(TraceEventKind.TOKENS, total=1000)]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.5))
        assert report.total_tokens == 1000
        assert report.est_tokens_without_onmc == 2000
        assert abs(report.tokens_saved_pct - 50.0) < 0.5

    def test_tokens_saved_zero_reduction(self) -> None:
        events = [_ev(TraceEventKind.TOKENS, total=500)]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.0))
        assert report.total_tokens == 500
        assert report.est_tokens_without_onmc == 500
        assert report.tokens_saved_pct == 0.0

    def test_empty_events_all_zeroes(self) -> None:
        """Empty events list must not raise and must return all-zero report."""
        report = compile_trace_report([], savings_estimator=_fixed_estimator(0.5))
        assert report.tool_calls == 0
        assert report.tool_failures == 0
        assert report.total_tokens == 0
        assert report.est_tokens_without_onmc == 0
        assert report.tokens_saved_pct == 0.0
        assert report.memory_hits == 0
        assert report.memory_misses == 0
        assert report.repeated_file_reads == []
        assert report.repeated_search_queries == []
        assert report.loops_detected == []
        assert report.top_wasteful == []

    def test_empty_events_no_divide_by_zero(self) -> None:
        """memory_hit_rate must be 0.0 when no memory events, not a ZeroDivisionError."""
        report = compile_trace_report([], savings_estimator=_fixed_estimator(0.5))
        assert report.memory_hit_rate == 0.0

    def test_session_meta_propagated(self) -> None:
        session = _session("tr_abc123")
        report = compile_trace_report([], session=session, savings_estimator=_fixed_estimator(0.0))
        assert report.session_id == "tr_abc123"
        assert report.label == "test"

    def test_honesty_notes_always_present(self) -> None:
        report = compile_trace_report([], savings_estimator=_fixed_estimator(0.0))
        assert len(report.extra_notes) >= 1

    def test_result_is_trace_report_type(self) -> None:
        report = compile_trace_report([], savings_estimator=_fixed_estimator(0.0))
        assert isinstance(report, TraceReport)

    def test_top_wasteful_sorted_by_count(self) -> None:
        events = [
            _ev(TraceEventKind.FILE_READ, target="a.py"),
            _ev(TraceEventKind.FILE_READ, target="a.py"),
            _ev(TraceEventKind.FILE_READ, target="a.py"),
            _ev(TraceEventKind.FILE_READ, target="b.py"),
            _ev(TraceEventKind.FILE_READ, target="b.py"),
        ]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.0))
        assert len(report.top_wasteful) >= 2
        assert report.top_wasteful[0].target == "a.py"  # count=3 first
        assert report.top_wasteful[1].target == "b.py"  # count=2 second

    def test_repeated_search_queries_flagged(self) -> None:
        q = "how to invalidate cache"
        events = [
            _ev(TraceEventKind.SEARCH_QUERY, target=q),
            _ev(TraceEventKind.SEARCH_QUERY, target=q),
        ]
        report = compile_trace_report(events, savings_estimator=_fixed_estimator(0.0))
        assert any(r.target == q for r in report.repeated_search_queries)


# ---------------------------------------------------------------------------
# Recorder lifecycle tests
# ---------------------------------------------------------------------------


class TestRecorderLifecycle:
    def test_start_session_creates_jsonl(self, tmp_path: Path) -> None:
        sid = start_session(tmp_path, label="my test")
        assert sid is not None
        session_file = tmp_path / ".onmc" / "traces" / f"{sid}.jsonl"
        assert session_file.exists()

    def test_start_session_writes_envelope(self, tmp_path: Path) -> None:
        sid = start_session(tmp_path, label="envelope test")
        assert sid is not None
        session_file = tmp_path / ".onmc" / "traces" / f"{sid}.jsonl"
        first_line = session_file.read_text(encoding="utf-8").splitlines()[0]
        record = json.loads(first_line)
        assert record["_type"] == "session"
        assert record["session_id"] == sid
        assert record["label"] == "envelope test"
        assert record["started_at"] > 0

    def test_start_session_sets_current_pointer(self, tmp_path: Path) -> None:
        sid = start_session(tmp_path)
        assert sid is not None
        assert current_session_id(tmp_path) == sid

    def test_stop_session_closes_and_removes_current(self, tmp_path: Path) -> None:
        sid = start_session(tmp_path)
        assert sid is not None
        ok = stop_session(tmp_path)
        assert ok is True
        # current pointer should be gone
        assert current_session_id(tmp_path) is None

    def test_stop_session_writes_tombstone(self, tmp_path: Path) -> None:
        sid = start_session(tmp_path)
        assert sid is not None
        stop_session(tmp_path)
        session_file = tmp_path / ".onmc" / "traces" / f"{sid}.jsonl"
        lines = session_file.read_text(encoding="utf-8").splitlines()
        last_record = json.loads(lines[-1])
        assert last_record["_type"] == "session_end"
        assert last_record["ended_at"] > 0

    def test_stop_session_returns_false_when_no_session(self, tmp_path: Path) -> None:
        ok = stop_session(tmp_path)
        assert ok is False

    def test_record_trace_event_appends_to_jsonl(self, tmp_path: Path) -> None:
        sid = start_session(tmp_path)
        assert sid is not None
        ev = TraceEvent(kind=TraceEventKind.TOOL_CALL, ts=_NOW, payload={"tool": "Read"})
        record_trace_event(tmp_path, ev)
        session_file = tmp_path / ".onmc" / "traces" / f"{sid}.jsonl"
        lines = session_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2  # envelope + event
        ev_record = json.loads(lines[1])
        assert ev_record["kind"] == TraceEventKind.TOOL_CALL

    def test_record_trace_event_noop_without_session(self, tmp_path: Path) -> None:
        """record_trace_event must not raise when no session is active."""
        ev = TraceEvent(kind=TraceEventKind.TOOL_CALL, ts=_NOW, payload={"tool": "Read"})
        record_trace_event(tmp_path, ev)  # must not raise

    def test_load_session_events_returns_session_and_events(self, tmp_path: Path) -> None:
        sid = start_session(tmp_path, label="load test")
        assert sid is not None
        ev = TraceEvent(kind=TraceEventKind.FILE_READ, ts=_NOW, payload={"target": "src/x.py"})
        record_trace_event(tmp_path, ev)
        stop_session(tmp_path)

        session, events = load_session_events(tmp_path, sid)
        assert session is not None
        assert session.session_id == sid
        assert session.label == "load test"
        assert session.ended_at is not None
        assert any(e.kind == TraceEventKind.FILE_READ for e in events)

    def test_load_session_events_missing_file_returns_none(self, tmp_path: Path) -> None:
        session, events = load_session_events(tmp_path, "tr_nonexistent")
        assert session is None
        assert events == []

    def test_current_session_id_none_when_no_session(self, tmp_path: Path) -> None:
        assert current_session_id(tmp_path) is None


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestTraceCliStartStop:
    def test_start_exits_0(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        OnmcService(cwd=sample_repo).init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["trace", "start"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "started" in result.output.lower()

    def test_start_with_label(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        OnmcService(cwd=sample_repo).init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(
            app, ["trace", "start", "--label", "Codex task"], catch_exceptions=False
        )
        assert result.exit_code == 0
        assert "Codex task" in result.output

    def test_stop_exits_0_after_start(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        OnmcService(cwd=sample_repo).init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        runner.invoke(app, ["trace", "start"], catch_exceptions=False)
        result = runner.invoke(app, ["trace", "stop"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "closed" in result.output.lower()

    def test_stop_exits_nonzero_without_session(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        OnmcService(cwd=sample_repo).init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["trace", "stop"])
        assert result.exit_code != 0


class TestTraceCliReport:
    def _start_session_with_events(self, sample_repo: Path) -> str:
        """Helper: start a session, record some events, stop it. Returns session_id."""
        sid = start_session(sample_repo, label="Codex task")
        assert sid is not None
        evs = [
            TraceEvent(
                kind=TraceEventKind.TOKENS, ts=_NOW, payload={"total": 8420}
            ),
            TraceEvent(
                kind=TraceEventKind.TOOL_CALL, ts=_NOW, payload={"tool": "Read", "target": "a.py"}
            ),
            TraceEvent(
                kind=TraceEventKind.FILE_READ, ts=_NOW, payload={"target": "a.py"}
            ),
            TraceEvent(
                kind=TraceEventKind.FILE_READ, ts=_NOW, payload={"target": "a.py"}
            ),
            TraceEvent(
                kind=TraceEventKind.MEMORY_HIT, ts=_NOW, payload={}
            ),
        ]
        for ev in evs:
            record_trace_event(sample_repo, ev)
        stop_session(sample_repo)
        return sid

    def test_report_exits_0(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        OnmcService(cwd=sample_repo).init_project()
        sid = self._start_session_with_events(sample_repo)
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["trace", "report", sid], catch_exceptions=False)
        assert result.exit_code == 0

    def test_report_card_contains_observatory(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        OnmcService(cwd=sample_repo).init_project()
        sid = self._start_session_with_events(sample_repo)
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["trace", "report", sid], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Trace Observatory" in result.output or "onmc" in result.output.lower()

    def test_report_json_valid(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        OnmcService(cwd=sample_repo).init_project()
        sid = self._start_session_with_events(sample_repo)
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(
            app, ["trace", "report", sid, "--json"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "session_id" in data
        assert "total_tokens" in data
        assert "tokens_saved_pct" in data
        assert "tool_calls" in data
        assert "memory_hits" in data
        assert "repeated_reads_blocked" in data
        assert "extra_notes" in data

    def test_report_json_types(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        OnmcService(cwd=sample_repo).init_project()
        sid = self._start_session_with_events(sample_repo)
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(
            app, ["trace", "report", sid, "--json"], catch_exceptions=False
        )
        data = json.loads(result.output)
        assert isinstance(data["total_tokens"], int)
        assert isinstance(data["tokens_saved_pct"], float)
        assert isinstance(data["tool_calls"], int)
        assert isinstance(data["repeated_file_reads"], list)
        assert isinstance(data["loops_detected"], list)
        assert isinstance(data["extra_notes"], list)

    def test_report_exits_nonzero_no_session(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        OnmcService(cwd=sample_repo).init_project()
        monkeypatch.chdir(sample_repo)

        runner = CliRunner()
        result = runner.invoke(app, ["trace", "report", "tr_nonexistent"])
        assert result.exit_code != 0

    def test_report_otel_writes_file(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from oh_no_my_claudecode.core.service import OnmcService

        OnmcService(cwd=sample_repo).init_project()
        sid = self._start_session_with_events(sample_repo)
        monkeypatch.chdir(sample_repo)

        otel_file = tmp_path / "spans.json"
        runner = CliRunner()
        result = runner.invoke(
            app, ["trace", "report", sid, "--otel", str(otel_file)], catch_exceptions=False
        )
        assert result.exit_code == 0
        assert otel_file.exists()
        spans = json.loads(otel_file.read_text(encoding="utf-8"))
        assert isinstance(spans, list)

    def test_report_uninitialized_repo_exits_nonzero(self, tmp_path: Path) -> None:
        """Uninitialized repo must exit non-zero gracefully."""
        runner = CliRunner()
        result = runner.invoke(app, ["trace", "report"], obj=None)
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# OTel span shape tests
# ---------------------------------------------------------------------------


class TestOtelSpans:
    def test_to_otel_spans_from_events(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            _ev(TraceEventKind.TOOL_CALL, tool="Read", target="src/foo.py"),
            _ev(TraceEventKind.TOKENS, total=500),
        ]
        spans = to_otel_spans(events, session_id="tr_test")
        assert len(spans) == 2
        for span in spans:
            assert len(span["traceId"]) == 32
            assert len(span["spanId"]) == 16
            assert "name" in span
            assert "startTimeUnixNano" in span
            assert "attributes" in span
            # Each span must have gen_ai.system = "onmc"
            attr_keys = {a["key"] for a in span["attributes"]}
            assert "gen_ai.system" in attr_keys
            assert "gen_ai.operation.name" in attr_keys
        assert spans[0]["traceId"] == spans[1]["traceId"]
        assert spans[0]["spanId"] != spans[1]["spanId"]

    def test_otel_span_ids_are_stable_for_same_events(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=100.0,
                payload={"run_id": "run-1", "node_id": "execute", "status": "succeeded"},
            ),
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=101.0,
                payload={"run_id": "run-1", "node_id": "verify", "status": "failed"},
            ),
        ]

        first = to_otel_spans(events, session_id="tr_stable")
        second = to_otel_spans(events, session_id="tr_stable")

        assert [span["traceId"] for span in first] == [span["traceId"] for span in second]
        assert [span["spanId"] for span in first] == [span["spanId"] for span in second]
        assert first[0]["traceId"] == first[1]["traceId"]
        assert first[0]["spanId"] != first[1]["spanId"]

    def test_otel_runtime_node_dependency_links_reference_dependency_spans(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=100.0,
                payload={"run_id": "run-1", "node_id": "plan", "status": "succeeded"},
            ),
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=101.0,
                payload={
                    "run_id": "run-1",
                    "node_id": "execute",
                    "status": "succeeded",
                    "dependencies": ["plan"],
                },
            ),
        ]
        spans = to_otel_spans(events, session_id="tr_links")

        plan_span, execute_span = spans
        assert execute_span["links"] == [
            {
                "traceId": plan_span["traceId"],
                "spanId": plan_span["spanId"],
                "attributes": [
                    {
                        "key": "onmc.runtime.dependency",
                        "value": {"stringValue": "plan"},
                    }
                ],
            }
        ]

    def test_otel_runtime_nodes_use_runtime_run_as_parent_span(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.RUNTIME_RUN,
                ts=99.0,
                payload={"run_id": "run-1", "status": "completed"},
            ),
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=100.0,
                payload={"run_id": "run-1", "node_id": "plan", "status": "succeeded"},
            ),
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=101.0,
                payload={
                    "run_id": "run-1",
                    "node_id": "execute",
                    "status": "succeeded",
                    "dependencies": ["plan"],
                },
            ),
        ]
        spans = to_otel_spans(events, session_id="tr_parent")

        run_span, plan_span, execute_span = spans
        assert plan_span["parentSpanId"] == run_span["spanId"]
        assert execute_span["parentSpanId"] == run_span["spanId"]
        assert execute_span["links"][0]["spanId"] == plan_span["spanId"]

    def test_to_otel_spans_from_report(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        report = compile_trace_report(
            [
                _ev(TraceEventKind.TOKENS, total=1000),
                _ev(TraceEventKind.MEMORY_HIT),
            ],
            savings_estimator=_fixed_estimator(0.3),
            session=_session("tr_rpt01"),
        )
        spans = to_otel_spans(report)
        assert isinstance(spans, list)
        # At minimum the TOKENS span and MEMORY_HIT span should be emitted
        assert len(spans) >= 1

    def test_otel_span_gen_ai_attributes_present(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [_ev(TraceEventKind.TOKENS, total=800)]
        spans = to_otel_spans(events, session_id="tr_otel")
        span = spans[0]
        attr_map = {a["key"]: a["value"] for a in span["attributes"]}
        assert attr_map["gen_ai.system"]["stringValue"] == "onmc"
        assert "gen_ai.usage.input_tokens" in attr_map or "gen_ai.usage.output_tokens" in attr_map

    def test_otel_span_preserves_measured_token_usage(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            _ev(
                TraceEventKind.TOKENS,
                input_tokens=321,
                output_tokens=123,
                total=444,
            )
        ]
        spans = to_otel_spans(events, session_id="tr_measured")

        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["gen_ai.usage.input_tokens"]["intValue"] == 321
        assert attr_map["gen_ai.usage.output_tokens"]["intValue"] == 123
        assert attr_map["onmc.usage.total_tokens"]["intValue"] == 444
        assert attr_map["onmc.usage.estimated"]["boolValue"] is False

    def test_otel_span_marks_legacy_total_token_split_as_estimated(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [_ev(TraceEventKind.TOKENS, total=500)]
        spans = to_otel_spans(events, session_id="tr_estimated")

        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["gen_ai.usage.input_tokens"]["intValue"] == 300
        assert attr_map["gen_ai.usage.output_tokens"]["intValue"] == 200
        assert attr_map["onmc.usage.estimated"]["boolValue"] is True
        assert (
            attr_map["onmc.usage.estimate_reason"]["stringValue"]
            == "legacy_total_tokens_only"
        )

    def test_otel_span_preserves_measured_end_timestamp(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.TOOL_CALL,
                ts=100.0,
                payload={"tool": "Bash", "duration_ms": 250},
            )
        ]
        spans = to_otel_spans(events, session_id="tr_duration")

        assert spans[0]["startTimeUnixNano"] == 100_000_000_000
        assert spans[0]["endTimeUnixNano"] == 100_250_000_000
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["onmc.duration.estimated"]["boolValue"] is False

    def test_otel_span_preserves_measured_end_ts(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.TOOL_CALL,
                ts=100.0,
                payload={"tool": "Bash", "end_ts": 101.5},
            )
        ]
        spans = to_otel_spans(events, session_id="tr_end_ts")

        assert spans[0]["startTimeUnixNano"] == 100_000_000_000
        assert spans[0]["endTimeUnixNano"] == 101_500_000_000
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["onmc.duration.estimated"]["boolValue"] is False

    def test_otel_span_marks_default_duration_as_estimated(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [TraceEvent(kind=TraceEventKind.TOOL_CALL, ts=100.0, payload={})]
        spans = to_otel_spans(events, session_id="tr_default_duration")

        assert spans[0]["startTimeUnixNano"] == 100_000_000_000
        assert spans[0]["endTimeUnixNano"] == 100_001_000_000
        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["onmc.duration.estimated"]["boolValue"] is True
        assert (
            attr_map["onmc.duration.estimate_reason"]["stringValue"]
            == "instant_event_default_1ms"
        )

    def test_otel_span_maps_runtime_node_to_agent_execution(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=100.0,
                payload={
                    "backend": "native",
                    "run_id": "run-1",
                    "node_id": "execute",
                    "node_kind": "agent",
                    "status": "succeeded",
                    "side_effecting": True,
                    "approval_required": False,
                    "retry_attempts": 2,
                    "dependencies": ["plan"],
                    "evidence_count": 2,
                    "evidence_kinds": ["completion", "mutation"],
                    "digest_evidence_count": 1,
                    "completion_evidence_count": 1,
                    "capabilities": {
                        "tools": ["edit"],
                        "commands": [["pytest", "tests/unit"]],
                        "filesystem_write": True,
                        "network": False,
                        "secrets": ["ANTHROPIC_API_KEY"],
                    },
                    "duration_ms": 25,
                },
            )
        ]
        spans = to_otel_spans(events, session_id="tr_runtime_node")

        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["gen_ai.operation.name"]["stringValue"] == "execute_agent"
        assert attr_map["onmc.event_kind"]["stringValue"] == "runtime_node"
        assert attr_map["onmc.duration.estimated"]["boolValue"] is False
        assert attr_map["onmc.runtime.backend"]["stringValue"] == "native"
        assert attr_map["onmc.runtime.run_id"]["stringValue"] == "run-1"
        assert attr_map["onmc.runtime.node_id"]["stringValue"] == "execute"
        assert attr_map["onmc.runtime.node.kind"]["stringValue"] == "agent"
        assert attr_map["onmc.runtime.node.status"]["stringValue"] == "succeeded"
        assert attr_map["onmc.runtime.node.side_effecting"]["boolValue"] is True
        assert attr_map["onmc.runtime.node.retry_attempts"]["intValue"] == 2
        assert attr_map["onmc.runtime.node.evidence_count"]["intValue"] == 2
        assert attr_map["onmc.runtime.node.digest_evidence_count"]["intValue"] == 1
        assert attr_map["onmc.runtime.node.completion_evidence_count"]["intValue"] == 1
        assert attr_map["onmc.runtime.capabilities.filesystem_write"]["boolValue"] is True
        assert attr_map["onmc.runtime.capabilities.secret_count"]["intValue"] == 1
        assert attr_map["onmc.runtime.node.dependencies"]["arrayValue"]["values"] == [
            {"stringValue": "plan"}
        ]
        assert attr_map["onmc.runtime.node.evidence_kinds"]["arrayValue"]["values"] == [
            {"stringValue": "completion"},
            {"stringValue": "mutation"},
        ]
        assert attr_map["onmc.runtime.capabilities.commands"]["arrayValue"]["values"] == [
            {"stringValue": "pytest tests/unit"}
        ]

    def test_otel_span_maps_runtime_run_to_agent_invocation(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.RUNTIME_RUN,
                ts=100.0,
                payload={
                    "backend": "native",
                    "run_id": "run-1",
                    "status": "completed",
                    "spec_digest": "abc123",
                    "node_count": 3,
                    "result_count": 3,
                    "max_workers": 2,
                    "duration_ms": 50,
                },
            )
        ]
        spans = to_otel_spans(events, session_id="tr_runtime_run")

        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert attr_map["gen_ai.operation.name"]["stringValue"] == "invoke_agent"
        assert attr_map["onmc.event_kind"]["stringValue"] == "runtime_run"
        assert attr_map["onmc.runtime.backend"]["stringValue"] == "native"
        assert attr_map["onmc.runtime.run_id"]["stringValue"] == "run-1"
        assert attr_map["onmc.runtime.run.status"]["stringValue"] == "completed"
        assert attr_map["onmc.runtime.run.spec_digest"]["stringValue"] == "abc123"
        assert attr_map["onmc.runtime.run.node_count"]["intValue"] == 3
        assert attr_map["onmc.runtime.run.result_count"]["intValue"] == 3
        assert attr_map["onmc.runtime.run.max_workers"]["intValue"] == 2
        assert spans[0]["status"]["code"] == 1

    @pytest.mark.parametrize("status", ["cancelled", "failed"])
    def test_otel_span_marks_terminal_runtime_run_as_error(self, status: str) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.RUNTIME_RUN,
                ts=100.0,
                payload={
                    "run_id": "run-1",
                    "status": status,
                    "error": "operator stopped run",
                },
            )
        ]
        spans = to_otel_spans(events, session_id=f"tr_runtime_run_{status}")

        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert spans[0]["status"]["code"] == 2
        assert spans[0]["status"]["message"] == "operator stopped run"
        assert attr_map["onmc.runtime.run.status"]["stringValue"] == status

    def test_otel_span_marks_failed_runtime_node_as_error(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=100.0,
                payload={"node_id": "verify", "status": "failed", "error": "tests failed"},
            )
        ]
        spans = to_otel_spans(events, session_id="tr_runtime_failed")

        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert spans[0]["status"]["code"] == 2
        assert spans[0]["status"]["message"] == "tests failed"
        assert attr_map["onmc.runtime.node.status"]["stringValue"] == "failed"
        assert attr_map["onmc.runtime.node.error"]["stringValue"] == "tests failed"

    @pytest.mark.parametrize("status", ["cancelled", "skipped"])
    def test_otel_span_marks_terminal_runtime_node_cancellation_as_error(
        self,
        status: str,
    ) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=100.0,
                payload={
                    "node_id": "execute",
                    "status": status,
                    "error": "operator cancelled",
                },
            )
        ]
        spans = to_otel_spans(events, session_id=f"tr_runtime_{status}")

        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert spans[0]["status"]["code"] == 2
        assert spans[0]["status"]["message"] == "operator cancelled"
        assert attr_map["onmc.runtime.node.status"]["stringValue"] == status

    def test_otel_span_keeps_runtime_approval_interrupt_non_error(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [
            TraceEvent(
                kind=TraceEventKind.RUNTIME_NODE,
                ts=100.0,
                payload={
                    "node_id": "deploy",
                    "status": "interrupted",
                    "error": "approval required before deploy",
                },
            )
        ]
        spans = to_otel_spans(events, session_id="tr_runtime_interrupted")

        attr_map = {a["key"]: a["value"] for a in spans[0]["attributes"]}
        assert spans[0]["status"]["code"] == 1
        assert "message" not in spans[0]["status"]
        assert attr_map["onmc.runtime.node.status"]["stringValue"] == "interrupted"
        assert (
            attr_map["onmc.runtime.node.error"]["stringValue"]
            == "approval required before deploy"
        )

    def test_otel_span_error_status_for_failure(self) -> None:
        from oh_no_my_claudecode.trace.otel import to_otel_spans

        events = [_ev(TraceEventKind.TOOL_FAILURE, tool="Bash", target="broken")]
        spans = to_otel_spans(events, session_id="tr_err")
        assert spans[0]["status"]["code"] == 2  # ERROR
