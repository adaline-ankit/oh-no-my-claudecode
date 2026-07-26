"""Append-only event store and exact-replay state machine."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.durable_runtime.metadata import capture_environment, capture_git
from oh_no_my_claudecode.durable_runtime.models import (
    Approval,
    CorruptRunError,
    EnvironmentSnapshot,
    Event,
    GitSnapshot,
    IdempotencyConflictError,
    InvalidTransitionError,
    Lease,
    LeaseConflictError,
    LeaseExpiredError,
    NodeSnapshot,
    NodeState,
    RetryClass,
    RetryMetadata,
    RunAlreadyExistsError,
    RunNotFoundError,
    RunSnapshot,
    RunState,
)

_fcntl: Any
_msvcrt: Any

try:
    import fcntl as _fcntl
except ModuleNotFoundError:  # pragma: no cover - exercised by Windows CI smoke.
    _fcntl = None
    import msvcrt as _msvcrt
else:  # pragma: no cover - platform import branch.
    _msvcrt = None

_SCHEMA_VERSION = 1
_ZERO_HASH = "0" * 64
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_RUN_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.CREATED: frozenset({RunState.RUNNING, RunState.CANCELLED}),
    RunState.RUNNING: frozenset(
        {
            RunState.PAUSED,
            RunState.WAITING,
            RunState.AWAITING_APPROVAL,
            RunState.COMPLETED,
            RunState.FAILED,
            RunState.CANCELLED,
        }
    ),
    RunState.PAUSED: frozenset({RunState.RUNNING, RunState.CANCELLED}),
    RunState.WAITING: frozenset(
        {RunState.RUNNING, RunState.AWAITING_APPROVAL, RunState.CANCELLED}
    ),
    RunState.AWAITING_APPROVAL: frozenset(
        {RunState.RUNNING, RunState.FAILED, RunState.CANCELLED}
    ),
}
_NODE_TRANSITIONS: dict[NodeState, frozenset[NodeState]] = {
    NodeState.PENDING: frozenset({NodeState.RUNNING, NodeState.CANCELLED}),
    NodeState.RUNNING: frozenset(
        {
            NodeState.PAUSED,
            NodeState.WAITING,
            NodeState.AWAITING_APPROVAL,
            NodeState.SUCCEEDED,
            NodeState.FAILED,
            NodeState.CANCELLED,
        }
    ),
    NodeState.PAUSED: frozenset({NodeState.RUNNING, NodeState.CANCELLED}),
    NodeState.WAITING: frozenset(
        {NodeState.RUNNING, NodeState.AWAITING_APPROVAL, NodeState.CANCELLED}
    ),
    NodeState.AWAITING_APPROVAL: frozenset(
        {NodeState.RUNNING, NodeState.FAILED, NodeState.CANCELLED}
    ),
}


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _lock_file(lock: Any) -> None:
    if _fcntl is not None:
        _fcntl.flock(lock.fileno(), _fcntl.LOCK_EX)
        return
    lock.seek(0)
    _msvcrt.locking(lock.fileno(), _msvcrt.LK_LOCK, 1)


def _unlock_file(lock: Any) -> None:
    if _fcntl is not None:
        _fcntl.flock(lock.fileno(), _fcntl.LOCK_UN)
        return
    lock.seek(0)
    _msvcrt.locking(lock.fileno(), _msvcrt.LK_UNLCK, 1)


def _event_body(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "hash"}


def _event_from_dict(raw: dict[str, Any]) -> Event:
    try:
        return Event(
            sequence=int(raw["sequence"]),
            event_id=str(raw["event_id"]),
            run_id=str(raw["run_id"]),
            event_type=str(raw["event_type"]),
            occurred_at=_datetime(raw["occurred_at"]),
            payload=dict(raw["payload"]),
            previous_hash=str(raw["previous_hash"]),
            hash=str(raw["hash"]),
            idempotency_key=str(raw["idempotency_key"]),
            operation_hash=str(raw["operation_hash"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CorruptRunError("invalid event schema") from exc


def _lease_to_dict(lease: Lease | None) -> dict[str, Any] | None:
    if lease is None:
        return None
    return {
        "owner": lease.owner,
        "token": lease.token,
        "acquired_at": _iso(lease.acquired_at),
        "heartbeat_at": _iso(lease.heartbeat_at),
        "expires_at": _iso(lease.expires_at),
    }


def _retry_to_dict(retry: RetryMetadata | None) -> dict[str, Any] | None:
    if retry is None:
        return None
    return {
        "attempt": retry.attempt,
        "classification": retry.classification.value,
        "retryable": retry.retryable,
        "backoff_seconds": retry.backoff_seconds,
        "not_before": _iso(retry.not_before) if retry.not_before else None,
        "reason": retry.reason,
    }


def _snapshot_to_dict(snapshot: RunSnapshot) -> dict[str, Any]:
    return {
        "run_id": snapshot.run_id,
        "state": snapshot.state.value,
        "nodes": {
            node_id: {
                "node_id": node.node_id,
                "state": node.state.value,
                "lease": _lease_to_dict(node.lease),
                "attempts": node.attempts,
                "retry": _retry_to_dict(node.retry),
                "retry_history": [_retry_to_dict(item) for item in node.retry_history],
            }
            for node_id, node in sorted(snapshot.nodes.items())
        },
        "environment": asdict(snapshot.environment),
        "git": asdict(snapshot.git),
        "created_at": _iso(snapshot.created_at),
        "updated_at": _iso(snapshot.updated_at),
        "last_sequence": snapshot.last_sequence,
        "last_hash": snapshot.last_hash,
        "approvals": [
            {"approved_by": item.approved_by, "approved_at": _iso(item.approved_at)}
            for item in snapshot.approvals
        ],
        "idempotency": dict(sorted(snapshot.idempotency.items())),
    }


class RuntimeStore:
    """Synchronous, local-first durable runtime with no background process."""

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self.root = Path(root)
        self._runs = self.root / "runs"
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_run(
        self,
        run_id: str,
        *,
        node_ids: list[str] | tuple[str, ...] = (),
        environment: EnvironmentSnapshot | None = None,
        git: GitSnapshot | None = None,
        repo: Path | None = None,
        idempotency_key: str,
    ) -> RunSnapshot:
        self._validate_id(run_id, "run")
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("node_ids must be unique")
        for node_id in node_ids:
            self._validate_id(node_id, "node")
        with self._locked(run_id, create=True):
            if self._events_path(run_id).exists():
                existing = self._load_unlocked(run_id)
                fingerprint = self._operation_hash(
                    "run_created",
                    {
                        "node_ids": list(node_ids),
                        "environment": asdict(environment or existing.environment),
                        "git": asdict(git or existing.git),
                    },
                )
                if self._check_idempotency(existing, idempotency_key, fingerprint):
                    return existing
                raise RunAlreadyExistsError(f"run {run_id!r} already exists")
            env = environment or capture_environment(repo)
            git_snapshot = git or capture_git(repo)
            payload = {
                "node_ids": list(node_ids),
                "environment": asdict(env),
                "git": asdict(git_snapshot),
            }
            return self._append_unlocked(
                run_id, None, "run_created", payload, idempotency_key=idempotency_key
            )

    def load(self, run_id: str) -> RunSnapshot:
        self._validate_id(run_id, "run")
        with self._locked(run_id):
            return self._load_unlocked(run_id)

    def events(self, run_id: str) -> tuple[Event, ...]:
        self._validate_id(run_id, "run")
        with self._locked(run_id):
            return tuple(self._read_events(run_id))

    def start(self, run_id: str, *, idempotency_key: str) -> RunSnapshot:
        return self._transition_run(run_id, RunState.RUNNING, None, idempotency_key)

    def pause(self, run_id: str, *, reason: str, idempotency_key: str) -> RunSnapshot:
        return self._transition_run(run_id, RunState.PAUSED, reason, idempotency_key)

    def wait(self, run_id: str, *, reason: str, idempotency_key: str) -> RunSnapshot:
        return self._transition_run(run_id, RunState.WAITING, reason, idempotency_key)

    def request_approval(
        self, run_id: str, *, reason: str, idempotency_key: str
    ) -> RunSnapshot:
        return self._transition_run(
            run_id, RunState.AWAITING_APPROVAL, reason, idempotency_key
        )

    def approve(
        self, run_id: str, *, approved_by: str, idempotency_key: str
    ) -> RunSnapshot:
        if not approved_by:
            raise ValueError("approved_by must not be empty")
        return self._transition_run(
            run_id,
            RunState.RUNNING,
            None,
            idempotency_key,
            approved_by=approved_by,
        )

    def resume(self, run_id: str, *, idempotency_key: str) -> RunSnapshot:
        return self._transition_run(run_id, RunState.RUNNING, None, idempotency_key)

    def complete(self, run_id: str, *, idempotency_key: str) -> RunSnapshot:
        return self._transition_run(run_id, RunState.COMPLETED, None, idempotency_key)

    def fail(self, run_id: str, *, reason: str, idempotency_key: str) -> RunSnapshot:
        return self._transition_run(run_id, RunState.FAILED, reason, idempotency_key)

    def cancel(self, run_id: str, *, reason: str, idempotency_key: str) -> RunSnapshot:
        return self._transition_run(run_id, RunState.CANCELLED, reason, idempotency_key)

    def start_node(self, run_id: str, node_id: str, *, idempotency_key: str) -> RunSnapshot:
        return self._transition_node(run_id, node_id, NodeState.RUNNING, None, idempotency_key)

    def pause_node(
        self, run_id: str, node_id: str, *, reason: str, idempotency_key: str
    ) -> RunSnapshot:
        return self._transition_node(run_id, node_id, NodeState.PAUSED, reason, idempotency_key)

    def wait_node(
        self, run_id: str, node_id: str, *, reason: str, idempotency_key: str
    ) -> RunSnapshot:
        return self._transition_node(run_id, node_id, NodeState.WAITING, reason, idempotency_key)

    def request_node_approval(
        self, run_id: str, node_id: str, *, reason: str, idempotency_key: str
    ) -> RunSnapshot:
        return self._transition_node(
            run_id, node_id, NodeState.AWAITING_APPROVAL, reason, idempotency_key
        )

    def approve_node(
        self, run_id: str, node_id: str, *, approved_by: str, idempotency_key: str
    ) -> RunSnapshot:
        if not approved_by:
            raise ValueError("approved_by must not be empty")
        return self._transition_node(
            run_id,
            node_id,
            NodeState.RUNNING,
            None,
            idempotency_key,
            approved_by=approved_by,
        )

    def resume_node(
        self, run_id: str, node_id: str, *, idempotency_key: str
    ) -> RunSnapshot:
        return self._transition_node(run_id, node_id, NodeState.RUNNING, None, idempotency_key)

    def complete_node(
        self, run_id: str, node_id: str, *, idempotency_key: str
    ) -> RunSnapshot:
        return self._transition_node(run_id, node_id, NodeState.SUCCEEDED, None, idempotency_key)

    def fail_node(
        self, run_id: str, node_id: str, *, reason: str, idempotency_key: str
    ) -> RunSnapshot:
        return self._transition_node(run_id, node_id, NodeState.FAILED, reason, idempotency_key)

    def cancel_node(
        self, run_id: str, node_id: str, *, reason: str, idempotency_key: str
    ) -> RunSnapshot:
        return self._transition_node(run_id, node_id, NodeState.CANCELLED, reason, idempotency_key)

    def acquire_lease(
        self,
        run_id: str,
        node_id: str,
        *,
        owner: str,
        ttl_seconds: float,
        idempotency_key: str,
    ) -> Lease:
        if not owner:
            raise ValueError("owner must not be empty")
        self._validate_ttl(ttl_seconds)
        with self._locked(run_id):
            snapshot = self._load_unlocked(run_id)
            fingerprint = self._operation_hash(
                "lease_acquired",
                {"node_id": node_id, "owner": owner, "ttl_seconds": ttl_seconds},
            )
            if self._check_idempotency(snapshot, idempotency_key, fingerprint):
                lease = snapshot.nodes[node_id].lease
                if lease is None:
                    raise LeaseExpiredError("the idempotent lease result is no longer active")
                return lease
            node = self._node(snapshot, node_id)
            now = self._now()
            if node.lease is not None and node.lease.expires_at > now:
                raise LeaseConflictError(f"node {node_id!r} is leased by {node.lease.owner!r}")
            token_material = (
                f"{run_id}\0{node_id}\0{owner}\0"
                f"{snapshot.last_sequence + 1}\0{idempotency_key}"
            )
            token = hashlib.sha256(
                token_material.encode()
            ).hexdigest()
            updated = self._append_unlocked(
                run_id,
                snapshot,
                "lease_acquired",
                {
                    "node_id": node_id,
                    "owner": owner,
                    "token": token,
                    "acquired_at": _iso(now),
                    "heartbeat_at": _iso(now),
                    "expires_at": _iso(now + timedelta(seconds=ttl_seconds)),
                    "ttl_seconds": ttl_seconds,
                },
                idempotency_key=idempotency_key,
            )
            lease = updated.nodes[node_id].lease
            if lease is None:
                raise CorruptRunError("lease acquisition event did not produce a lease")
            return lease

    def heartbeat(
        self,
        run_id: str,
        node_id: str,
        *,
        token: str,
        ttl_seconds: float,
        idempotency_key: str,
    ) -> Lease:
        self._validate_ttl(ttl_seconds)
        with self._locked(run_id):
            snapshot = self._load_unlocked(run_id)
            fingerprint = self._operation_hash(
                "lease_heartbeat",
                {"node_id": node_id, "token": token, "ttl_seconds": ttl_seconds},
            )
            if self._check_idempotency(snapshot, idempotency_key, fingerprint):
                lease = snapshot.nodes[node_id].lease
                if lease is None:
                    raise LeaseExpiredError("the idempotent heartbeat lease is no longer active")
                return lease
            lease = self._node(snapshot, node_id).lease
            now = self._now()
            if lease is None or lease.expires_at <= now:
                raise LeaseExpiredError(f"lease for node {node_id!r} has expired")
            if lease.token != token:
                raise LeaseConflictError("lease token does not match")
            updated = self._append_unlocked(
                run_id,
                snapshot,
                "lease_heartbeat",
                {
                    "node_id": node_id,
                    "token": token,
                    "heartbeat_at": _iso(now),
                    "expires_at": _iso(now + timedelta(seconds=ttl_seconds)),
                    "ttl_seconds": ttl_seconds,
                },
                idempotency_key=idempotency_key,
            )
            renewed = updated.nodes[node_id].lease
            if renewed is None:
                raise CorruptRunError("heartbeat event removed its lease")
            return renewed

    def release_lease(
        self,
        run_id: str,
        node_id: str,
        *,
        token: str,
        idempotency_key: str,
    ) -> RunSnapshot:
        """Release an active lease; ownership is proven by its opaque token."""
        with self._locked(run_id):
            snapshot = self._load_unlocked(run_id)
            payload = {"node_id": node_id, "token": token}
            fingerprint = self._operation_hash("lease_released", payload)
            if self._check_idempotency(snapshot, idempotency_key, fingerprint):
                return snapshot
            lease = self._node(snapshot, node_id).lease
            if lease is None or lease.expires_at <= self._now():
                raise LeaseExpiredError(f"lease for node {node_id!r} has expired")
            if lease.token != token:
                raise LeaseConflictError("lease token does not match")
            return self._append_unlocked(
                run_id,
                snapshot,
                "lease_released",
                payload,
                idempotency_key=idempotency_key,
            )

    def expire_leases(self, run_id: str, *, idempotency_key: str) -> RunSnapshot:
        with self._locked(run_id):
            snapshot = self._load_unlocked(run_id)
            now = self._now()
            node_ids = sorted(
                node_id
                for node_id, node in snapshot.nodes.items()
                if node.lease is not None and node.lease.expires_at <= now
            )
            return self._append_checked(
                run_id,
                snapshot,
                "leases_expired",
                {"node_ids": node_ids, "expired_at": _iso(now)},
                idempotency_key,
            )

    def record_retry(
        self,
        run_id: str,
        node_id: str,
        *,
        classification: RetryClass,
        reason: str,
        base_delay_seconds: float = 1,
        max_delay_seconds: float = 300,
        idempotency_key: str,
    ) -> RetryMetadata:
        if base_delay_seconds < 0 or max_delay_seconds < base_delay_seconds:
            raise ValueError("retry delays must satisfy 0 <= base <= max")
        with self._locked(run_id):
            snapshot = self._load_unlocked(run_id)
            node = self._node(snapshot, node_id)
            attempt = node.attempts + 1
            retryable = classification is not RetryClass.PERMANENT
            backoff = (
                min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
                if retryable
                else None
            )
            now = self._now()
            payload = {
                "node_id": node_id,
                "attempt": attempt,
                "classification": classification.value,
                "retryable": retryable,
                "backoff_seconds": backoff,
                "not_before": (
                    _iso(now + timedelta(seconds=backoff)) if backoff is not None else None
                ),
                "reason": reason,
                "base_delay_seconds": base_delay_seconds,
                "max_delay_seconds": max_delay_seconds,
            }
            updated = self._append_checked(
                run_id, snapshot, "retry_recorded", payload, idempotency_key
            )
            retry = updated.nodes[node_id].retry
            if retry is None:
                raise CorruptRunError("retry event did not produce retry metadata")
            return retry

    def _transition_run(
        self,
        run_id: str,
        target: RunState,
        reason: str | None,
        idempotency_key: str,
        *,
        approved_by: str | None = None,
    ) -> RunSnapshot:
        with self._locked(run_id):
            snapshot = self._load_unlocked(run_id)
            payload = {"from": snapshot.state.value, "to": target.value, "reason": reason}
            if approved_by is not None:
                payload["approved_by"] = approved_by
            fingerprint = self._operation_hash("run_transition", payload)
            if self._check_idempotency(snapshot, idempotency_key, fingerprint):
                return snapshot
            if target not in _RUN_TRANSITIONS.get(snapshot.state, frozenset()):
                raise InvalidTransitionError(
                    f"run cannot transition from {snapshot.state.value} to {target.value}"
                )
            if approved_by is not None and snapshot.state is not RunState.AWAITING_APPROVAL:
                raise InvalidTransitionError("run is not awaiting approval")
            return self._append_unlocked(
                run_id, snapshot, "run_transition", payload, idempotency_key=idempotency_key
            )

    def _transition_node(
        self,
        run_id: str,
        node_id: str,
        target: NodeState,
        reason: str | None,
        idempotency_key: str,
        *,
        approved_by: str | None = None,
    ) -> RunSnapshot:
        with self._locked(run_id):
            snapshot = self._load_unlocked(run_id)
            node = self._node(snapshot, node_id)
            payload = {
                "node_id": node_id,
                "from": node.state.value,
                "to": target.value,
                "reason": reason,
            }
            if approved_by is not None:
                payload["approved_by"] = approved_by
            fingerprint = self._operation_hash("node_transition", payload)
            if self._check_idempotency(snapshot, idempotency_key, fingerprint):
                return snapshot
            if target not in _NODE_TRANSITIONS.get(node.state, frozenset()):
                raise InvalidTransitionError(
                    f"node {node_id!r} cannot transition from {node.state.value} to {target.value}"
                )
            if approved_by is not None and node.state is not NodeState.AWAITING_APPROVAL:
                raise InvalidTransitionError(f"node {node_id!r} is not awaiting approval")
            return self._append_unlocked(
                run_id, snapshot, "node_transition", payload, idempotency_key=idempotency_key
            )

    def _append_checked(
        self,
        run_id: str,
        snapshot: RunSnapshot,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> RunSnapshot:
        fingerprint = self._operation_hash(event_type, payload)
        if self._check_idempotency(snapshot, idempotency_key, fingerprint):
            return snapshot
        return self._append_unlocked(
            run_id, snapshot, event_type, payload, idempotency_key=idempotency_key
        )

    def _append_unlocked(
        self,
        run_id: str,
        snapshot: RunSnapshot | None,
        event_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> RunSnapshot:
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        sequence = 1 if snapshot is None else snapshot.last_sequence + 1
        previous_hash = _ZERO_HASH if snapshot is None else snapshot.last_hash
        operation_hash = self._operation_hash(event_type, payload)
        body = {
            "sequence": sequence,
            "event_id": f"{run_id}:{sequence}",
            "run_id": run_id,
            "event_type": event_type,
            "occurred_at": _iso(self._now()),
            "payload": payload,
            "previous_hash": previous_hash,
            "idempotency_key": idempotency_key,
            "operation_hash": operation_hash,
        }
        raw = {**body, "hash": _hash(body)}
        path = self._events_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as stream:
            stream.write(_canonical(raw) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        updated = self._apply(snapshot, _event_from_dict(raw))
        self._write_checkpoint(updated)
        return updated

    def _load_unlocked(self, run_id: str) -> RunSnapshot:
        events = self._read_events(run_id)
        if not events:
            raise RunNotFoundError(f"run {run_id!r} does not exist")
        snapshots: list[RunSnapshot] = []
        snapshot: RunSnapshot | None = None
        for event in events:
            snapshot = self._apply(snapshot, event)
            snapshots.append(snapshot)
        if snapshot is None:
            raise RunNotFoundError(f"run {run_id!r} does not exist")
        checkpoint_path = self._checkpoint_path(run_id)
        if checkpoint_path.exists():
            checkpoint = self._read_checkpoint(checkpoint_path)
            sequence = checkpoint.get("snapshot", {}).get("last_sequence")
            if not isinstance(sequence, int) or sequence < 1 or sequence > len(snapshots):
                raise CorruptRunError("checkpoint sequence is invalid")
            expected = _snapshot_to_dict(snapshots[sequence - 1])
            if checkpoint["snapshot"] != expected:
                raise CorruptRunError("checkpoint does not match the event log")
        if not checkpoint_path.exists() or sequence != len(snapshots):
            self._write_checkpoint(snapshot)
        return snapshot

    def _read_events(self, run_id: str) -> list[Event]:
        path = self._events_path(run_id)
        if not path.exists():
            return []
        events: list[Event] = []
        previous_hash = _ZERO_HASH
        try:
            lines = path.read_bytes().splitlines()
        except OSError as exc:
            raise CorruptRunError("could not read event log") from exc
        for index, line in enumerate(lines, start=1):
            try:
                raw = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise CorruptRunError(f"invalid event JSON at line {index}") from exc
            if not isinstance(raw, dict):
                raise CorruptRunError(f"invalid event schema at line {index}")
            event = _event_from_dict(raw)
            if event.sequence != index or event.run_id != run_id:
                raise CorruptRunError(f"invalid event sequence or run id at line {index}")
            if event.previous_hash != previous_hash:
                raise CorruptRunError(f"broken hash chain at line {index}")
            if event.hash != _hash(_event_body(raw)):
                raise CorruptRunError(f"event hash mismatch at line {index}")
            previous_hash = event.hash
            events.append(event)
        return events

    def _apply(self, snapshot: RunSnapshot | None, event: Event) -> RunSnapshot:
        payload = event.payload
        if snapshot is None:
            if event.event_type != "run_created":
                raise CorruptRunError("first event must create the run")
            try:
                nodes = {
                    node_id: NodeSnapshot(node_id=node_id) for node_id in payload["node_ids"]
                }
                environment = EnvironmentSnapshot(**payload["environment"])
                git = GitSnapshot(**payload["git"])
            except (KeyError, TypeError) as exc:
                raise CorruptRunError("invalid run creation payload") from exc
            return RunSnapshot(
                run_id=event.run_id,
                state=RunState.CREATED,
                nodes=nodes,
                environment=environment,
                git=git,
                created_at=event.occurred_at,
                updated_at=event.occurred_at,
                last_sequence=event.sequence,
                last_hash=event.hash,
                idempotency={event.idempotency_key: event.operation_hash},
            )
        if event.previous_hash != snapshot.last_hash:
            raise CorruptRunError("event does not extend current state")
        nodes = dict(snapshot.nodes)
        approvals = snapshot.approvals
        state = snapshot.state
        try:
            if event.event_type == "run_transition":
                run_source = RunState(payload["from"])
                run_target = RunState(payload["to"])
                if run_source is not state or run_target not in _RUN_TRANSITIONS.get(
                    state, frozenset()
                ):
                    raise CorruptRunError("invalid run transition in event log")
                state = run_target
                if payload.get("approved_by"):
                    approvals += (Approval(payload["approved_by"], event.occurred_at),)
                if state is RunState.CANCELLED:
                    terminal = {NodeState.SUCCEEDED, NodeState.FAILED, NodeState.CANCELLED}
                    nodes = {
                        key: (
                            node
                            if node.state in terminal
                            else replace(node, state=NodeState.CANCELLED)
                        )
                        for key, node in nodes.items()
                    }
            elif event.event_type == "node_transition":
                node_id = payload["node_id"]
                node_source = NodeState(payload["from"])
                node_target = NodeState(payload["to"])
                node = nodes[node_id]
                if node_source is not node.state or node_target not in _NODE_TRANSITIONS.get(
                    node.state, frozenset()
                ):
                    raise CorruptRunError("invalid node transition in event log")
                nodes[node_id] = replace(node, state=node_target)
            elif event.event_type == "lease_acquired":
                node_id = payload["node_id"]
                acquired_lease = Lease(
                    owner=payload["owner"],
                    token=payload["token"],
                    acquired_at=_datetime(payload["acquired_at"]),
                    heartbeat_at=_datetime(payload["heartbeat_at"]),
                    expires_at=_datetime(payload["expires_at"]),
                )
                nodes[node_id] = replace(nodes[node_id], lease=acquired_lease)
            elif event.event_type == "lease_heartbeat":
                node_id = payload["node_id"]
                active_lease = nodes[node_id].lease
                if active_lease is None:
                    raise CorruptRunError("heartbeat has no preceding lease")
                nodes[node_id] = replace(
                    nodes[node_id],
                    lease=replace(
                        active_lease,
                        heartbeat_at=_datetime(payload["heartbeat_at"]),
                        expires_at=_datetime(payload["expires_at"]),
                    ),
                )
            elif event.event_type == "lease_released":
                node_id = payload["node_id"]
                active_lease = nodes[node_id].lease
                if active_lease is None or active_lease.token != payload["token"]:
                    raise CorruptRunError("lease release does not match an active lease")
                nodes[node_id] = replace(nodes[node_id], lease=None)
            elif event.event_type == "leases_expired":
                for node_id in payload["node_ids"]:
                    nodes[node_id] = replace(nodes[node_id], lease=None)
            elif event.event_type == "retry_recorded":
                node_id = payload["node_id"]
                retry = RetryMetadata(
                    attempt=payload["attempt"],
                    classification=RetryClass(payload["classification"]),
                    retryable=payload["retryable"],
                    backoff_seconds=payload["backoff_seconds"],
                    not_before=_datetime(payload["not_before"]) if payload["not_before"] else None,
                    reason=payload["reason"],
                )
                node = nodes[node_id]
                nodes[node_id] = replace(
                    node,
                    attempts=retry.attempt,
                    retry=retry,
                    retry_history=(*node.retry_history, retry),
                )
            else:
                raise CorruptRunError(f"unknown event type {event.event_type!r}")
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, CorruptRunError):
                raise
            raise CorruptRunError(f"invalid {event.event_type} payload") from exc
        idempotency = dict(snapshot.idempotency)
        existing = idempotency.get(event.idempotency_key)
        if existing is not None and existing != event.operation_hash:
            raise CorruptRunError("conflicting idempotency keys in event log")
        idempotency[event.idempotency_key] = event.operation_hash
        return replace(
            snapshot,
            state=state,
            nodes=nodes,
            approvals=approvals,
            updated_at=event.occurred_at,
            last_sequence=event.sequence,
            last_hash=event.hash,
            idempotency=idempotency,
        )

    def _write_checkpoint(self, snapshot: RunSnapshot) -> None:
        path = self._checkpoint_path(snapshot.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {"schema_version": _SCHEMA_VERSION, "snapshot": _snapshot_to_dict(snapshot)}
        document = {**body, "checkpoint_hash": _hash(body)}
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temp.open("wb") as stream:
                stream.write(_canonical(document) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temp.unlink()

    @staticmethod
    def _read_checkpoint(path: Path) -> dict[str, Any]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CorruptRunError("invalid checkpoint JSON") from exc
        if not isinstance(document, dict) or document.get("schema_version") != _SCHEMA_VERSION:
            raise CorruptRunError("invalid checkpoint schema")
        supplied_hash = document.get("checkpoint_hash")
        body = {key: value for key, value in document.items() if key != "checkpoint_hash"}
        if supplied_hash != _hash(body):
            raise CorruptRunError("checkpoint hash mismatch")
        if not isinstance(document.get("snapshot"), dict):
            raise CorruptRunError("invalid checkpoint snapshot")
        return document

    @contextlib.contextmanager
    def _locked(self, run_id: str, *, create: bool = False) -> Iterator[None]:
        run_dir = self._run_dir(run_id)
        if create:
            run_dir.mkdir(parents=True, exist_ok=True)
        elif not run_dir.exists():
            raise RunNotFoundError(f"run {run_id!r} does not exist")
        lock_path = run_dir / ".lock"
        with lock_path.open("a+b") as lock:
            _lock_file(lock)
            try:
                yield
            finally:
                _unlock_file(lock)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now.astimezone(UTC)

    @staticmethod
    def _operation_hash(event_type: str, payload: dict[str, Any]) -> str:
        # Derived state documents the event but is not part of caller command
        # identity. This keeps a retry stable across elapsed time and replay.
        derived_by_type = {
            "run_transition": {"from"},
            "node_transition": {"from"},
            "lease_acquired": {"token", "acquired_at", "heartbeat_at", "expires_at"},
            "lease_heartbeat": {"heartbeat_at", "expires_at"},
            "leases_expired": {"node_ids", "expired_at"},
            "retry_recorded": {"attempt", "retryable", "backoff_seconds", "not_before"},
        }
        ignored = derived_by_type.get(event_type, set())
        command_payload = {key: value for key, value in payload.items() if key not in ignored}
        return _hash({"event_type": event_type, "payload": command_payload})

    @staticmethod
    def _check_idempotency(
        snapshot: RunSnapshot, idempotency_key: str, fingerprint: str
    ) -> bool:
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        existing = snapshot.idempotency.get(idempotency_key)
        if existing is None:
            return False
        if existing != fingerprint:
            raise IdempotencyConflictError(
                f"idempotency key {idempotency_key!r} was used for another operation"
            )
        return True

    @staticmethod
    def _node(snapshot: RunSnapshot, node_id: str) -> NodeSnapshot:
        try:
            return snapshot.nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown node {node_id!r}") from exc

    @staticmethod
    def _validate_id(value: str, kind: str) -> None:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError(f"{kind}_id contains unsafe characters")

    @staticmethod
    def _validate_ttl(ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")

    def _run_dir(self, run_id: str) -> Path:
        return self._runs / run_id

    def _events_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "events.jsonl"

    def _checkpoint_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "checkpoint.json"


__all__ = ["RuntimeStore"]
