"""Typed runtime graph contracts shared by ONMC execution surfaces."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Any, ClassVar

SCHEMA_VERSION = "1"


class RuntimeContractError(ValueError):
    """Raised when a runtime graph is not executable."""


class NodeResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunResultStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Budget:
    """Per-node spend and time ceiling."""

    timeout_seconds: float
    max_cost_usd: float | None = None
    max_tokens: int | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"timeout_seconds", "max_cost_usd", "max_tokens"}
    )

    def __post_init__(self) -> None:
        _positive_number(self.timeout_seconds, "timeout_seconds")
        if self.max_cost_usd is not None:
            _nonnegative_number(self.max_cost_usd, "max_cost_usd")
        if self.max_tokens is not None and (
            not isinstance(self.max_tokens, int)
            or isinstance(self.max_tokens, bool)
            or self.max_tokens < 1
        ):
            raise RuntimeContractError("max_tokens must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "max_cost_usd": self.max_cost_usd,
            "max_tokens": self.max_tokens,
            "timeout_seconds": float(self.timeout_seconds),
        }

    @classmethod
    def from_dict(cls, payload: object, *, path: str = "budget") -> Budget:
        data = _object(payload, path)
        _exact_fields(data, cls._FIELDS, path)
        max_tokens = data["max_tokens"]
        return cls(
            timeout_seconds=_number(data["timeout_seconds"], f"{path}.timeout_seconds"),
            max_cost_usd=_optional_number(data["max_cost_usd"], f"{path}.max_cost_usd"),
            max_tokens=None
            if max_tokens is None
            else _integer(max_tokens, f"{path}.max_tokens"),
        )


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    """Declared effects a node may perform."""

    tools: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    filesystem_write: bool = False
    network: bool = False
    secrets: tuple[str, ...] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"tools", "commands", "filesystem_write", "network", "secrets"}
    )

    def __post_init__(self) -> None:
        _string_tuple(self.tools, "tools")
        _string_tuple(self.secrets, "secrets")
        for index, command in enumerate(self.commands):
            _string_tuple(command, f"commands[{index}]", allow_empty=False)
        if not isinstance(self.filesystem_write, bool):
            raise RuntimeContractError("filesystem_write must be a bool")
        if not isinstance(self.network, bool):
            raise RuntimeContractError("network must be a bool")

    @property
    def empty(self) -> bool:
        return (
            not self.tools
            and not self.commands
            and not self.filesystem_write
            and not self.network
            and not self.secrets
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "commands": [list(command) for command in self.commands],
            "filesystem_write": self.filesystem_write,
            "network": self.network,
            "secrets": list(self.secrets),
            "tools": list(self.tools),
        }

    @classmethod
    def from_dict(cls, payload: object, *, path: str = "capabilities") -> CapabilitySet:
        data = _object(payload, path)
        _exact_fields(data, cls._FIELDS, path)
        raw_commands = _array(data["commands"], f"{path}.commands")
        return cls(
            tools=_string_tuple(data["tools"], f"{path}.tools"),
            commands=tuple(
                _string_tuple(command, f"{path}.commands[{index}]", allow_empty=False)
                for index, command in enumerate(raw_commands)
            ),
            filesystem_write=_bool(data["filesystem_write"], f"{path}.filesystem_write"),
            network=_bool(data["network"], f"{path}.network"),
            secrets=_string_tuple(data["secrets"], f"{path}.secrets"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Pointer to evidence used or produced by a runtime node."""

    evidence_id: str
    kind: str
    uri: str
    digest: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"id", "kind", "uri", "digest"})

    def __post_init__(self) -> None:
        _nonempty(self.evidence_id, "id")
        _nonempty(self.kind, "kind")
        _nonempty(self.uri, "uri")
        if self.digest is not None:
            _nonempty(self.digest, "digest")

    def to_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "id": self.evidence_id,
            "kind": self.kind,
            "uri": self.uri,
        }

    @classmethod
    def from_dict(cls, payload: object, *, path: str = "evidence") -> EvidenceRef:
        data = _object(payload, path)
        _exact_fields(data, cls._FIELDS, path)
        digest = data["digest"]
        return cls(
            evidence_id=_string(data["id"], f"{path}.id"),
            kind=_string(data["kind"], f"{path}.kind"),
            uri=_string(data["uri"], f"{path}.uri"),
            digest=None if digest is None else _string(digest, f"{path}.digest"),
        )


@dataclass(frozen=True, slots=True)
class NodeSpec:
    """One executable node in a canonical ONMC graph."""

    node_id: str
    kind: str
    objective: str
    completion_condition: str | None
    dependencies: tuple[str, ...]
    side_effecting: bool
    idempotency_key: str | None
    timeout_seconds: float | None
    budget: Budget | None
    capabilities: CapabilitySet
    metadata: dict[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "id",
            "kind",
            "objective",
            "completion_condition",
            "dependencies",
            "side_effecting",
            "idempotency_key",
            "timeout_seconds",
            "budget",
            "capabilities",
            "metadata",
        }
    )

    def __post_init__(self) -> None:
        _nonempty(self.node_id, "id")
        _nonempty(self.kind, "kind")
        _nonempty(self.objective, "objective")
        if self.completion_condition is not None:
            _nonempty(self.completion_condition, "completion_condition")
        _string_tuple(self.dependencies, "dependencies")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise RuntimeContractError(f"node {self.node_id!r} dependencies must be unique")
        if not isinstance(self.side_effecting, bool):
            raise RuntimeContractError("side_effecting must be a bool")
        if self.idempotency_key is not None:
            _nonempty(self.idempotency_key, "idempotency_key")
        if self.timeout_seconds is not None:
            _positive_number(self.timeout_seconds, "timeout_seconds")
        if self.budget is not None and not isinstance(self.budget, Budget):
            raise RuntimeContractError("budget must be a Budget")
        if not isinstance(self.capabilities, CapabilitySet):
            raise RuntimeContractError("capabilities must be a CapabilitySet")
        if not isinstance(self.metadata, dict):
            raise RuntimeContractError("metadata must be an object")
        if self.side_effecting:
            if self.idempotency_key is None:
                raise RuntimeContractError(
                    f"side-effecting node {self.node_id!r} requires idempotency_key"
                )
            if self.timeout_seconds is None:
                raise RuntimeContractError(
                    f"side-effecting node {self.node_id!r} requires timeout_seconds"
                )
            if self.budget is None:
                raise RuntimeContractError(f"side-effecting node {self.node_id!r} requires budget")
            if self.capabilities.empty:
                raise RuntimeContractError(
                    f"side-effecting node {self.node_id!r} requires declared capabilities"
                )
            if self.completion_condition is None:
                raise RuntimeContractError(
                    f"side-effecting node {self.node_id!r} requires completion_condition"
                )

    def to_dict(self) -> dict[str, object]:
        return {
            "budget": self.budget.to_dict() if self.budget is not None else None,
            "capabilities": self.capabilities.to_dict(),
            "completion_condition": self.completion_condition,
            "dependencies": list(self.dependencies),
            "id": self.node_id,
            "idempotency_key": self.idempotency_key,
            "kind": self.kind,
            "metadata": _json_object(self.metadata, "metadata"),
            "objective": self.objective,
            "side_effecting": self.side_effecting,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, payload: object, *, index: int = 0) -> NodeSpec:
        path = f"nodes[{index}]"
        data = _object(payload, path)
        _exact_fields(data, cls._FIELDS, path)
        raw_budget = data["budget"]
        raw_key = data["idempotency_key"]
        raw_timeout = data["timeout_seconds"]
        raw_completion = data["completion_condition"]
        return cls(
            node_id=_string(data["id"], f"{path}.id"),
            kind=_string(data["kind"], f"{path}.kind"),
            objective=_string(data["objective"], f"{path}.objective"),
            completion_condition=None
            if raw_completion is None
            else _string(raw_completion, f"{path}.completion_condition"),
            dependencies=_string_tuple(data["dependencies"], f"{path}.dependencies"),
            side_effecting=_bool(data["side_effecting"], f"{path}.side_effecting"),
            idempotency_key=None
            if raw_key is None
            else _string(raw_key, f"{path}.idempotency_key"),
            timeout_seconds=None
            if raw_timeout is None
            else _number(raw_timeout, f"{path}.timeout_seconds"),
            budget=(
                None
                if raw_budget is None
                else Budget.from_dict(raw_budget, path=f"{path}.budget")
            ),
            capabilities=CapabilitySet.from_dict(
                data["capabilities"], path=f"{path}.capabilities"
            ),
            metadata=_object(data["metadata"], f"{path}.metadata"),
        )


@dataclass(frozen=True, slots=True)
class NodeResult:
    """Result emitted by one executed runtime node."""

    node_id: str
    status: NodeResultStatus
    idempotency_key: str
    output: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceRef, ...] = ()
    error: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"node_id", "status", "idempotency_key", "output", "evidence", "error"}
    )

    def __post_init__(self) -> None:
        _nonempty(self.node_id, "node_id")
        if not isinstance(self.status, NodeResultStatus):
            raise RuntimeContractError("status must be a NodeResultStatus")
        _nonempty(self.idempotency_key, "idempotency_key")
        if not isinstance(self.output, dict):
            raise RuntimeContractError("output must be an object")
        for item in self.evidence:
            if not isinstance(item, EvidenceRef):
                raise RuntimeContractError("evidence items must be EvidenceRef")
        if self.error is not None:
            _nonempty(self.error, "error")

    def to_dict(self) -> dict[str, object]:
        return {
            "error": self.error,
            "evidence": [item.to_dict() for item in self.evidence],
            "idempotency_key": self.idempotency_key,
            "node_id": self.node_id,
            "output": _json_object(self.output, "output"),
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, payload: object) -> NodeResult:
        data = _object(payload, "node result")
        _exact_fields(data, cls._FIELDS, "node result")
        try:
            status = NodeResultStatus(_string(data["status"], "node result.status"))
        except ValueError as exc:
            raise RuntimeContractError("invalid node result status") from exc
        raw_error = data["error"]
        return cls(
            node_id=_string(data["node_id"], "node result.node_id"),
            status=status,
            idempotency_key=_string(data["idempotency_key"], "node result.idempotency_key"),
            output=_object(data["output"], "node result.output"),
            evidence=tuple(
                EvidenceRef.from_dict(item, path=f"node result.evidence[{index}]")
                for index, item in enumerate(_array(data["evidence"], "node result.evidence"))
            ),
            error=None if raw_error is None else _string(raw_error, "node result.error"),
        )


@dataclass(frozen=True, slots=True)
class RunSpec:
    """Canonical graph ONMC can execute through any backend."""

    run_id: str
    task: str
    nodes: tuple[NodeSpec, ...]
    evidence: tuple[EvidenceRef, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"schema_version", "run_id", "task", "nodes", "evidence", "metadata"}
    )

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise RuntimeContractError(f"unsupported runtime schema: {self.schema_version}")
        _nonempty(self.run_id, "run_id")
        _nonempty(self.task, "task")
        if not isinstance(self.nodes, tuple):
            raise RuntimeContractError("nodes must be a tuple")
        if not self.nodes:
            raise RuntimeContractError("run spec must contain at least one node")
        for item in self.evidence:
            if not isinstance(item, EvidenceRef):
                raise RuntimeContractError("evidence items must be EvidenceRef")
        if not isinstance(self.metadata, dict):
            raise RuntimeContractError("metadata must be an object")
        _validate_graph(self.nodes)

    def topological_order(self) -> tuple[NodeSpec, ...]:
        by_id = {node.node_id: node for node in self.nodes}
        remaining = {node.node_id: len(node.dependencies) for node in self.nodes}
        dependents: dict[str, list[str]] = {node.node_id: [] for node in self.nodes}
        for node in self.nodes:
            for dependency in node.dependencies:
                dependents[dependency].append(node.node_id)
        ready = deque(node.node_id for node in self.nodes if remaining[node.node_id] == 0)
        ordered: list[NodeSpec] = []
        while ready:
            current = ready.popleft()
            ordered.append(by_id[current])
            for dependent in dependents[current]:
                remaining[dependent] -= 1
                if remaining[dependent] == 0:
                    ready.append(dependent)
        return tuple(ordered)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence": [item.to_dict() for item in self.evidence],
            "metadata": _json_object(self.metadata, "metadata"),
            "nodes": [node.to_dict() for node in self.nodes],
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "task": self.task,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_dict(cls, payload: object) -> RunSpec:
        data = _object(payload, "run spec")
        _exact_fields(data, cls._FIELDS, "run spec")
        raw_schema = _string(data["schema_version"], "run spec.schema_version")
        if raw_schema != SCHEMA_VERSION:
            raise RuntimeContractError(f"unsupported runtime schema: {raw_schema}")
        return cls(
            schema_version=raw_schema,
            run_id=_string(data["run_id"], "run spec.run_id"),
            task=_string(data["task"], "run spec.task"),
            nodes=tuple(
                NodeSpec.from_dict(node, index=index)
                for index, node in enumerate(_array(data["nodes"], "run spec.nodes"))
            ),
            evidence=tuple(
                EvidenceRef.from_dict(item, path=f"run spec.evidence[{index}]")
                for index, item in enumerate(_array(data["evidence"], "run spec.evidence"))
            ),
            metadata=_object(data["metadata"], "run spec.metadata"),
        )


@dataclass(frozen=True, slots=True)
class RunResult:
    """Terminal result from one runtime backend execution."""

    run_id: str
    status: RunResultStatus
    results: tuple[NodeResult, ...]
    backend: str
    spec_digest: str
    error: str | None = None

    def __post_init__(self) -> None:
        _nonempty(self.run_id, "run_id")
        if not isinstance(self.status, RunResultStatus):
            raise RuntimeContractError("status must be a RunResultStatus")
        _nonempty(self.backend, "backend")
        _nonempty(self.spec_digest, "spec_digest")
        for item in self.results:
            if not isinstance(item, NodeResult):
                raise RuntimeContractError("results must contain NodeResult items")
        if self.error is not None:
            _nonempty(self.error, "error")

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "error": self.error,
            "results": [item.to_dict() for item in self.results],
            "run_id": self.run_id,
            "spec_digest": self.spec_digest,
            "status": self.status.value,
        }


def _validate_graph(nodes: tuple[NodeSpec, ...]) -> None:
    node_ids = [node.node_id for node in nodes]
    if len(set(node_ids)) != len(node_ids):
        raise RuntimeContractError("node ids must be unique")
    known = set(node_ids)
    for node in nodes:
        missing = [dependency for dependency in node.dependencies if dependency not in known]
        if missing:
            raise RuntimeContractError(f"node {node.node_id!r} depends on missing nodes: {missing}")
        if node.node_id in node.dependencies:
            raise RuntimeContractError(f"node {node.node_id!r} depends on itself")
    if len(_topological(nodes)) != len(nodes):
        raise RuntimeContractError("runtime graph must be acyclic")


def _topological(nodes: tuple[NodeSpec, ...]) -> tuple[NodeSpec, ...]:
    by_id = {node.node_id: node for node in nodes}
    remaining = {node.node_id: len(node.dependencies) for node in nodes}
    dependents: dict[str, list[str]] = {node.node_id: [] for node in nodes}
    for node in nodes:
        for dependency in node.dependencies:
            dependents[dependency].append(node.node_id)
    ready = deque(node.node_id for node in nodes if remaining[node.node_id] == 0)
    ordered: list[NodeSpec] = []
    while ready:
        current = ready.popleft()
        ordered.append(by_id[current])
        for dependent in dependents[current]:
            remaining[dependent] -= 1
            if remaining[dependent] == 0:
                ready.append(dependent)
    return tuple(ordered)


def _json_object(value: dict[str, Any], path: str) -> dict[str, object]:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeContractError(f"{path} must be JSON serializable") from exc
    return dict(value)


def _object(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeContractError(f"{path} must be an object")
    return dict(value)


def _array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise RuntimeContractError(f"{path} must be an array")
    return value


def _exact_fields(data: dict[str, Any], fields: frozenset[str], path: str) -> None:
    found = set(data)
    if found != fields:
        raise RuntimeContractError(
            f"{path} fields must be exactly {sorted(fields)}, got {sorted(found)}"
        )


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise RuntimeContractError(f"{path} must be a string")
    return value


def _nonempty(value: object, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeContractError(f"{path} must not be empty")


def _string_tuple(value: object, path: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise RuntimeContractError(f"{path} must be a string array")
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise RuntimeContractError(f"{path}[{index}] must not be empty")
        items.append(item)
    if not allow_empty and not items:
        raise RuntimeContractError(f"{path} must not be empty")
    if len(set(items)) != len(items):
        raise RuntimeContractError(f"{path} must contain unique values")
    return tuple(items)


def _bool(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeContractError(f"{path} must be a bool")
    return value


def _integer(value: object, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeContractError(f"{path} must be an integer")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeContractError(f"{path} must be a number")
    try:
        if not isfinite(value):
            raise RuntimeContractError(f"{path} must be finite")
    except OverflowError as exc:
        raise RuntimeContractError(f"{path} must be finite") from exc
    return float(value)


def _optional_number(value: object, path: str) -> float | None:
    if value is None:
        return None
    return _number(value, path)


def _positive_number(value: object, path: str) -> None:
    if _number(value, path) <= 0:
        raise RuntimeContractError(f"{path} must be positive")


def _nonnegative_number(value: object, path: str) -> None:
    if _number(value, path) < 0:
        raise RuntimeContractError(f"{path} must be non-negative")
