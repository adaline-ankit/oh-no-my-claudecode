"""Optional OpenTelemetry GenAI-convention span export.

Converts a ``TraceReport`` (or a list of ``TraceEvent`` objects) into a list
of OpenTelemetry span dicts following the
`OpenTelemetry GenAI semantic conventions <https://opentelemetry.io/docs/specs/semconv/gen-ai/>`_.

**No OpenTelemetry SDK dependency** — this module emits pure Python dicts
that match the OTLP JSON shape.  Callers can serialize to JSON and pipe into
any OTLP-compatible backend or inspect manually.

Key attributes used
-------------------
- ``gen_ai.system``          — "onmc"
- ``gen_ai.operation.name``  — mapped from ``TraceEventKind``
- ``gen_ai.usage.input_tokens`` / ``gen_ai.usage.output_tokens``
- ``onmc.tool``              — tool name for tool_call events
- ``onmc.target``            — file path / query for read/search events
- ``onmc.session_id``        — parent session identifier
- ``onmc.usage.estimated``   — true only when legacy total-token events require estimation
- ``onmc.duration.estimated`` — true only when no measured end time/duration was recorded
- ``onmc.runtime.*``         — runtime graph/node attributes for runtime_node events
- ``traceId`` / ``spanId``   — deterministic OTLP correlation identifiers
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from oh_no_my_claudecode.trace.models import (
    TraceEvent,
    TraceEventKind,
    TraceReport,
)

_GEN_AI_SYSTEM = "onmc"

# Mapping from TraceEventKind to a GenAI operation name.
_OPERATION_MAP: dict[str, str] = {
    TraceEventKind.TOOL_CALL: "execute_tool",
    TraceEventKind.TOOL_FAILURE: "execute_tool",
    TraceEventKind.RUNTIME_NODE: "execute_agent",
    TraceEventKind.FILE_READ: "retrieve",
    TraceEventKind.SEARCH_QUERY: "retrieve",
    TraceEventKind.TOKENS: "chat",
    TraceEventKind.MEMORY_HIT: "retrieve",
    TraceEventKind.MEMORY_MISS: "retrieve",
    TraceEventKind.RECALL_SURFACED: "retrieve",
    TraceEventKind.DANGER_BLOCKED: "execute_tool",
    TraceEventKind.MEMORY_CAPTURED: "create",
    TraceEventKind.SKILL_PROMOTED: "create",
    TraceEventKind.STALENESS_WARNING: "chat",
    TraceEventKind.GENERIC: "chat",
}

_STATUS_ERROR = {"code": 2}  # OTEL StatusCode.ERROR
_STATUS_OK = {"code": 1}  # OTEL StatusCode.OK


def _ns(ts_seconds: float) -> int:
    """Convert Unix seconds to nanoseconds (OTLP time format)."""
    return int(ts_seconds * 1_000_000_000)


def _span_from_event(
    event: TraceEvent,
    *,
    session_id: str,
    index: int = 0,
) -> dict[str, Any]:
    """Build an OTLP JSON span dict from a single ``TraceEvent``."""
    kind = event.kind
    operation = _OPERATION_MAP.get(kind, "chat")
    is_error = _event_is_error(event)

    attributes: list[dict[str, Any]] = [
        {"key": "gen_ai.system", "value": {"stringValue": _GEN_AI_SYSTEM}},
        {"key": "gen_ai.operation.name", "value": {"stringValue": operation}},
        {"key": "onmc.session_id", "value": {"stringValue": session_id}},
        {"key": "onmc.event_kind", "value": {"stringValue": kind}},
    ]

    payload = event.payload
    start_ns, end_ns, duration_attributes = _span_times(event)
    attributes.extend(duration_attributes)
    if "tool" in payload:
        attributes.append(
            {"key": "onmc.tool", "value": {"stringValue": str(payload["tool"])}}
        )
    if "target" in payload:
        attributes.append(
            {"key": "onmc.target", "value": {"stringValue": str(payload["target"])}}
        )
    attributes.extend(_token_usage_attributes(payload))
    if payload.get("title"):
        attributes.append(
            {"key": "onmc.title", "value": {"stringValue": str(payload["title"])}}
        )
    attributes.extend(_runtime_node_attributes(event))

    return {
        "traceId": _trace_id(session_id),
        "spanId": _span_id(session_id, index, event),
        "name": f"onmc.{kind}",
        "kind": 1,  # INTERNAL
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
        "status": _STATUS_ERROR if is_error else _STATUS_OK,
        "attributes": attributes,
    }


def _trace_id(session_id: str) -> str:
    material = f"onmc-trace:{session_id or 'default'}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _span_id(session_id: str, index: int, event: TraceEvent) -> str:
    material = {
        "kind": event.kind,
        "payload": event.payload,
        "session_id": session_id,
        "span_index": index,
        "ts": event.ts,
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _event_is_error(event: TraceEvent) -> bool:
    if event.kind in (TraceEventKind.TOOL_FAILURE, TraceEventKind.DANGER_BLOCKED):
        return True
    if event.kind == TraceEventKind.RUNTIME_NODE:
        return str(event.payload.get("status", "")).lower() == "failed"
    return False


def _runtime_node_attributes(event: TraceEvent) -> list[dict[str, Any]]:
    if event.kind != TraceEventKind.RUNTIME_NODE:
        return []
    payload = event.payload
    attributes: list[dict[str, Any]] = []
    _append_string_attribute(attributes, "onmc.runtime.backend", payload.get("backend"))
    _append_string_attribute(attributes, "onmc.runtime.run_id", payload.get("run_id"))
    _append_string_attribute(attributes, "onmc.runtime.node_id", payload.get("node_id"))
    _append_string_attribute(attributes, "onmc.runtime.node.kind", payload.get("node_kind"))
    _append_string_attribute(attributes, "onmc.runtime.node.status", payload.get("status"))
    _append_string_attribute(attributes, "onmc.runtime.node.error", payload.get("error"))
    _append_bool_attribute(
        attributes,
        "onmc.runtime.node.side_effecting",
        payload.get("side_effecting"),
    )
    _append_bool_attribute(
        attributes,
        "onmc.runtime.node.approval_required",
        payload.get("approval_required"),
    )
    _append_int_attribute(
        attributes,
        "onmc.runtime.node.retry_attempts",
        payload.get("retry_attempts"),
    )
    _append_string_array_attribute(
        attributes,
        "onmc.runtime.node.dependencies",
        payload.get("dependencies"),
    )
    capabilities = payload.get("capabilities")
    if isinstance(capabilities, dict):
        _append_string_array_attribute(
            attributes,
            "onmc.runtime.capabilities.tools",
            capabilities.get("tools"),
        )
        _append_string_array_attribute(
            attributes,
            "onmc.runtime.capabilities.commands",
            _command_strings(capabilities.get("commands")),
        )
        _append_bool_attribute(
            attributes,
            "onmc.runtime.capabilities.filesystem_write",
            capabilities.get("filesystem_write"),
        )
        _append_bool_attribute(
            attributes,
            "onmc.runtime.capabilities.network",
            capabilities.get("network"),
        )
        secrets = capabilities.get("secrets")
        if isinstance(secrets, list | tuple):
            _append_int_attribute(
                attributes,
                "onmc.runtime.capabilities.secret_count",
                len(secrets),
            )
    return attributes


def _command_strings(commands: object) -> list[str]:
    if not isinstance(commands, list | tuple):
        return []
    rendered: list[str] = []
    for command in commands:
        if isinstance(command, list | tuple):
            rendered.append(" ".join(str(part) for part in command))
        else:
            rendered.append(str(command))
    return rendered


def _span_times(event: TraceEvent) -> tuple[int, int, list[dict[str, Any]]]:
    payload = event.payload
    start_ns = _ns(event.ts)
    end_ts = _optional_float(payload, "end_ts")
    if end_ts is not None and end_ts >= event.ts:
        return (
            start_ns,
            _ns(end_ts),
            [{"key": "onmc.duration.estimated", "value": {"boolValue": False}}],
        )

    duration_seconds = _optional_float(payload, "duration_seconds")
    if duration_seconds is None:
        duration_ms = _optional_float(payload, "duration_ms")
        if duration_ms is not None:
            duration_seconds = duration_ms / 1000.0
    if duration_seconds is not None and duration_seconds >= 0:
        return (
            start_ns,
            start_ns + _ns(duration_seconds),
            [{"key": "onmc.duration.estimated", "value": {"boolValue": False}}],
        )

    return (
        start_ns,
        start_ns + 1_000_000,
        [
            {"key": "onmc.duration.estimated", "value": {"boolValue": True}},
            {
                "key": "onmc.duration.estimate_reason",
                "value": {"stringValue": "instant_event_default_1ms"},
            },
        ],
    )


def _token_usage_attributes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    measured_input = _optional_int(payload, "input_tokens")
    measured_output = _optional_int(payload, "output_tokens")
    if measured_input is not None or measured_output is not None:
        attributes: list[dict[str, Any]] = [
            {"key": "onmc.usage.estimated", "value": {"boolValue": False}}
        ]
        if measured_input is not None:
            attributes.append(
                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": measured_input}}
            )
        if measured_output is not None:
            attributes.append(
                {"key": "gen_ai.usage.output_tokens", "value": {"intValue": measured_output}}
            )
        total = _optional_int(payload, "total")
        if total is not None:
            attributes.append({"key": "onmc.usage.total_tokens", "value": {"intValue": total}})
        return attributes

    total = _optional_int(payload, "total")
    if total is None:
        return []
    input_tokens = int(total * 0.6)
    output_tokens = total - input_tokens
    return [
        {"key": "gen_ai.usage.input_tokens", "value": {"intValue": input_tokens}},
        {"key": "gen_ai.usage.output_tokens", "value": {"intValue": output_tokens}},
        {"key": "onmc.usage.total_tokens", "value": {"intValue": total}},
        {"key": "onmc.usage.estimated", "value": {"boolValue": True}},
        {
            "key": "onmc.usage.estimate_reason",
            "value": {"stringValue": "legacy_total_tokens_only"},
        },
    ]


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _optional_float(payload: dict[str, Any], key: str) -> float | None:
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _append_string_attribute(
    attributes: list[dict[str, Any]],
    key: str,
    value: object,
) -> None:
    if value is None:
        return
    attributes.append({"key": key, "value": {"stringValue": str(value)}})


def _append_bool_attribute(
    attributes: list[dict[str, Any]],
    key: str,
    value: object,
) -> None:
    if not isinstance(value, bool):
        return
    attributes.append({"key": key, "value": {"boolValue": value}})


def _append_int_attribute(
    attributes: list[dict[str, Any]],
    key: str,
    value: object,
) -> None:
    if isinstance(value, bool):
        return
    if not isinstance(value, int | float | str | bytes | bytearray):
        return
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return
    attributes.append({"key": key, "value": {"intValue": parsed}})


def _append_string_array_attribute(
    attributes: list[dict[str, Any]],
    key: str,
    value: object,
) -> None:
    if not isinstance(value, list | tuple):
        return
    attributes.append(
        {
            "key": key,
            "value": {
                "arrayValue": {
                    "values": [{"stringValue": str(item)} for item in value],
                }
            },
        }
    )


def to_otel_spans(
    source: TraceReport | list[TraceEvent],
    *,
    session_id: str = "",
) -> list[dict[str, Any]]:
    """Convert a report or event list to OTLP JSON span dicts.

    Parameters
    ----------
    source:
        Either a ``TraceReport`` (the session_id is taken from it) or a bare
        list of ``TraceEvent`` objects (supply *session_id* manually).
    session_id:
        Used when *source* is a list of events.  Overrides the report's
        session_id when both are provided.

    Returns
    -------
    list[dict[str, Any]]
        One span dict per event.  Serialise with ``json.dumps`` for OTLP JSON.
    """
    if isinstance(source, TraceReport):
        sid = session_id or source.session_id
        events: list[TraceEvent] = []
        # Re-synthesise minimal events from the report's aggregated counters.
        # Real events are not stored on TraceReport — callers who need full
        # fidelity should pass the raw event list instead.
        # We emit one summary span per metric category.
        now = time.time()
        if source.tool_calls > 0:
            events.append(
                TraceEvent(
                    kind=TraceEventKind.TOOL_CALL,
                    ts=now,
                    payload={"total_calls": source.tool_calls, "tool": "summary"},
                )
            )
        if source.tool_failures > 0:
            events.append(
                TraceEvent(
                    kind=TraceEventKind.TOOL_FAILURE,
                    ts=now,
                    payload={"total_failures": source.tool_failures, "tool": "summary"},
                )
            )
        if source.total_tokens > 0:
            events.append(
                TraceEvent(
                    kind=TraceEventKind.TOKENS,
                    ts=now,
                    payload={
                        "total": source.total_tokens,
                        "est_without": source.est_tokens_without_onmc,
                    },
                )
            )
        if source.memory_hits > 0:
            events.append(
                TraceEvent(
                    kind=TraceEventKind.MEMORY_HIT,
                    ts=now,
                    payload={"count": source.memory_hits},
                )
            )
        if source.memory_misses > 0:
            events.append(
                TraceEvent(
                    kind=TraceEventKind.MEMORY_MISS,
                    ts=now,
                    payload={"count": source.memory_misses},
                )
            )
    else:
        events = source
        sid = session_id

    return [
        _span_from_event(ev, session_id=sid, index=index)
        for index, ev in enumerate(events)
    ]
