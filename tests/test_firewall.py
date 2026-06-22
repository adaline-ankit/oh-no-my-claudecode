"""Tests for the context firewall — hooks/ routing of operational noise to sink.

Coverage:
- is_firewall_enabled() respects ONMC_FIREWALL env var (kill-switch).
- firewall_emit() routes to the sink when firewall is ON.
- firewall_emit() is a no-op when ONMC_FIREWALL=0.
- firewall_emit() is fully exception-safe (sink error cannot propagate).
- compile_prompt_recall_safe: recall in output; sink gets event; ONMC_FIREWALL=0 skips sink.
- compile_boot_digest: sink gets recall_surfaced event; ONMC_FIREWALL=0 skips; content unchanged.
- compile_pretool_warning: sink gets danger_blocked; warning still in output; ONMC_FIREWALL=0 skips.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from oh_no_my_claudecode.hooks.firewall import firewall_emit, is_firewall_enabled
from oh_no_my_claudecode.hooks.pre_tool_use import compile_pretool_warning
from oh_no_my_claudecode.hooks.prompt_recall import compile_prompt_recall_safe
from oh_no_my_claudecode.models import (
    FileStat,
    MemoryEntry,
    MemoryKind,
    SourceType,
    TaskRecord,
    TaskStatus,
)
from oh_no_my_claudecode.notify import EventKind, FileSink, NotifyEvent
from oh_no_my_claudecode.storage import SQLiteStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_storage(tmp_path: Path) -> SQLiteStorage:
    db = SQLiteStorage(tmp_path / ".onmc" / "memory.db")
    db.initialize()
    return db


def _seed_memory(storage: SQLiteStorage, path: str = "src/cache.py") -> MemoryEntry:
    entry = MemoryEntry(
        id="mem-cache-1",
        kind=MemoryKind.INVARIANT,
        title="Cache invalidation boundary",
        summary="All cache invalidations must go through the shared boundary module.",
        details="Direct cache writes from workers bypass the boundary and cause stale reads.",
        source_type=SourceType.DOC,
        source_ref=path,
        tags=["cache", "invariant"],
        confidence=0.9,
        feedback_score=0.3,
        created_at=_now(),
        updated_at=_now(),
        staleness=None,
    )
    storage.upsert_memories([entry])
    return entry


def _read_sink_events(tmp_path: Path) -> list[dict[str, object]]:
    """Read all events from the FileSink log."""
    log_path = FileSink(tmp_path).log_path
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]


# ---------------------------------------------------------------------------
# is_firewall_enabled — kill-switch
# ---------------------------------------------------------------------------


class TestIsFirewallEnabled:
    def test_default_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        assert is_firewall_enabled() is True

    def test_zero_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONMC_FIREWALL", "0")
        assert is_firewall_enabled() is False

    def test_false_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONMC_FIREWALL", "false")
        assert is_firewall_enabled() is False

    def test_no_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONMC_FIREWALL", "no")
        assert is_firewall_enabled() is False

    def test_one_enables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONMC_FIREWALL", "1")
        assert is_firewall_enabled() is True

    def test_true_enables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONMC_FIREWALL", "true")
        assert is_firewall_enabled() is True

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONMC_FIREWALL", "FALSE")
        assert is_firewall_enabled() is False
        monkeypatch.setenv("ONMC_FIREWALL", "NO")
        assert is_firewall_enabled() is False


# ---------------------------------------------------------------------------
# firewall_emit — routing and kill-switch
# ---------------------------------------------------------------------------


class TestFirewallEmit:
    def test_routes_event_to_file_sink_when_firewall_on(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        event = NotifyEvent(kind=EventKind.GENERIC, title="test firewall emit")
        firewall_emit(tmp_path, event)

        events = _read_sink_events(tmp_path)
        assert len(events) == 1
        assert events[0]["title"] == "test firewall emit"

    def test_noop_when_firewall_off(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ONMC_FIREWALL", "0")
        event = NotifyEvent(kind=EventKind.GENERIC, title="should not appear")
        firewall_emit(tmp_path, event)

        events = _read_sink_events(tmp_path)
        assert events == []

    def test_exception_safe_on_bad_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        bad_root = Path("/does/not/exist/at/all")
        event = NotifyEvent(kind=EventKind.GENERIC, title="should not raise")
        firewall_emit(bad_root, event)  # must not raise

    def test_exception_safe_when_emit_event_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        event = NotifyEvent(kind=EventKind.GENERIC, title="boom")
        with patch(
            "oh_no_my_claudecode.hooks.firewall.emit_event",
            side_effect=RuntimeError("simulated sink failure"),
        ):
            firewall_emit(tmp_path, event)  # must not raise


# ---------------------------------------------------------------------------
# compile_prompt_recall_safe — recall content + firewall routing
# ---------------------------------------------------------------------------


class TestPromptRecallFirewall:
    def test_recall_content_still_in_output_with_firewall_on(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """High-value recall must remain in the returned text regardless of firewall."""
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        storage = _make_storage(tmp_path)
        _seed_memory(storage)

        text, tokens = compile_prompt_recall_safe(
            storage, "cache invalidation", repo_root=tmp_path
        )

        assert text != ""
        assert tokens > 0
        assert "cache" in text.lower() or "Cache" in text

    def test_sink_receives_recall_surfaced_event(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        storage = _make_storage(tmp_path)
        _seed_memory(storage)

        text, _ = compile_prompt_recall_safe(
            storage, "cache invalidation", repo_root=tmp_path
        )

        if text:  # only if recall was produced
            events = _read_sink_events(tmp_path)
            kinds = [e["kind"] for e in events]
            assert EventKind.RECALL_SURFACED in kinds

    def test_no_sink_event_when_firewall_off(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ONMC_FIREWALL", "0")
        storage = _make_storage(tmp_path)
        _seed_memory(storage)

        compile_prompt_recall_safe(storage, "cache invalidation", repo_root=tmp_path)

        events = _read_sink_events(tmp_path)
        assert events == []

    def test_no_sink_event_when_no_recall(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When no memories match, no event is emitted."""
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        storage = _make_storage(tmp_path)
        # No memories seeded.

        compile_prompt_recall_safe(storage, "xyzzyx frabbitz", repo_root=tmp_path)

        events = _read_sink_events(tmp_path)
        assert events == []

    def test_hook_exits_gracefully_when_sink_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A sink failure must not propagate — recall result must still be returned."""
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        storage = _make_storage(tmp_path)
        _seed_memory(storage)

        with patch(
            "oh_no_my_claudecode.hooks.firewall.emit_event",
            side_effect=RuntimeError("sink down"),
        ):
            text, tokens = compile_prompt_recall_safe(
                storage, "cache invalidation", repo_root=tmp_path
            )

        # Result must still be valid even though the sink errored.
        assert isinstance(text, str)
        assert isinstance(tokens, int)

    def test_defaults_to_cwd_when_repo_root_omitted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """repo_root=None must not raise — it falls back to Path.cwd()."""
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        storage = _make_storage(tmp_path)

        text, tokens = compile_prompt_recall_safe(storage, "cache", repo_root=None)
        assert isinstance(text, str)
        assert isinstance(tokens, int)


# ---------------------------------------------------------------------------
# compile_boot_digest — digest content + firewall routing
# ---------------------------------------------------------------------------


class TestBootDigestFirewall:
    def _make_invariant(self, mid: str = "inv1") -> MemoryEntry:
        return MemoryEntry(
            id=mid,
            kind=MemoryKind.INVARIANT,
            title="Cache boundary invariant",
            summary="Never bypass the cache boundary from worker code.",
            details="Direct writes cause stale read hazards.",
            source_type=SourceType.MANUAL,
            source_ref="src/cache.py",
            tags=["cache"],
            confidence=0.9,
            feedback_score=0.0,
            created_at=_now(),
            updated_at=_now(),
        )

    def _make_task(self) -> TaskRecord:
        return TaskRecord(
            task_id="task-1",
            title="Fix the cache bug",
            description="Tracked in #42.",
            status=TaskStatus.ACTIVE,
            labels=[],
            repo_root="/repo",
            branch="main",
            created_at=_now(),
            updated_at=_now(),
        )

    def test_digest_content_unchanged_with_firewall(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from oh_no_my_claudecode.hooks.boot_digest import compile_boot_digest

        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        memories = [self._make_invariant()]
        tasks = [self._make_task()]

        text, tokens = compile_boot_digest(
            memories=memories,
            tasks=tasks,
            repo_name="myrepo",
            repo_root=tmp_path,
        )

        assert text != ""
        assert tokens > 0

    def test_sink_receives_recall_surfaced_on_digest(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from oh_no_my_claudecode.hooks.boot_digest import compile_boot_digest

        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        memories = [self._make_invariant()]

        text, _ = compile_boot_digest(
            memories=memories,
            tasks=[],
            repo_name="myrepo",
            repo_root=tmp_path,
        )

        if text:
            events = _read_sink_events(tmp_path)
            kinds = [e["kind"] for e in events]
            assert EventKind.RECALL_SURFACED in kinds

    def test_no_sink_event_when_firewall_off(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from oh_no_my_claudecode.hooks.boot_digest import compile_boot_digest

        monkeypatch.setenv("ONMC_FIREWALL", "0")
        memories = [self._make_invariant()]

        compile_boot_digest(
            memories=memories,
            tasks=[],
            repo_name="myrepo",
            repo_root=tmp_path,
        )

        events = _read_sink_events(tmp_path)
        assert events == []

    def test_no_sink_event_when_digest_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When there is nothing to digest, no event is emitted."""
        from oh_no_my_claudecode.hooks.boot_digest import compile_boot_digest

        monkeypatch.delenv("ONMC_FIREWALL", raising=False)

        text, tokens = compile_boot_digest(
            memories=[],
            tasks=[],
            repo_name="emptyrepo",
            repo_root=tmp_path,
        )

        assert text == ""
        assert tokens == 0
        events = _read_sink_events(tmp_path)
        assert events == []

    def test_sink_exception_does_not_break_digest(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from oh_no_my_claudecode.hooks.boot_digest import compile_boot_digest

        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        memories = [self._make_invariant()]

        with patch(
            "oh_no_my_claudecode.hooks.firewall.emit_event",
            side_effect=RuntimeError("sink crash"),
        ):
            text, tokens = compile_boot_digest(
                memories=memories,
                tasks=[],
                repo_name="myrepo",
                repo_root=tmp_path,
            )

        assert isinstance(text, str)
        assert isinstance(tokens, int)

    def test_defaults_to_cwd_when_repo_root_omitted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from oh_no_my_claudecode.hooks.boot_digest import compile_boot_digest

        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        memories = [self._make_invariant()]

        text, tokens = compile_boot_digest(
            memories=memories,
            tasks=[],
            repo_name="myrepo",
            # repo_root omitted — falls back to Path.cwd()
        )

        assert isinstance(text, str)
        assert isinstance(tokens, int)


# ---------------------------------------------------------------------------
# compile_pretool_warning — danger signal in context + sink routing
# ---------------------------------------------------------------------------


class TestPreToolFirewall:
    def test_warning_content_preserved_in_context(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The in-context warning must still be returned (real safety signal)."""
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        repo = tmp_path / "repo"
        repo.mkdir()
        storage = _make_storage(tmp_path)
        storage.upsert_file_stats(
            [FileStat(path="src/hotspot.py", change_count=15, recent_change_count=4)]
        )

        md, n = compile_pretool_warning(storage, repo, "src/hotspot.py")

        assert n >= 1
        assert "HIGH-CHURN" in md

    def test_sink_receives_danger_blocked_event(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        repo = tmp_path / "repo"
        repo.mkdir()
        storage = _make_storage(tmp_path)
        storage.upsert_file_stats(
            [FileStat(path="src/hotspot.py", change_count=15, recent_change_count=4)]
        )

        md, n = compile_pretool_warning(storage, repo, "src/hotspot.py")

        assert n >= 1
        # The firewall_emit target is repo_root (the repo dir), so read sink from there.
        events = _read_sink_events(repo)
        kinds = [e["kind"] for e in events]
        assert EventKind.DANGER_BLOCKED in kinds

    def test_sink_event_detail_describes_signals(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        repo = tmp_path / "repo"
        repo.mkdir()
        storage = _make_storage(tmp_path)
        storage.upsert_file_stats(
            [FileStat(path="src/hotspot.py", change_count=10, recent_change_count=5)]
        )
        storage.upsert_memories(
            [
                MemoryEntry(
                    id="inv1",
                    kind=MemoryKind.INVARIANT,
                    title="Key invariant",
                    summary="Lock before mutating state.",
                    details="Lock before mutating state.",
                    source_type=SourceType.MANUAL,
                    source_ref="src/hotspot.py",
                    confidence=0.9,
                    created_at=_now(),
                    updated_at=_now(),
                )
            ]
        )

        compile_pretool_warning(storage, repo, "src/hotspot.py")

        events = _read_sink_events(repo)
        danger_events = [e for e in events if e["kind"] == EventKind.DANGER_BLOCKED]
        assert danger_events
        detail = str(danger_events[0].get("detail", ""))
        # detail should mention at least one signal type
        assert "high-churn" in detail or "invariant" in detail

    def test_no_sink_event_when_firewall_off(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ONMC_FIREWALL", "0")
        repo = tmp_path / "repo"
        repo.mkdir()
        storage = _make_storage(tmp_path)
        storage.upsert_file_stats(
            [FileStat(path="src/hotspot.py", change_count=15, recent_change_count=4)]
        )

        md, n = compile_pretool_warning(storage, repo, "src/hotspot.py")

        assert n >= 1  # warning still produced in context
        assert "HIGH-CHURN" in md  # content unchanged
        events = _read_sink_events(repo)
        assert events == []  # no sink event

    def test_no_sink_event_when_no_danger(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        repo = tmp_path / "repo"
        repo.mkdir()
        storage = _make_storage(tmp_path)

        md, n = compile_pretool_warning(storage, repo, "src/unknown_clean.py")

        assert n == 0
        assert md == ""
        events = _read_sink_events(repo)
        assert events == []

    def test_sink_error_does_not_break_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ONMC_FIREWALL", raising=False)
        repo = tmp_path / "repo"
        repo.mkdir()
        storage = _make_storage(tmp_path)
        storage.upsert_file_stats(
            [FileStat(path="src/hotspot.py", change_count=15, recent_change_count=4)]
        )

        with patch(
            "oh_no_my_claudecode.hooks.firewall.emit_event",
            side_effect=RuntimeError("sink crash"),
        ):
            md, n = compile_pretool_warning(storage, repo, "src/hotspot.py")

        # Warning must still be returned even if sink errors.
        assert n >= 1
        assert "HIGH-CHURN" in md
