"""HMAC-authenticated, scoped, expiring capability tokens."""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ._serialization import canonical_json_bytes
from .models import ActionType, Capability, CommandRule, NetworkRule, PathRule

MAX_TOKEN_LENGTH = 65_536
_BASE64URL_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
_SHA256_SIGNATURE_LENGTH = 43


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("token times must be timezone-aware")
    return value.astimezone(UTC)


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(data: str) -> bytes:
    if not data or any(char not in _BASE64URL_CHARS for char in data):
        raise ValueError("invalid base64url")
    decoded = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
    if _encode(decoded) != data:
        raise ValueError("non-canonical base64url")
    return decoded


def _capability_payload(capability: Capability) -> dict[str, object]:
    return {
        "action_type": capability.action_type.value,
        "operations": sorted(capability.operations),
        "resources": sorted(capability.resources),
        "command_rules": [
            {"argv": list(rule.argv), "exact": rule.exact} for rule in capability.command_rules
        ],
        "path_rules": [
            {"root": str(rule.root), "allow_root": rule.allow_root}
            for rule in capability.path_rules
        ],
        "network_rules": [
            {"host": rule.host, "ports": sorted(rule.ports)} for rule in capability.network_rules
        ],
        "max_amount": capability.max_amount,
        "verifier": capability.verifier,
    }


def _capability_from_payload(data: object) -> Capability:
    if not isinstance(data, dict):
        raise ValueError("invalid capability")
    return Capability(
        ActionType(str(data["action_type"])),
        operations=frozenset(str(item) for item in data.get("operations", [])),
        resources=frozenset(str(item) for item in data.get("resources", [])),
        command_rules=tuple(
            CommandRule(tuple(str(arg) for arg in item["argv"]), exact=bool(item["exact"]))
            for item in data.get("command_rules", [])
            if isinstance(item, dict)
        ),
        path_rules=tuple(
            PathRule(Path(str(item["root"])), allow_root=bool(item["allow_root"]))
            for item in data.get("path_rules", [])
            if isinstance(item, dict)
        ),
        network_rules=tuple(
            NetworkRule(
                str(item["host"]),
                ports=frozenset(int(port) for port in item.get("ports", [])),
            )
            for item in data.get("network_rules", [])
            if isinstance(item, dict)
        ),
        max_amount=(float(data["max_amount"]) if data.get("max_amount") is not None else None),
        verifier=bool(data.get("verifier", False)),
    )


@dataclass(frozen=True)
class CapabilityToken:
    token_id: str
    subject: str
    capabilities: tuple[Capability, ...]
    issued_at: datetime
    expires_at: datetime


class TokenAuthority:
    """Mint and verify opaque-looking signed capability tokens."""

    def __init__(
        self,
        signing_key: bytes,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError("signing_key must contain at least 32 bytes")
        self._signing_key = signing_key
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue(
        self,
        *,
        subject: str,
        capabilities: Iterable[Capability],
        ttl: timedelta,
    ) -> str:
        if not subject or "\x00" in subject:
            raise ValueError("token subject must be non-empty")
        issued_at = _utc(self._clock())
        expires_at = issued_at + ttl
        scopes = tuple(capabilities)
        if not scopes:
            raise ValueError("a capability token must carry at least one scope")
        payload = {
            "version": 1,
            "token_id": secrets.token_hex(16),
            "subject": subject,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "capabilities": [_capability_payload(scope) for scope in scopes],
        }
        encoded = _encode(canonical_json_bytes(payload))
        if len(encoded) + 1 + _SHA256_SIGNATURE_LENGTH > MAX_TOKEN_LENGTH:
            raise ValueError("capability token exceeds the maximum encoded size")
        signature = _encode(hmac.digest(self._signing_key, encoded.encode("ascii"), "sha256"))
        return f"{encoded}.{signature}"

    def verify(
        self,
        token: str,
        *,
        subject: str | None,
        now: datetime | None = None,
    ) -> CapabilityToken | None:
        try:
            if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH or token.count(".") != 1:
                return None
            encoded, signature = token.split(".", 1)
            if len(signature) != _SHA256_SIGNATURE_LENGTH:
                return None
            expected = hmac.digest(self._signing_key, encoded.encode("ascii"), "sha256")
            if not hmac.compare_digest(_decode(signature), expected):
                return None
            payload = json.loads(_decode(encoded))
            if not isinstance(payload, dict) or payload.get("version") != 1:
                return None
            token_subject = str(payload["subject"])
            if subject is not None and token_subject != subject:
                return None
            issued_at = _utc(datetime.fromisoformat(str(payload["issued_at"])))
            expires_at = _utc(datetime.fromisoformat(str(payload["expires_at"])))
            checked_at = _utc(now or self._clock())
            if checked_at < issued_at or checked_at >= expires_at:
                return None
            capabilities = tuple(_capability_from_payload(item) for item in payload["capabilities"])
            if not capabilities:
                return None
            return CapabilityToken(
                token_id=str(payload["token_id"]),
                subject=token_subject,
                capabilities=capabilities,
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            binascii.Error,
            json.JSONDecodeError,
            UnicodeError,
        ):
            return None
