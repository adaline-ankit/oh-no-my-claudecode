"""Immutable policy models for the tool broker."""

from __future__ import annotations

import ipaddress
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType


class ActionType(StrEnum):
    """Security-sensitive action classes understood by the broker."""

    TOOL = "tool"
    FILESYSTEM = "filesystem"
    COMMAND = "command"
    NETWORK = "network"
    SECRET = "secret"  # noqa: S105 - action category, not a credential
    BUDGET = "budget"
    DEPLOYMENT = "deployment"


class DecisionEffect(StrEnum):
    """A broker decision, ordered by security precedence in ``Policy``."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


def _nonempty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{field_name} must be a non-empty string without NUL bytes")
    return value


def _freeze_json(
    value: object,
    *,
    depth: int = 0,
    active: frozenset[int] = frozenset(),
    count: list[int] | None = None,
) -> object:
    """Validate and immutably copy bounded canonical-JSON-compatible data."""

    if depth > 16:
        raise ValueError("context exceeds the maximum nesting depth")
    if count is None:
        count = [0]
    count[0] += 1
    if count[0] > 4096:
        raise ValueError("context exceeds the maximum item count")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value.bit_length() > 4096:
            raise ValueError("context integer is too large")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("context numbers must be finite")
        return value
    if isinstance(value, str):
        if len(value) > 65_536:
            raise ValueError("context string is too large")
        return value
    if isinstance(value, Mapping):
        object_id = id(value)
        if object_id in active:
            raise ValueError("context cannot contain cycles")
        next_active = active | {object_id}
        copied: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("context mapping keys must be strings")
            copied[key] = _freeze_json(item, depth=depth + 1, active=next_active, count=count)
        return MappingProxyType(copied)
    if isinstance(value, (list, tuple)):
        object_id = id(value)
        if object_id in active:
            raise ValueError("context cannot contain cycles")
        next_active = active | {object_id}
        return tuple(
            _freeze_json(item, depth=depth + 1, active=next_active, count=count) for item in value
        )
    raise ValueError("context must contain only canonical JSON data")


def canonical_host(host: str) -> str:
    """Return a comparison-safe hostname or IP literal.

    URLs, user-info, paths, wildcards, and bracketed host/port strings are not
    accepted as hosts.  Callers must provide host and port separately.
    """

    _nonempty(host, "host")
    candidate = host.rstrip(".")
    if not candidate or any(part in candidate for part in ("://", "@", "/", "\\", "*")):
        raise ValueError("host must be a hostname or IP literal, not a URL or pattern")
    try:
        return ipaddress.ip_address(candidate).compressed.lower()
    except ValueError:
        pass
    try:
        canonical = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("host is not a valid IDNA hostname") from exc
    labels = canonical.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(ch.isalnum() or ch == "-" for ch in label)
        for label in labels
    ):
        raise ValueError("host is not a valid hostname")
    return canonical


@dataclass(frozen=True)
class CommandRule:
    """An argv prefix or exact argv rule; shell strings are never parsed."""

    argv: tuple[str, ...]
    exact: bool = False

    def __post_init__(self) -> None:
        normalized = tuple(self.argv)
        if not normalized or any(
            not isinstance(arg, str) or not arg or "\x00" in arg for arg in normalized
        ):
            raise ValueError("command rule argv must contain non-empty strings without NUL bytes")
        object.__setattr__(self, "argv", normalized)

    def matches(self, argv: tuple[str, ...]) -> bool:
        if self.exact:
            return argv == self.argv
        return len(argv) >= len(self.argv) and argv[: len(self.argv)] == self.argv


@dataclass(frozen=True)
class PathRule:
    """A root with point-in-time symlink-aware containment checks.

    A decision-only check cannot prevent a component changing afterward. Callers
    must re-submit the action immediately before separately owned execution.
    """

    root: Path
    allow_root: bool = True

    def __post_init__(self) -> None:
        raw = Path(self.root)
        if "\x00" in str(raw):
            raise ValueError("path rule root cannot contain NUL bytes")
        object.__setattr__(self, "root", raw.resolve(strict=False))

    def matches(self, path: str | Path) -> bool:
        raw = Path(path)
        if "\x00" in str(raw):
            return False
        resolved = raw.resolve(strict=False)
        if resolved == self.root:
            return self.allow_root
        return resolved.is_relative_to(self.root)


@dataclass(frozen=True)
class NetworkRule:
    """An exact host, ``*.domain`` suffix, or IP CIDR rule."""

    host: str
    ports: frozenset[int] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        ports = frozenset(self.ports)
        if any(
            not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535
            for port in ports
        ):
            raise ValueError("network rule ports must be integers from 1 to 65535")
        object.__setattr__(self, "ports", ports)

        raw = _nonempty(self.host, "host rule").rstrip(".")
        if raw.startswith("*."):
            suffix = canonical_host(raw[2:])
            object.__setattr__(self, "host", f"*.{suffix}")
            return
        try:
            network = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            object.__setattr__(self, "host", canonical_host(raw))
        else:
            object.__setattr__(self, "host", network.with_prefixlen.lower())

    def matches(self, host: str, port: int | None) -> bool:
        if self.ports and port not in self.ports:
            return False
        try:
            candidate = canonical_host(host)
        except ValueError:
            return False
        if self.host.startswith("*."):
            suffix = self.host[2:]
            return candidate.endswith(f".{suffix}") and candidate != suffix
        try:
            network = ipaddress.ip_network(self.host, strict=False)
        except ValueError:
            return candidate == self.host
        try:
            return ipaddress.ip_address(candidate) in network
        except ValueError:
            return False


@dataclass(frozen=True)
class Action:
    """A normalized declaration of an intended action.

    This object describes intent only.  Nothing in the package executes it.
    """

    action_type: ActionType
    operation: str
    resource: str = ""
    argv: tuple[str, ...] = ()
    path: str | None = None
    host: str | None = None
    port: int | None = None
    amount: float | None = None
    verifier: bool = False
    context: Mapping[str, object] = field(default_factory=dict, compare=True, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_type", ActionType(self.action_type))
        _nonempty(self.operation, "operation")
        if not isinstance(self.verifier, bool):
            raise ValueError("verifier must be a boolean")
        if self.resource and "\x00" in self.resource:
            raise ValueError("resource cannot contain NUL bytes")
        if (
            self.action_type
            in {
                ActionType.TOOL,
                ActionType.SECRET,
                ActionType.BUDGET,
                ActionType.DEPLOYMENT,
            }
            and not self.resource
        ):
            raise ValueError(f"{self.action_type.value} actions require a resource")
        argv = tuple(self.argv)
        if any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in argv):
            raise ValueError("argv must contain non-empty strings without NUL bytes")
        object.__setattr__(self, "argv", argv)
        if self.action_type is ActionType.COMMAND and not argv:
            raise ValueError("command actions require a non-empty argv")
        if self.path is not None and (not self.path or "\x00" in self.path):
            raise ValueError("path must be non-empty and cannot contain NUL bytes")
        if self.action_type is ActionType.FILESYSTEM and not self.path:
            raise ValueError("filesystem actions require a non-empty path")
        if self.host is not None:
            object.__setattr__(self, "host", canonical_host(self.host))
        if self.action_type is ActionType.NETWORK and self.host is None:
            raise ValueError("network actions require a host")
        if self.port is not None and (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("port must be an integer from 1 to 65535")
        if self.amount is not None and (
            isinstance(self.amount, bool) or not math.isfinite(self.amount) or self.amount < 0
        ):
            raise ValueError("amount must be a finite non-negative number")
        if not isinstance(self.context, Mapping):
            raise ValueError("context must be a mapping")
        allowed_fields = {
            ActionType.TOOL: {"resource"},
            ActionType.FILESYSTEM: {"path"},
            ActionType.COMMAND: {"argv"},
            ActionType.NETWORK: {"host", "port"},
            ActionType.SECRET: {"resource"},
            ActionType.BUDGET: {"resource", "amount"},
            ActionType.DEPLOYMENT: {"resource"},
        }[self.action_type]
        present_fields = {
            name
            for name, present in (
                ("resource", bool(self.resource)),
                ("argv", bool(self.argv)),
                ("path", self.path is not None),
                ("host", self.host is not None),
                ("port", self.port is not None),
                ("amount", self.amount is not None),
            )
            if present
        }
        unexpected = present_fields - allowed_fields
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise ValueError(f"{self.action_type.value} action has irrelevant fields: {names}")
        frozen_context = _freeze_json(self.context)
        if not isinstance(frozen_context, Mapping):
            raise ValueError("context must be a mapping")
        object.__setattr__(self, "context", frozen_context)

    @classmethod
    def tool(
        cls,
        name: str,
        *,
        operation: str = "invoke",
        verifier: bool = False,
        context: Mapping[str, object] | None = None,
    ) -> Action:
        return cls(
            ActionType.TOOL,
            operation,
            resource=_nonempty(name, "tool name"),
            verifier=verifier,
            context=context if context is not None else {},
        )

    @classmethod
    def filesystem(
        cls,
        operation: str,
        path: str | Path,
        *,
        verifier: bool = False,
        context: Mapping[str, object] | None = None,
    ) -> Action:
        return cls(
            ActionType.FILESYSTEM,
            operation,
            path=str(path),
            verifier=verifier,
            context=context if context is not None else {},
        )

    @classmethod
    def command(
        cls,
        argv: tuple[str, ...] | list[str],
        *,
        verifier: bool = False,
        context: Mapping[str, object] | None = None,
    ) -> Action:
        return cls(
            ActionType.COMMAND,
            "execute",
            argv=tuple(argv),
            verifier=verifier,
            context=context if context is not None else {},
        )

    @classmethod
    def network(
        cls,
        operation: str,
        host: str,
        port: int | None = None,
        *,
        verifier: bool = False,
        context: Mapping[str, object] | None = None,
    ) -> Action:
        return cls(
            ActionType.NETWORK,
            operation,
            host=host,
            port=port,
            verifier=verifier,
            context=context if context is not None else {},
        )

    @classmethod
    def secret(cls, operation: str, name: str) -> Action:
        return cls(ActionType.SECRET, operation, resource=_nonempty(name, "secret name"))

    @classmethod
    def budget(cls, operation: str, name: str, *, amount: float | None = None) -> Action:
        return cls(
            ActionType.BUDGET, operation, resource=_nonempty(name, "budget name"), amount=amount
        )

    @classmethod
    def deployment(cls, operation: str, target: str) -> Action:
        return cls(
            ActionType.DEPLOYMENT, operation, resource=_nonempty(target, "deployment target")
        )

    def audit_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "action_type": self.action_type.value,
            "operation": self.operation,
            "verifier": self.verifier,
        }
        if self.resource:
            payload["resource"] = self.resource
        if self.argv:
            payload["argv"] = list(self.argv)
        if self.path is not None:
            payload["path"] = self.path
        if self.host is not None:
            payload["host"] = self.host
        if self.port is not None:
            payload["port"] = self.port
        if self.amount is not None:
            payload["amount"] = self.amount
        if self.context:
            payload["context"] = dict(self.context)
        return payload


@dataclass(frozen=True)
class Capability:
    """A least-privilege scope carried by policy rules or signed tokens."""

    action_type: ActionType
    operations: frozenset[str] = field(default_factory=lambda: frozenset({"*"}))
    resources: frozenset[str] = field(default_factory=frozenset)
    command_rules: tuple[CommandRule, ...] = ()
    path_rules: tuple[PathRule, ...] = ()
    network_rules: tuple[NetworkRule, ...] = ()
    max_amount: float | None = None
    verifier: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_type", ActionType(self.action_type))
        operations = frozenset(self.operations)
        resources = frozenset(self.resources)
        if not operations or any(not value or "\x00" in value for value in operations):
            raise ValueError("capability operations must be non-empty strings")
        if any(not value or "\x00" in value for value in resources):
            raise ValueError("capability resources must be non-empty strings")
        object.__setattr__(self, "operations", operations)
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "command_rules", tuple(self.command_rules))
        object.__setattr__(self, "path_rules", tuple(self.path_rules))
        object.__setattr__(self, "network_rules", tuple(self.network_rules))
        if not isinstance(self.verifier, bool):
            raise ValueError("verifier must be a boolean")
        if self.max_amount is not None and (
            isinstance(self.max_amount, bool)
            or not math.isfinite(self.max_amount)
            or self.max_amount < 0
        ):
            raise ValueError("max_amount must be a finite non-negative number")

        allowed_fields = {
            ActionType.TOOL: {"resources"},
            ActionType.FILESYSTEM: {"path_rules"},
            ActionType.COMMAND: {"command_rules"},
            ActionType.NETWORK: {"network_rules"},
            ActionType.SECRET: {"resources"},
            ActionType.BUDGET: {"resources", "max_amount"},
            ActionType.DEPLOYMENT: {"resources"},
        }[self.action_type]
        present_fields = {
            name
            for name, present in (
                ("resources", bool(self.resources)),
                ("command_rules", bool(self.command_rules)),
                ("path_rules", bool(self.path_rules)),
                ("network_rules", bool(self.network_rules)),
                ("max_amount", self.max_amount is not None),
            )
            if present
        }
        unexpected = present_fields - allowed_fields
        if unexpected:
            names = ", ".join(sorted(unexpected))
            raise ValueError(f"{self.action_type.value} capability has irrelevant fields: {names}")
        required_field = {
            ActionType.TOOL: "resources",
            ActionType.FILESYSTEM: "path_rules",
            ActionType.COMMAND: "command_rules",
            ActionType.NETWORK: "network_rules",
            ActionType.SECRET: "resources",
            ActionType.BUDGET: "resources",
            ActionType.DEPLOYMENT: "resources",
        }[self.action_type]
        if required_field not in present_fields:
            raise ValueError(f"{self.action_type.value} capability requires {required_field}")

    def matches(self, action: Action, *, match_verifier: bool = True) -> bool:
        if action.action_type is not self.action_type:
            return False
        if match_verifier and action.verifier is not self.verifier:
            return False
        if "*" not in self.operations and action.operation not in self.operations:
            return False
        if self.action_type is ActionType.COMMAND:
            return any(rule.matches(action.argv) for rule in self.command_rules)
        if self.action_type is ActionType.FILESYSTEM:
            return action.path is not None and any(
                rule.matches(action.path) for rule in self.path_rules
            )
        if self.action_type is ActionType.NETWORK:
            return action.host is not None and any(
                rule.matches(action.host, action.port) for rule in self.network_rules
            )
        if self.action_type is ActionType.BUDGET:
            if not self._resource_matches(action.resource):
                return False
            return self.max_amount is None or (
                action.amount is not None and action.amount <= self.max_amount
            )
        return self._resource_matches(action.resource)

    def _resource_matches(self, resource: str) -> bool:
        return "*" in self.resources or resource in self.resources


@dataclass(frozen=True)
class PolicyRule:
    rule_id: str
    effect: DecisionEffect
    capability: Capability

    def __post_init__(self) -> None:
        _nonempty(self.rule_id, "rule_id")
        object.__setattr__(self, "effect", DecisionEffect(self.effect))


@dataclass(frozen=True)
class Policy:
    """An immutable deny-by-default rule set."""

    rules: tuple[PolicyRule, ...] = ()

    def __post_init__(self) -> None:
        rules = tuple(self.rules)
        ids = [rule.rule_id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("policy rule IDs must be unique")
        object.__setattr__(self, "rules", rules)


@dataclass(frozen=True)
class Decision:
    effect: DecisionEffect
    reason_code: str
    matched_rule_ids: tuple[str, ...] = ()
    matched_token_ids: tuple[str, ...] = ()
    resolved_path: str | None = None

    @property
    def allowed(self) -> bool:
        return self.effect is DecisionEffect.ALLOW

    @property
    def denied(self) -> bool:
        return self.effect is DecisionEffect.DENY

    @property
    def approval_required(self) -> bool:
        return self.effect is DecisionEffect.REQUIRE_APPROVAL
