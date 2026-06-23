"""Tests for the onmc Replay Lab (onmc replay).

Covers:
- replay_session with seeded events + brain that surfaces recall on relevant step
- replay_session with_memory=False → no recall/guard hits, zero injected_chars
- compare_replay shows positive with-vs-without delta (memory changed ≥1 step)
- a recorded FAILED_APPROACH dead-end surfaces in guard during replay
- empty session → graceful zeroes, no error
- resolve-by-session-id AND resolve-by-path both work (service.replay)
- --compare, --without-memory, --json shapes (CLI via invoke)
- deterministic: same events + same storage → same report on two calls
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.replay.lab import compare_replay, replay_session
from oh_no_my_claudecode.replay.models import ReplayComparison, ReplayReport
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.trace.models import TraceEvent, TraceEventKind
from oh_no_my_claudecode.trace.recorder import (
    record_trace_event,
    start_session,
    stop_session,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = time.time()


def _ev(kind: str, **payload: object) -> TraceEvent:
    return TraceEvent(kind=kind, ts=_NOW, payload=dict(payload))


def _seeded_storage(tmp_path: Path, *, title: str = "cache invalidation bug") -> SQLiteStorage:
    """Return an initialised SQLiteStorage with one FAILED_APPROACH memory."""
    from oh_no_my_claudecode.config import database_path, default_config
    from oh_no_my_claudecode.models import MemoryEntry
    from oh_no_my_claudecode.utils.text import stable_id
    from oh_no_my_claudecode.utils.time import utc_now

    config = default_config(tmp_path)
    storage = SQLiteStorage(database_path(config, tmp_path))
    storage.initialize()

    now = utc_now()
    entry = MemoryEntry(
        id=stable_id("failed_approach", title, "cache", "test", prefix="test"),
        kind=MemoryKind.FAILED_APPROACH,
        title=title,
        summary="Tried bypassing cache boundary from worker; broke invalidation.",
        details="Do not bypass the cache boundary from workers — invariant violated.",
        source_type=SourceType.MANUAL,
        source_ref="test:replay",
        tags=["cache", "invalidation", "worker"],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return storage


def _init_repo(repo: Path) -> SQLiteStorage:
    """Initialise an onmc project at *repo* and return its storage."""
    OnmcService(cwd=repo).init_project()
    from oh_no_my_claudecode.config import database_path, load_config

    config = load_config(repo)
    storage = SQLiteStorage(database_path(config, repo))
    storage.initialize()
    return storage


# ---------------------------------------------------------------------------
# replay_session — unit tests (pure function, no CLI)
# ---------------------------------------------------------------------------


class TestReplaySession:
    def test_empty_events_returns_graceful_zeroes(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path)
        report = replay_session(storage, [], session_id="tr_empty")
        assert isinstance(report, ReplayReport)
        assert report.total_steps == 0
        assert report.steps_with_recall == 0
        assert report.steps_with_deadend == 0
        assert report.mean_injected_chars == 0.0
        assert report.steps == []

    def test_with_memory_surfaces_recall_on_relevant_step(self, tmp_path: Path) -> None:
        """A memory_hit event with a query matching the seeded memory triggers recall."""
        storage = _seeded_storage(tmp_path, title="cache invalidation bug")
        events = [
            _ev(TraceEventKind.MEMORY_HIT, query="cache invalidation bypass worker"),
        ]
        report = replay_session(storage, events, with_memory=True)
        assert report.total_steps == 1
        # The seeded FAILED_APPROACH memory should match.
        assert report.steps_with_recall >= 1 or report.steps_with_deadend >= 1
        step = report.steps[0]
        assert step.query == "cache invalidation bypass worker"
        assert isinstance(step.recall_hits, int)
        assert isinstance(step.injected_chars, int)

    def test_without_memory_all_steps_zero(self, tmp_path: Path) -> None:
        """with_memory=False → every step has recall_hits=0, deadend_hits=0, injected_chars=0."""
        storage = _seeded_storage(tmp_path)
        events = [
            _ev(TraceEventKind.MEMORY_HIT, query="cache invalidation bypass worker"),
            _ev(TraceEventKind.FILE_READ, target="src/cache.py"),
            _ev(TraceEventKind.SEARCH_QUERY, target="how to invalidate cache"),
        ]
        report = replay_session(storage, events, with_memory=False)
        assert report.with_memory is False
        assert report.total_steps == 3
        for step in report.steps:
            assert step.recall_hits == 0
            assert step.deadend_hits == 0
            assert step.injected_chars == 0
        assert report.steps_with_recall == 0
        assert report.steps_with_deadend == 0
        assert report.mean_injected_chars == 0.0

    def test_deadend_surfaces_for_failed_approach(self, tmp_path: Path) -> None:
        """compile_guard surfaces FAILED_APPROACH memories — deadend_hits > 0 on match."""
        storage = _seeded_storage(tmp_path, title="cache invalidation bug")
        events = [
            _ev(TraceEventKind.TOOL_CALL, target="cache invalidation bypass worker"),
        ]
        report = replay_session(storage, events, with_memory=True)
        assert report.total_steps == 1
        step = report.steps[0]
        # Guard targets FAILED_APPROACH — should surface the seeded memory.
        assert step.deadend_hits >= 1

    def test_tokens_events_are_skipped(self, tmp_path: Path) -> None:
        """Events with no usable text payload (e.g. tokens) are excluded from steps."""
        storage = _seeded_storage(tmp_path)
        events = [
            _ev(TraceEventKind.TOKENS, total=8000),
            _ev(TraceEventKind.MEMORY_HIT, query="cache"),
        ]
        report = replay_session(storage, events)
        # Only the MEMORY_HIT event has a query — tokens event is skipped.
        assert report.total_steps == 1

    def test_file_read_event_uses_target_as_query(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path)
        events = [_ev(TraceEventKind.FILE_READ, target="src/cache.py")]
        report = replay_session(storage, events)
        assert report.total_steps == 1
        assert report.steps[0].query == "src/cache.py"

    def test_notify_recall_surfaced_uses_title(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path)
        events = [_ev(TraceEventKind.RECALL_SURFACED, title="cache bug recalled")]
        report = replay_session(storage, events)
        assert report.total_steps == 1
        assert report.steps[0].query == "cache bug recalled"

    def test_session_id_propagated(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path)
        report = replay_session(storage, [], session_id="tr_mytest01")
        assert report.session_id == "tr_mytest01"

    def test_deterministic_same_events_same_result(self, tmp_path: Path) -> None:
        """Two identical calls produce bit-for-bit identical reports."""
        storage = _seeded_storage(tmp_path)
        events = [
            _ev(TraceEventKind.MEMORY_HIT, query="cache invalidation bypass worker"),
            _ev(TraceEventKind.FILE_READ, target="src/cache.py"),
        ]
        r1 = replay_session(storage, events, with_memory=True)
        r2 = replay_session(storage, events, with_memory=True)
        assert r1.total_steps == r2.total_steps
        assert r1.steps_with_recall == r2.steps_with_recall
        assert r1.steps_with_deadend == r2.steps_with_deadend
        for s1, s2 in zip(r1.steps, r2.steps, strict=True):
            assert s1.recall_hits == s2.recall_hits
            assert s1.deadend_hits == s2.deadend_hits
            assert s1.injected_chars == s2.injected_chars

    def test_step_index_matches_event_position(self, tmp_path: Path) -> None:
        """ReplayStep.index records the original event position in the list."""
        storage = _seeded_storage(tmp_path)
        events = [
            _ev(TraceEventKind.TOKENS, total=999),  # idx 0 — skipped
            _ev(TraceEventKind.FILE_READ, target="a.py"),  # idx 1 → step with index=1
            _ev(TraceEventKind.TOKENS, total=1),  # idx 2 — skipped
            _ev(TraceEventKind.SEARCH_QUERY, target="b query"),  # idx 3 → step with index=3
        ]
        report = replay_session(storage, events)
        assert report.total_steps == 2
        assert report.steps[0].index == 1
        assert report.steps[1].index == 3


# ---------------------------------------------------------------------------
# compare_replay — unit tests
# ---------------------------------------------------------------------------


class TestCompareReplay:
    def test_compare_returns_replay_comparison(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path)
        events = [_ev(TraceEventKind.MEMORY_HIT, query="cache")]
        result = compare_replay(storage, events)
        assert isinstance(result, ReplayComparison)

    def test_with_memory_report_has_with_memory_true(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path)
        events = [_ev(TraceEventKind.FILE_READ, target="cache")]
        result = compare_replay(storage, events)
        assert result.with_memory.with_memory is True
        assert result.without_memory.with_memory is False

    def test_memory_changes_at_least_one_step_when_relevant(self, tmp_path: Path) -> None:
        """When the brain has a matching memory, compare shows ≥1 step changed."""
        storage = _seeded_storage(tmp_path, title="cache invalidation bug")
        events = [
            _ev(TraceEventKind.TOOL_CALL, target="cache invalidation bypass worker"),
        ]
        result = compare_replay(storage, events)
        changed = result.deltas.get("steps_where_context_changed", 0)
        # With memory adds injected_chars that without-memory doesn't have.
        assert int(changed) >= 1

    def test_without_memory_report_all_zeroes(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path)
        events = [
            _ev(TraceEventKind.MEMORY_HIT, query="cache invalidation bypass"),
            _ev(TraceEventKind.FILE_READ, target="src/cache.py"),
        ]
        result = compare_replay(storage, events)
        n = result.without_memory
        assert n.steps_with_recall == 0
        assert n.steps_with_deadend == 0
        assert n.mean_injected_chars == 0.0

    def test_deltas_dict_has_expected_keys(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path)
        result = compare_replay(storage, [])
        assert "steps_where_recall_added" in result.deltas
        assert "steps_where_deadend_added" in result.deltas
        assert "steps_where_context_changed" in result.deltas
        assert "mean_chars_delta" in result.deltas

    def test_empty_events_comparison_graceful(self, tmp_path: Path) -> None:
        storage = _seeded_storage(tmp_path)
        result = compare_replay(storage, [])
        assert result.with_memory.total_steps == 0
        assert result.without_memory.total_steps == 0
        for v in result.deltas.values():
            assert v == 0.0


# ---------------------------------------------------------------------------
# service.replay — resolve by session_id AND by path
# ---------------------------------------------------------------------------


class TestServiceReplay:
    def _write_session(self, repo: Path) -> str:
        """Create a real trace session with events; return session_id."""
        sid = start_session(repo, label="replay-lab-test")
        assert sid is not None
        events = [
            TraceEvent(kind=TraceEventKind.MEMORY_HIT, ts=_NOW, payload={"query": "cache bug"}),
            TraceEvent(kind=TraceEventKind.FILE_READ, ts=_NOW, payload={"target": "src/cache.py"}),
        ]
        for ev in events:
            record_trace_event(repo, ev)
        stop_session(repo)
        return sid

    def test_resolve_by_session_id(self, sample_repo: Path) -> None:
        _init_repo(sample_repo)
        sid = self._write_session(sample_repo)
        svc = OnmcService(cwd=sample_repo)
        _, result = svc.replay(sid, compare=False)
        assert isinstance(result, ReplayReport)
        assert result.session_id == sid

    def test_resolve_by_path(self, sample_repo: Path) -> None:
        _init_repo(sample_repo)
        sid = self._write_session(sample_repo)
        jsonl_path = sample_repo / ".onmc" / "traces" / f"{sid}.jsonl"
        svc = OnmcService(cwd=sample_repo)
        _, result = svc.replay(str(jsonl_path), compare=False)
        assert isinstance(result, ReplayReport)

    def test_compare_flag_returns_comparison(self, sample_repo: Path) -> None:
        _init_repo(sample_repo)
        sid = self._write_session(sample_repo)
        svc = OnmcService(cwd=sample_repo)
        _, result = svc.replay(sid, compare=True)
        assert isinstance(result, ReplayComparison)

    def test_without_memory_flag(self, sample_repo: Path) -> None:
        _init_repo(sample_repo)
        sid = self._write_session(sample_repo)
        svc = OnmcService(cwd=sample_repo)
        _, result = svc.replay(sid, compare=False, with_memory=False)
        assert isinstance(result, ReplayReport)
        assert result.with_memory is False
        for step in result.steps:
            assert step.recall_hits == 0
            assert step.injected_chars == 0

    def test_missing_session_raises_file_not_found(self, sample_repo: Path) -> None:
        _init_repo(sample_repo)
        svc = OnmcService(cwd=sample_repo)
        with pytest.raises(FileNotFoundError):
            svc.replay("tr_nonexistent_xyzxyz", compare=False)


# ---------------------------------------------------------------------------
# CLI — onmc replay run (exit codes, JSON shape, --compare, --without-memory)
# ---------------------------------------------------------------------------


class TestReplayCli:
    def _setup_session(self, repo: Path) -> str:
        """Init the repo, write a session, return the session_id."""
        OnmcService(cwd=repo).init_project()
        sid = start_session(repo, label="cli-replay-test")
        assert sid is not None
        evs = [
            TraceEvent(
                kind=TraceEventKind.MEMORY_HIT, ts=_NOW, payload={"query": "cache invalidation"}
            ),
            TraceEvent(
                kind=TraceEventKind.FILE_READ, ts=_NOW, payload={"target": "src/cache.py"}
            ),
        ]
        for ev in evs:
            record_trace_event(repo, ev)
        stop_session(repo)
        return sid

    def test_run_exits_0(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sid = self._setup_session(sample_repo)
        monkeypatch.chdir(sample_repo)
        runner = CliRunner()
        result = runner.invoke(app, ["replay", "run", sid], catch_exceptions=False)
        assert result.exit_code == 0

    def test_run_json_valid(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sid = self._setup_session(sample_repo)
        monkeypatch.chdir(sample_repo)
        runner = CliRunner()
        result = runner.invoke(app, ["replay", "run", sid, "--json"], catch_exceptions=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["kind"] == "report"
        assert "session_id" in data
        assert "total_steps" in data
        assert "steps_with_recall" in data
        assert "steps_with_deadend" in data
        assert "mean_injected_chars" in data
        assert "steps" in data
        assert isinstance(data["steps"], list)

    def test_run_json_step_shape(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sid = self._setup_session(sample_repo)
        monkeypatch.chdir(sample_repo)
        runner = CliRunner()
        result = runner.invoke(app, ["replay", "run", sid, "--json"], catch_exceptions=False)
        data = json.loads(result.output)
        for step in data["steps"]:
            assert "index" in step
            assert "query" in step
            assert "recall_hits" in step
            assert "deadend_hits" in step
            assert "injected_chars" in step

    def test_compare_json_shape(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sid = self._setup_session(sample_repo)
        monkeypatch.chdir(sample_repo)
        runner = CliRunner()
        result = runner.invoke(
            app, ["replay", "run", sid, "--compare", "--json"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["kind"] == "comparison"
        assert "with_memory" in data
        assert "without_memory" in data
        assert "deltas" in data
        assert "steps_where_recall_added" in data["deltas"]
        assert "steps_where_deadend_added" in data["deltas"]
        assert "steps_where_context_changed" in data["deltas"]
        assert "mean_chars_delta" in data["deltas"]

    def test_without_memory_json(self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sid = self._setup_session(sample_repo)
        monkeypatch.chdir(sample_repo)
        runner = CliRunner()
        result = runner.invoke(
            app, ["replay", "run", sid, "--without-memory", "--json"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["kind"] == "report"
        assert data["with_memory"] is False
        for step in data["steps"]:
            assert step["recall_hits"] == 0
            assert step["injected_chars"] == 0

    def test_missing_session_exits_nonzero(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        OnmcService(cwd=sample_repo).init_project()
        monkeypatch.chdir(sample_repo)
        runner = CliRunner()
        result = runner.invoke(app, ["replay", "run", "tr_nonexistent_xyzxyz"])
        assert result.exit_code != 0

    def test_resolve_by_path_json(
        self, sample_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = self._setup_session(sample_repo)
        monkeypatch.chdir(sample_repo)
        jsonl_path = sample_repo / ".onmc" / "traces" / f"{sid}.jsonl"
        runner = CliRunner()
        result = runner.invoke(
            app, ["replay", "run", str(jsonl_path), "--json"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["kind"] == "report"
        assert "steps" in data
