"""Typed values used by the local durable runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RunState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING = "waiting"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING = "waiting"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RetryClass(StrEnum):
    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    RESOURCE = "resource"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EnvironmentSnapshot:
    python_version: str
    platform: str
    executable: str
    cwd: str


@dataclass(frozen=True)
class GitSnapshot:
    root: str | None
    head: str | None
    branch: str | None
    dirty: bool | None


@dataclass(frozen=True)
class Lease:
    owner: str
    token: str
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class RetryMetadata:
    attempt: int
    classification: RetryClass
    retryable: bool
    backoff_seconds: float | None
    not_before: datetime | None
    reason: str


@dataclass(frozen=True)
class Approval:
    approved_by: str
    approved_at: datetime


@dataclass(frozen=True)
class NodeSnapshot:
    node_id: str
    state: NodeState = NodeState.PENDING
    lease: Lease | None = None
    attempts: int = 0
    retry: RetryMetadata | None = None
    retry_history: tuple[RetryMetadata, ...] = ()


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    state: RunState
    nodes: dict[str, NodeSnapshot]
    environment: EnvironmentSnapshot
    git: GitSnapshot
    created_at: datetime
    updated_at: datetime
    last_sequence: int
    last_hash: str
    approvals: tuple[Approval, ...] = ()
    idempotency: dict[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Event:
    sequence: int
    event_id: str
    run_id: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any]
    previous_hash: str
    hash: str
    idempotency_key: str
    operation_hash: str


class DurableRuntimeError(RuntimeError):
    """Base class for durable-runtime failures."""


class RunNotFoundError(DurableRuntimeError):
    pass


class RunAlreadyExistsError(DurableRuntimeError):
    pass


class InvalidTransitionError(DurableRuntimeError):
    pass


class IdempotencyConflictError(DurableRuntimeError):
    pass


class LeaseConflictError(DurableRuntimeError):
    pass


class LeaseExpiredError(DurableRuntimeError):
    pass


class CorruptRunError(DurableRuntimeError):
    pass
