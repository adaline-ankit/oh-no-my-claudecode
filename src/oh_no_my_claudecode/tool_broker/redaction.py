"""Deterministic secret redaction for broker audit payloads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEYS = {
    "auth",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "session",
    "sessionid",
}
_SENSITIVE_SUFFIXES = (
    "apikey",
    "credential",
    "password",
    "passwd",
    "privatekey",
    "secret",
    "token",
)
_VALUE_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
)


def _redact_string(value: str, ordered_secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in ordered_secrets:
        redacted = redacted.replace(secret, REDACTED)
    for pattern in _VALUE_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def _is_secret_key(key: str) -> bool:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    normalized = re.sub(r"[^a-z0-9]", "", separated.lower())
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _redact(value: Any, ordered_secrets: tuple[str, ...]) -> Any:
    if isinstance(value, Mapping):
        result: dict[object, Any] = {}
        for key, item in value.items():
            clean_key = _redact_string(key, ordered_secrets) if isinstance(key, str) else key
            result[clean_key] = (
                REDACTED
                if isinstance(key, str) and _is_secret_key(key)
                else _redact(item, ordered_secrets)
            )
        return result
    if isinstance(value, tuple):
        return tuple(_redact(item, ordered_secrets) for item in value)
    if isinstance(value, list):
        return [_redact(item, ordered_secrets) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(
            (_redact(item, ordered_secrets) for item in value),
            key=repr,
        )
    if isinstance(value, str):
        return _redact_string(value, ordered_secrets)
    return value


def redact_secrets(value: Any, *, secret_values: tuple[str, ...] = ()) -> Any:
    """Recursively redact sensitive keys, known values, and common token forms."""

    ordered_secrets = tuple(
        sorted((secret for secret in secret_values if secret), key=len, reverse=True)
    )
    return _redact(value, ordered_secrets)
