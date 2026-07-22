from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from oh_no_my_claudecode.durable_runtime import (
    CorruptRunError,
    EnvironmentSnapshot,
    GitSnapshot,
    IdempotencyConflictError,
    InvalidTransitionError,
    LeaseConflictError,
    LeaseExpiredError,
    NodeState,
    RetryClass,
    RunState,
    RuntimeStore,
)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 22, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def _store(tmp_path: Path, clock: Clock) -> RuntimeStore:
    return RuntimeStore(tmp_path / "runtime", clock=clock)


def _create(store: RuntimeStore, run_id: str = "run-1") -> None:
    store.create_run(
        run_id,
        node_ids=["plan", "build"],
        environment=EnvironmentSnapshot(
            python_version="3.11.9",
            platform="test-os",
            executable="/python",
            cwd="/repo",
        ),
        git=GitSnapshot(root="/repo", head="abc123", branch="feature/runtime", dirty=False),
        idempotency_key="create-1",
    )


def test_crash_reload_replays_events_beyond_stale_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    store = _store(tmp_path, clock)
    _create(store)
    store.start("run-1", idempotency_key="start-1")

    original = store._write_checkpoint
    monkeypatch.setattr(store, "_write_checkpoint", lambda snapshot: None)
    store.start_node("run-1", "plan", idempotency_key="node-start-1")
    monkeypatch.setattr(store, "_write_checkpoint", original)

    resumed = _store(tmp_path, clock).load("run-1")
    assert resumed.state is RunState.RUNNING
    assert resumed.nodes["plan"].state is NodeState.RUNNING
    assert resumed.last_sequence == 3
    assert len(_store(tmp_path, clock).events("run-1")) == 3


def test_duplicate_idempotency_key_returns_same_result_without_new_event(tmp_path: Path) -> None:
    clock = Clock()
    store = _store(tmp_path, clock)
    _create(store)

    first = store.start("run-1", idempotency_key="start-once")
    second = store.start("run-1", idempotency_key="start-once")

    assert second == first
    assert len(store.events("run-1")) == 2
    with pytest.raises(IdempotencyConflictError):
        store.pause("run-1", reason="different operation", idempotency_key="start-once")


def test_pause_wait_approve_cancel_transitions_are_persisted(tmp_path: Path) -> None:
    clock = Clock()
    store = _store(tmp_path, clock)
    _create(store)
    store.start("run-1", idempotency_key="start")
    store.pause("run-1", reason="operator", idempotency_key="pause")
    assert store.load("run-1").state is RunState.PAUSED
    store.resume("run-1", idempotency_key="resume-1")
    store.wait("run-1", reason="dependency", idempotency_key="wait")
    store.request_approval("run-1", reason="deploy", idempotency_key="request")
    approved = store.approve(
        "run-1", approved_by="maintainer", idempotency_key="approve"
    )
    assert approved.state is RunState.RUNNING
    assert approved.approvals[-1].approved_by == "maintainer"
    cancelled = store.cancel("run-1", reason="superseded", idempotency_key="cancel")
    assert cancelled.state is RunState.CANCELLED
    with pytest.raises(InvalidTransitionError):
        store.resume("run-1", idempotency_key="resume-terminal")


def test_node_transitions_reject_invalid_edges(tmp_path: Path) -> None:
    clock = Clock()
    store = _store(tmp_path, clock)
    _create(store)
    store.start("run-1", idempotency_key="start")

    with pytest.raises(InvalidTransitionError):
        store.complete_node("run-1", "plan", idempotency_key="complete-pending")
    store.start_node("run-1", "plan", idempotency_key="node-start")
    store.pause_node("run-1", "plan", reason="operator", idempotency_key="node-pause")
    store.resume_node("run-1", "plan", idempotency_key="node-resume")
    done = store.complete_node("run-1", "plan", idempotency_key="node-complete")
    assert done.nodes["plan"].state is NodeState.SUCCEEDED


def test_lease_heartbeat_and_expiry_are_deterministic(tmp_path: Path) -> None:
    clock = Clock()
    store = _store(tmp_path, clock)
    _create(store)

    lease = store.acquire_lease(
        "run-1", "plan", owner="worker-a", ttl_seconds=30, idempotency_key="lease-a"
    )
    with pytest.raises(LeaseConflictError):
        store.acquire_lease(
            "run-1", "plan", owner="worker-b", ttl_seconds=30, idempotency_key="lease-b"
        )
    clock.advance(20)
    renewed = store.heartbeat(
        "run-1", "plan", token=lease.token, ttl_seconds=30, idempotency_key="heartbeat-a"
    )
    assert renewed.expires_at == clock.now + timedelta(seconds=30)
    clock.advance(31)
    expired = store.expire_leases("run-1", idempotency_key="expire")
    assert expired.nodes["plan"].lease is None
    with pytest.raises(LeaseExpiredError):
        store.heartbeat(
            "run-1", "plan", token=lease.token, ttl_seconds=30, idempotency_key="late"
        )
    replacement = store.acquire_lease(
        "run-1", "plan", owner="worker-b", ttl_seconds=10, idempotency_key="lease-c"
    )
    assert replacement.owner == "worker-b"


def test_retry_classification_records_exponential_backoff(tmp_path: Path) -> None:
    clock = Clock()
    store = _store(tmp_path, clock)
    _create(store)
    store.start("run-1", idempotency_key="start")
    store.start_node("run-1", "plan", idempotency_key="node-start")

    transient = store.record_retry(
        "run-1",
        "plan",
        classification=RetryClass.TRANSIENT,
        reason="network reset",
        base_delay_seconds=5,
        max_delay_seconds=60,
        idempotency_key="retry-1",
    )
    assert transient.attempt == 1
    assert transient.retryable is True
    assert transient.backoff_seconds == 5
    assert transient.not_before == clock.now + timedelta(seconds=5)
    clock.advance(1)
    duplicate = store.record_retry(
        "run-1",
        "plan",
        classification=RetryClass.TRANSIENT,
        reason="network reset",
        base_delay_seconds=5,
        max_delay_seconds=60,
        idempotency_key="retry-1",
    )
    assert duplicate == transient
    assert len(store.load("run-1").nodes["plan"].retry_history) == 1

    permanent = store.record_retry(
        "run-1",
        "plan",
        classification=RetryClass.PERMANENT,
        reason="invalid input",
        base_delay_seconds=5,
        max_delay_seconds=60,
        idempotency_key="retry-2",
    )
    assert permanent.attempt == 2
    assert permanent.retryable is False
    assert permanent.backoff_seconds is None
    assert permanent.not_before is None


def test_environment_and_git_metadata_survive_exact_reload(tmp_path: Path) -> None:
    clock = Clock()
    store = _store(tmp_path, clock)
    _create(store)

    loaded = _store(tmp_path, clock).load("run-1")
    assert loaded.environment.python_version == "3.11.9"
    assert loaded.git.head == "abc123"
    assert loaded.git.dirty is False


def test_tampered_event_is_detected_even_when_checkpoint_exists(tmp_path: Path) -> None:
    clock = Clock()
    store = _store(tmp_path, clock)
    _create(store)
    store.start("run-1", idempotency_key="start")

    event_path = tmp_path / "runtime" / "runs" / "run-1" / "events.jsonl"
    lines = event_path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["payload"]["node_ids"] = ["evil"]
    lines[0] = json.dumps(event, sort_keys=True, separators=(",", ":"))
    event_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(CorruptRunError, match="hash"):
        store.load("run-1")


def test_truncated_event_and_tampered_checkpoint_are_detected(tmp_path: Path) -> None:
    clock = Clock()
    store = _store(tmp_path, clock)
    _create(store)
    run_dir = tmp_path / "runtime" / "runs" / "run-1"

    with (run_dir / "events.jsonl").open("ab") as stream:
        stream.write(b'{"sequence":2')
    with pytest.raises(CorruptRunError, match="event JSON"):
        store.load("run-1")

    # Restore a valid store, then make the checkpoint disagree with the log head.
    other = _store(tmp_path / "other", clock)
    _create(other)
    checkpoint_path = tmp_path / "other" / "runtime" / "runs" / "run-1" / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["last_hash"] = "0" * 64
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(CorruptRunError, match="checkpoint"):
        other.load("run-1")
