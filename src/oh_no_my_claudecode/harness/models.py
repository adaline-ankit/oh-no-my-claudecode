"""Immutable task-DAG models for the adaptive execution harness."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import ClassVar, TypeGuard

SCHEMA_VERSION = "1"


class DAGValidationError(ValueError):
    """Raised when task nodes do not form a valid directed acyclic graph."""


class SerializationError(ValueError):
    """Raised when a serialized task DAG does not match the current schema."""


class NodeKind(StrEnum):
    """Canonical phases emitted by the task compiler."""

    UNDERSTAND = "understand"
    RETRIEVE = "retrieve"
    PLAN = "plan"
    CLAIM = "claim"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPAIR = "repair"
    PROVE = "prove"
    LEARN = "learn"


class RiskLevel(StrEnum):
    """Execution risk used to select deterministic policy headroom."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry policy for one node invocation."""

    max_attempts: int = 2
    backoff_seconds: float = 1.0

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"max_attempts", "backoff_seconds"})

    def validate(self) -> None:
        if not _is_int(self.max_attempts) or self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if isinstance(self.backoff_seconds, bool) or not isinstance(
            self.backoff_seconds, (int, float)
        ):
            raise ValueError("backoff_seconds must be a number")
        try:
            finite = isfinite(self.backoff_seconds)
        except OverflowError as exc:
            raise ValueError("backoff_seconds must be finite") from exc
        if not finite:
            raise ValueError("backoff_seconds must be finite")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "backoff_seconds": float(self.backoff_seconds),
            "max_attempts": self.max_attempts,
        }

    @classmethod
    def from_dict(cls, payload: object, *, path: str) -> RetryPolicy:
        data = _object(payload, path)
        _exact_fields(data, cls._FIELDS, path)
        return cls(
            max_attempts=_integer(data["max_attempts"], f"{path}.max_attempts"),
            backoff_seconds=_number(data["backoff_seconds"], f"{path}.backoff_seconds"),
        )


@dataclass(frozen=True, slots=True)
class NodePolicy:
    """All runtime policy required to dispatch and assess a task node."""

    agent: str
    model: str
    tools: tuple[str, ...]
    context_budget: int
    verifier: str
    retry: RetryPolicy

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"agent", "model", "tools", "context_budget", "verifier", "retry"}
    )

    def __post_init__(self) -> None:
        _require_nonempty(self.agent, "agent")
        _require_nonempty(self.model, "model")
        _require_string_tuple(self.tools, "tools", allow_empty=False)
        if len(set(self.tools)) != len(self.tools):
            raise ValueError("tools must be unique")
        if not _is_int(self.context_budget) or self.context_budget <= 0:
            raise ValueError("context_budget must be positive")
        _require_nonempty(self.verifier, "verifier")
        if not isinstance(self.retry, RetryPolicy):
            raise ValueError("retry must be a RetryPolicy")
        self.retry.validate()

    def to_dict(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "context_budget": self.context_budget,
            "model": self.model,
            "retry": self.retry.to_dict(),
            "tools": list(self.tools),
            "verifier": self.verifier,
        }

    @classmethod
    def from_dict(cls, payload: object, *, path: str = "policy") -> NodePolicy:
        data = _object(payload, path)
        _exact_fields(data, cls._FIELDS, path)
        return cls(
            agent=_string(data["agent"], f"{path}.agent"),
            model=_string(data["model"], f"{path}.model"),
            tools=_string_tuple(data["tools"], f"{path}.tools"),
            context_budget=_integer(data["context_budget"], f"{path}.context_budget"),
            verifier=_string(data["verifier"], f"{path}.verifier"),
            retry=RetryPolicy.from_dict(data["retry"], path=f"{path}.retry"),
        )


@dataclass(frozen=True, slots=True)
class TaskNode:
    """One typed, immutable node in a task DAG."""

    node_id: str
    kind: NodeKind
    objective: str
    dependencies: tuple[str, ...]
    policy: NodePolicy

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"id", "kind", "objective", "dependencies", "policy"}
    )

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise DAGValidationError("node id must not be empty")
        if not isinstance(self.kind, NodeKind):
            raise DAGValidationError("node kind must be a NodeKind")
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise DAGValidationError(f"node '{self.node_id}' objective must not be empty")
        try:
            _require_string_tuple(self.dependencies, "dependencies")
        except ValueError as exc:
            raise DAGValidationError(f"node '{self.node_id}' {exc}") from exc
        if len(set(self.dependencies)) != len(self.dependencies):
            raise DAGValidationError(f"node '{self.node_id}' dependencies must be unique")
        if not isinstance(self.policy, NodePolicy):
            raise DAGValidationError(f"node '{self.node_id}' policy must be a NodePolicy")

    def to_dict(self) -> dict[str, object]:
        return {
            "dependencies": list(self.dependencies),
            "id": self.node_id,
            "kind": self.kind.value,
            "objective": self.objective,
            "policy": self.policy.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: object, *, index: int) -> TaskNode:
        path = f"nodes[{index}]"
        data = _object(payload, path)
        _exact_fields(data, cls._FIELDS, path)
        raw_kind = _string(data["kind"], f"{path}.kind")
        try:
            kind = NodeKind(raw_kind)
        except ValueError as exc:
            raise SerializationError(f"invalid node kind: {raw_kind}") from exc
        return cls(
            node_id=_string(data["id"], f"{path}.id"),
            kind=kind,
            objective=_string(data["objective"], f"{path}.objective"),
            dependencies=_string_tuple(data["dependencies"], f"{path}.dependencies"),
            policy=NodePolicy.from_dict(data["policy"], path=f"{path}.policy"),
        )


@dataclass(frozen=True, slots=True)
class TaskDAG:
    """Versioned task graph with strict validation and canonical JSON encoding."""

    schema_version: str
    task: str
    risk: RiskLevel
    nodes: tuple[TaskNode, ...]

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"schema_version", "task", "risk", "nodes"}
    )

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise SerializationError(f"unsupported schema version: {self.schema_version}")
        if not isinstance(self.task, str) or not self.task.strip():
            raise DAGValidationError("task must not be empty")
        if not isinstance(self.risk, RiskLevel):
            raise DAGValidationError("risk must be a RiskLevel")
        if not isinstance(self.nodes, tuple):
            raise DAGValidationError("nodes must be a tuple")
        _validate_dag(self.nodes)

    def topological_order(self) -> tuple[TaskNode, ...]:
        """Return a stable dependency order, preserving source order for ties."""
        by_id = {node.node_id: node for node in self.nodes}
        remaining = {node.node_id: len(node.dependencies) for node in self.nodes}
        dependents: dict[str, list[str]] = {node.node_id: [] for node in self.nodes}
        for node in self.nodes:
            for dependency in node.dependencies:
                dependents[dependency].append(node.node_id)

        ready = deque(node.node_id for node in self.nodes if remaining[node.node_id] == 0)
        ordered: list[TaskNode] = []
        while ready:
            current = ready.popleft()
            ordered.append(by_id[current])
            for dependent in dependents[current]:
                remaining[dependent] -= 1
                if remaining[dependent] == 0:
                    ready.append(dependent)
        return tuple(ordered)

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "risk": self.risk.value,
            "schema_version": self.schema_version,
            "task": self.task,
        }

    def to_json(self) -> str:
        """Serialize to a byte-stable, whitespace-free JSON representation."""
        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, payload: object) -> TaskDAG:
        data = _object(payload, "task DAG payload")
        _exact_fields(data, cls._FIELDS, "task DAG payload")
        schema_version = _string(data["schema_version"], "schema_version")
        if schema_version != SCHEMA_VERSION:
            raise SerializationError(f"unsupported schema version: {schema_version}")
        raw_risk = _string(data["risk"], "risk")
        try:
            risk = RiskLevel(raw_risk)
        except ValueError as exc:
            raise SerializationError(f"invalid risk: {raw_risk}") from exc
        raw_nodes = data["nodes"]
        if not isinstance(raw_nodes, list):
            raise SerializationError("nodes must be an array")
        return cls(
            schema_version=schema_version,
            task=_string(data["task"], "task"),
            risk=risk,
            nodes=tuple(
                TaskNode.from_dict(node, index=index)
                for index, node in enumerate(raw_nodes)
            ),
        )

    @classmethod
    def from_json(cls, payload: str | bytes | bytearray) -> TaskDAG:
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise SerializationError("invalid task DAG JSON") from exc
        return cls.from_dict(decoded)


def _validate_dag(nodes: tuple[TaskNode, ...]) -> None:
    by_id: dict[str, TaskNode] = {}
    for node in nodes:
        if not isinstance(node, TaskNode):
            raise DAGValidationError("nodes must contain only TaskNode values")
        if node.node_id in by_id:
            raise DAGValidationError(f"duplicate node id: {node.node_id}")
        by_id[node.node_id] = node
    if not nodes:
        raise DAGValidationError("task DAG must contain at least one node")

    for node in nodes:
        for dependency in node.dependencies:
            if dependency == node.node_id:
                raise DAGValidationError(f"node '{node.node_id}' cannot depend on itself")
            if dependency not in by_id:
                raise DAGValidationError(
                    f"node '{node.node_id}' has unknown dependency '{dependency}'"
                )

    state: dict[str, int] = {}
    for node in nodes:
        if state.get(node.node_id, 0) != 0:
            continue
        path: list[str] = []
        active_index: dict[str, int] = {}
        stack: list[tuple[str, int]] = [(node.node_id, 0)]
        while stack:
            node_id, dependency_index = stack[-1]
            if state.get(node_id, 0) == 0:
                state[node_id] = 1
                active_index[node_id] = len(path)
                path.append(node_id)

            dependencies = by_id[node_id].dependencies
            if dependency_index == len(dependencies):
                stack.pop()
                path.pop()
                active_index.pop(node_id)
                state[node_id] = 2
                continue

            dependency = dependencies[dependency_index]
            stack[-1] = (node_id, dependency_index + 1)
            dependency_state = state.get(dependency, 0)
            if dependency_state == 1:
                cycle = [*path[active_index[dependency] :], dependency]
                raise DAGValidationError(f"cycle detected: {' -> '.join(cycle)}")
            if dependency_state == 0:
                stack.append((dependency, 0))


def _object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise SerializationError(f"{path} must be an object")
    return value


def _exact_fields(data: dict[str, object], expected: frozenset[str], path: str) -> None:
    missing = sorted(expected - data.keys())
    unknown = sorted(data.keys() - expected)
    if missing:
        raise SerializationError(f"{path} missing fields: {', '.join(missing)}")
    if unknown:
        raise SerializationError(f"{path} has unknown fields: {', '.join(unknown)}")


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise SerializationError(f"{path} must be a string")
    return value


def _integer(value: object, path: str) -> int:
    if not _is_int(value):
        field = path.rsplit(".", 1)[-1]
        raise SerializationError(f"{field} must be an integer")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        field = path.rsplit(".", 1)[-1]
        raise SerializationError(f"{field} must be a number")
    return float(value)


def _string_tuple(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SerializationError(f"{path} must be an array of strings")
    return tuple(value)


def _require_nonempty(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")


def _require_string_tuple(value: object, name: str, *, allow_empty: bool = True) -> None:
    if not isinstance(value, tuple) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{name} must be a tuple of non-empty strings")
    if not allow_empty and not value:
        raise ValueError(f"at least one {name[:-1] if name.endswith('s') else name} is required")


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)
