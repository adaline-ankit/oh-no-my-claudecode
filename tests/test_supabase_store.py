"""Supabase store: PostgREST calls shaped right, fully offline via fake transport."""

from __future__ import annotations

import json

import pytest

from oh_no_my_claudecode.learning.attribution import LiftVerdict, MemoryLift
from oh_no_my_claudecode.learning.supabase_store import SupabaseEarnedMemoryStore


class _Recorder:
    def __init__(self, status: int = 201) -> None:
        self.calls: list[tuple[str, str, dict[str, str], object]] = []
        self.status = status

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None):
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        return self.status, "" if self.status < 300 else '{"message":"boom"}'


class _StubMemory:
    """Sink contract is memory_id + to_dict(); the full model chain isn't needed."""

    memory_id = "mem_1"

    def to_dict(self) -> dict[str, object]:
        return {
            "memory_id": "mem_1",
            "kind": "repo-fact",
            "content": "the actor field needs a user: prefix",
            "scope": {"repos": ["acme/api"]},
            "provenance": {"trace_ids": ["run-1"]},
            "version": 1,
            "promotion": {"reason": "held-out +0.3"},
        }


def _memory() -> _StubMemory:
    return _StubMemory()


def _store(recorder: _Recorder) -> SupabaseEarnedMemoryStore:
    return SupabaseEarnedMemoryStore(url="https://proj.supabase.co", key="k", transport=recorder)


def test_write_posts_promotion_trail_to_earned_memories() -> None:
    rec = _Recorder()
    assert _store(rec).write(_memory()) == "mem_1"
    method, url, headers, payload = rec.calls[0]
    assert (method, url) == ("POST", "https://proj.supabase.co/rest/v1/earned_memories")
    assert headers["apikey"] == "k" and headers["Authorization"] == "Bearer k"
    assert payload["memory_id"] == "mem_1"
    assert "promotion" in payload and "provenance" in payload  # trail persisted


def test_write_failure_raises_not_silently_drops() -> None:
    with pytest.raises(RuntimeError, match="supabase write failed"):
        _store(_Recorder(status=401)).write(_memory())


def test_remove_is_retirement_timestamp_never_delete() -> None:
    rec = _Recorder(status=204)
    assert _store(rec).remove("mem_1") is True
    method, url, _, payload = rec.calls[0]
    assert method == "PATCH" and url.endswith("earned_memories?memory_id=eq.mem_1")
    assert payload == {"retired_at": "now()"}


def test_ledger_and_receipt_rows_shaped_for_schema() -> None:
    rec = _Recorder()
    store = _store(rec)
    n = store.record_ledger([MemoryLift("mem_1", 0.3, (0.1, 0.5), 10, LiftVerdict.EARNING)])
    assert n == 1
    _, url, _, rows = rec.calls[0]
    assert url.endswith("/memory_ledger")
    assert rows[0] == {
        "memory_id": "mem_1",
        "mean_lift": 0.3,
        "ci_low": 0.1,
        "ci_high": 0.5,
        "n_tasks": 10,
        "verdict": "earning",
    }
    store.record_receipt("a" * 64, "acme/api", True, {"payloadType": "x"})
    _, url2, _, row2 = rec.calls[1]
    assert url2.endswith("/receipts") and row2["verified"] is True
