"""Optional OpenTelemetry GenAI-convention span export.

Converts a ``TraceReport`` (or a list of ``TraceEvent`` objects) into a list
of OpenTelemetry span dicts following the
`OpenTelemetry GenAI semantic conventions <https://opentelemetry.io/docs/specs/semconv/gen-ai/>`_.

**No OpenTelemetry SDK dependency** — this module emits pure Python dicts
that match the OTLP JSON shape.  Callers can serialize to JSON and pipe into
any OTLP-compatible backend or inspect manually.

Key attributes used
-------------------
- ``gen_ai.system``          — legacy compatibility marker "onmc"
- ``gen_ai.provider.name``   — measured provider identity when available
- ``gen_ai.operation.name``  — mapped from ``TraceEventKind``
- ``gen_ai.usage.input_tokens`` / ``gen_ai.usage.output_tokens``
- ``gen_ai.usage.cache_*``   — measured cache-token fields when available
- ``onmc.tool``              — tool name for tool_call events
- ``onmc.content.*``         — opt-in redacted content only
- ``onmc.session_id``        — parent session identifier
- ``onmc.usage.complete`` / ``onmc.cost.complete`` — explicit coverage markers
- ``onmc.duration.complete`` — false when no measured end time was recorded
- ``onmc.runtime.*``         — runtime graph/run/node attributes for runtime events
- ``traceId`` / ``spanId``   — deterministic OTLP correlation identifiers
- ``parentSpanId``           — runtime_node parent run span when runtime_run is present
- ``links``                  — runtime_node dependency edges when dependency spans are present
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
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
    TraceEventKind.MODEL_CALL: "chat",
    TraceEventKind.RETRIEVAL: "retrieval",
    TraceEventKind.VERIFIER: "verify",
    TraceEventKind.POLICY_DECISION: "policy",
    TraceEventKind.ROUTE_DECISION: "route",
    TraceEventKind.PROMOTION_DECISION: "promote",
    TraceEventKind.RUNTIME_RUN: "invoke_agent",
    TraceEventKind.RUNTIME_NODE: "execute_agent",
    TraceEventKind.FILE_READ: "retrieval",
    TraceEventKind.SEARCH_QUERY: "retrieval",
    TraceEventKind.TOKENS: "chat",
    TraceEventKind.MEMORY_HIT: "retrieval",
    TraceEventKind.MEMORY_MISS: "retrieval",
    TraceEventKind.RECALL_SURFACED: "retrieval",
    TraceEventKind.DANGER_BLOCKED: "execute_tool",
    TraceEventKind.MEMORY_CAPTURED: "create",
    TraceEventKind.SKILL_PROMOTED: "create",
    TraceEventKind.STALENESS_WARNING: "chat",
    TraceEventKind.GENERIC: "chat",
}

_STATUS_ERROR = {"code": 2}  # OTEL StatusCode.ERROR
_STATUS_OK = {"code": 1}  # OTEL StatusCode.OK
_ERROR_RUNTIME_NODE_STATUSES = frozenset({"cancelled", "failed", "skipped"})
_ERROR_RUNTIME_RUN_STATUSES = frozenset({"cancelled", "failed"})
_USAGE_EVENT_KINDS = frozenset({TraceEventKind.MODEL_CALL, TraceEventKind.TOKENS})
_CONTENT_KEYS = frozenset(
    {
        "arguments",
        "content",
        "detail",
        "error",
        "objective",
        "output",
        "prompt",
        "query",
        "result",
        "target",
        "title",
        "tool_input",
        "tool_output",
    }
)
_DEFAULT_REDACTION_PATTERNS = (
    r"(?i)\b(?:authorization\s*:\s*)?bearer\s+[A-Za-z0-9._~+/=-]+",
    r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+",
    r"\b(?:sk|xox[baprs])-[A-Za-z0-9_-]{8,}\b",
    r"/Users/[^/\s]+",
)


@dataclass(frozen=True, slots=True)
class TelemetryPrivacy:
    """Privacy policy applied before trace content leaves the process."""

    capture_content: bool = False
    redaction_text: str = "[REDACTED]"
    redaction_patterns: tuple[str, ...] = _DEFAULT_REDACTION_PATTERNS

    def redact(self, value: object) -> str:
        """Render *value* and replace common credential and local-path forms."""
        rendered = str(value)
        for pattern in self.redaction_patterns:
            rendered = re.sub(pattern, self.redaction_text, rendered)
        return rendered


def _ns(ts_seconds: float) -> int:
    """Convert Unix seconds to nanoseconds (OTLP time format)."""
    return int(ts_seconds * 1_000_000_000)


def _span_from_event(
    event: TraceEvent,
    *,
    session_id: str,
    index: int = 0,
    privacy: TelemetryPrivacy,
) -> dict[str, Any]:
    """Build an OTLP JSON span dict from a single ``TraceEvent``."""
    kind = event.kind
    operation = _OPERATION_MAP.get(kind, "chat")
    span_status = _span_status(event, privacy=privacy)

    attributes: list[dict[str, Any]] = [
        {"key": "gen_ai.system", "value": {"stringValue": _GEN_AI_SYSTEM}},
        {"key": "gen_ai.operation.name", "value": {"stringValue": operation}},
        {"key": "onmc.session_id", "value": {"stringValue": session_id}},
        {"key": "onmc.event_kind", "value": {"stringValue": kind}},
        {
            "key": "onmc.content.capture_enabled",
            "value": {"boolValue": privacy.capture_content},
        },
    ]

    payload = event.payload
    start_ns, end_ns, duration_attributes = _span_times(event)
    attributes.extend(duration_attributes)
    if "tool" in payload:
        attributes.append(
            {"key": "onmc.tool", "value": {"stringValue": str(payload["tool"])}}
        )
    _append_string_attribute(attributes, "gen_ai.provider.name", payload.get("provider"))
    _append_string_attribute(attributes, "gen_ai.request.model", payload.get("model"))
    attributes.extend(_token_usage_attributes(event))
    attributes.extend(_cost_attributes(event))
    attributes.extend(_content_attributes(payload, privacy=privacy))
    attributes.extend(_runtime_run_attributes(event, privacy=privacy))
    attributes.extend(_runtime_node_attributes(event, privacy=privacy))

    return {
        "traceId": _trace_id(session_id),
        "spanId": _span_id(session_id, index, event),
        "name": f"onmc.{kind}",
        "kind": 1,  # INTERNAL
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
        "status": span_status,
        "attributes": attributes,
    }


def _trace_id(session_id: str) -> str:
    material = f"onmc-trace:{session_id or 'default'}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _span_id(session_id: str, index: int, event: TraceEvent) -> str:
    if event.span_id is not None:
        return _logical_span_id(session_id, event.span_id)
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


def _logical_span_id(session_id: str, logical_span_id: str) -> str:
    material = f"onmc-span:{session_id}:{logical_span_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _event_is_error(event: TraceEvent) -> bool:
    if event.kind in (TraceEventKind.TOOL_FAILURE, TraceEventKind.DANGER_BLOCKED):
        return True
    if str(event.payload.get("status", "")).lower() in {"error", "failed"}:
        return True
    if event.kind == TraceEventKind.RUNTIME_RUN:
        return str(event.payload.get("status", "")).lower() in _ERROR_RUNTIME_RUN_STATUSES
    if event.kind == TraceEventKind.RUNTIME_NODE:
        return str(event.payload.get("status", "")).lower() in _ERROR_RUNTIME_NODE_STATUSES
    return False


def _span_status(event: TraceEvent, *, privacy: TelemetryPrivacy) -> dict[str, Any]:
    if not _event_is_error(event):
        return _STATUS_OK
    status: dict[str, Any] = dict(_STATUS_ERROR)
    message = event.payload.get("error") or event.payload.get("title")
    if message and privacy.capture_content:
        status["message"] = privacy.redact(message)
    return status


def _runtime_run_attributes(
    event: TraceEvent,
    *,
    privacy: TelemetryPrivacy,
) -> list[dict[str, Any]]:
    if event.kind != TraceEventKind.RUNTIME_RUN:
        return []
    payload = event.payload
    attributes: list[dict[str, Any]] = []
    _append_string_attribute(attributes, "onmc.runtime.backend", payload.get("backend"))
    _append_string_attribute(attributes, "onmc.runtime.run_id", payload.get("run_id"))
    _append_string_attribute(attributes, "onmc.runtime.run.status", payload.get("status"))
    if privacy.capture_content and payload.get("error") is not None:
        _append_string_attribute(
            attributes,
            "onmc.runtime.run.error",
            privacy.redact(payload["error"]),
        )
    _append_string_attribute(
        attributes,
        "onmc.runtime.run.spec_digest",
        payload.get("spec_digest"),
    )
    _append_string_attribute(
        attributes,
        "onmc.runtime.run.environment_digest",
        payload.get("environment_digest"),
    )
    _append_string_attribute(
        attributes,
        "onmc.runtime.run.environment.python_version",
        payload.get("environment_python_version"),
    )
    _append_string_attribute(
        attributes,
        "onmc.runtime.run.environment.platform",
        payload.get("environment_platform"),
    )
    _append_string_attribute(
        attributes,
        "onmc.runtime.run.git_digest",
        payload.get("git_digest"),
    )
    _append_string_attribute(
        attributes,
        "onmc.runtime.run.git_head",
        payload.get("git_head"),
    )
    _append_string_attribute(
        attributes,
        "onmc.runtime.run.git_branch",
        payload.get("git_branch"),
    )
    _append_bool_attribute(
        attributes,
        "onmc.runtime.run.git_dirty",
        payload.get("git_dirty"),
    )
    _append_int_attribute(
        attributes,
        "onmc.runtime.run.node_count",
        payload.get("node_count"),
    )
    _append_int_attribute(
        attributes,
        "onmc.runtime.run.result_count",
        payload.get("result_count"),
    )
    _append_node_status_count_attributes(attributes, payload.get("node_status_counts"))
    _append_int_attribute(
        attributes,
        "onmc.runtime.run.evidence_count",
        payload.get("evidence_count"),
    )
    _append_string_array_attribute(
        attributes,
        "onmc.runtime.run.evidence_kinds",
        payload.get("evidence_kinds"),
    )
    _append_int_attribute(
        attributes,
        "onmc.runtime.run.digest_evidence_count",
        payload.get("digest_evidence_count"),
    )
    _append_int_attribute(
        attributes,
        "onmc.runtime.run.completion_evidence_count",
        payload.get("completion_evidence_count"),
    )
    _append_int_attribute(
        attributes,
        "onmc.runtime.run.max_workers",
        payload.get("max_workers"),
    )
    return attributes


def _append_node_status_count_attributes(
    attributes: list[dict[str, Any]],
    value: object,
) -> None:
    if not isinstance(value, dict):
        return
    for status in ("succeeded", "failed", "skipped"):
        _append_int_attribute(
            attributes,
            f"onmc.runtime.run.node_status_count.{status}",
            value.get(status),
        )


def _runtime_node_attributes(
    event: TraceEvent,
    *,
    privacy: TelemetryPrivacy,
) -> list[dict[str, Any]]:
    if event.kind != TraceEventKind.RUNTIME_NODE:
        return []
    payload = event.payload
    attributes: list[dict[str, Any]] = []
    _append_string_attribute(attributes, "onmc.runtime.backend", payload.get("backend"))
    _append_string_attribute(attributes, "onmc.runtime.run_id", payload.get("run_id"))
    _append_string_attribute(attributes, "onmc.runtime.node_id", payload.get("node_id"))
    _append_string_attribute(attributes, "onmc.runtime.node.kind", payload.get("node_kind"))
    _append_string_attribute(attributes, "onmc.runtime.node.status", payload.get("status"))
    if privacy.capture_content and payload.get("error") is not None:
        _append_string_attribute(
            attributes,
            "onmc.runtime.node.error",
            privacy.redact(payload["error"]),
        )
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
    _append_int_attribute(
        attributes,
        "onmc.runtime.node.evidence_count",
        payload.get("evidence_count"),
    )
    _append_string_array_attribute(
        attributes,
        "onmc.runtime.node.evidence_kinds",
        payload.get("evidence_kinds"),
    )
    _append_int_attribute(
        attributes,
        "onmc.runtime.node.digest_evidence_count",
        payload.get("digest_evidence_count"),
    )
    _append_int_attribute(
        attributes,
        "onmc.runtime.node.completion_evidence_count",
        payload.get("completion_evidence_count"),
    )
    capabilities = payload.get("capabilities")
    if isinstance(capabilities, dict):
        _append_string_array_attribute(
            attributes,
            "onmc.runtime.capabilities.tools",
            capabilities.get("tools"),
        )
        if privacy.capture_content:
            _append_string_array_attribute(
                attributes,
                "onmc.runtime.capabilities.commands",
                [
                    privacy.redact(command)
                    for command in _command_strings(capabilities.get("commands"))
                ],
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
            [{"key": "onmc.duration.complete", "value": {"boolValue": True}}],
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
            [{"key": "onmc.duration.complete", "value": {"boolValue": True}}],
        )

    return (
        start_ns,
        start_ns,
        [
            {"key": "onmc.duration.complete", "value": {"boolValue": False}},
            {
                "key": "onmc.duration.incomplete_reason",
                "value": {"stringValue": "end_time_not_recorded"},
            },
        ],
    )


def _token_usage_attributes(event: TraceEvent) -> list[dict[str, Any]]:
    if event.kind not in _USAGE_EVENT_KINDS:
        return []
    payload = event.payload
    measured_input = _optional_int(payload, "input_tokens")
    measured_output = _optional_int(payload, "output_tokens")
    cache_read = _optional_int(payload, "cache_read_input_tokens")
    cache_creation = _optional_int(payload, "cache_creation_input_tokens")
    reasoning_output = _optional_int(payload, "reasoning_output_tokens")
    total = _optional_int(payload, "total")
    attributes: list[dict[str, Any]] = []
    if measured_input is not None:
        _append_int_attribute(attributes, "gen_ai.usage.input_tokens", measured_input)
    if measured_output is not None:
        _append_int_attribute(attributes, "gen_ai.usage.output_tokens", measured_output)
    if cache_read is not None:
        _append_int_attribute(
            attributes,
            "gen_ai.usage.cache_read.input_tokens",
            cache_read,
        )
    if cache_creation is not None:
        _append_int_attribute(
            attributes,
            "gen_ai.usage.cache_creation.input_tokens",
            cache_creation,
        )
    if reasoning_output is not None:
        _append_int_attribute(
            attributes,
            "gen_ai.usage.reasoning.output_tokens",
            reasoning_output,
        )
    if total is not None:
        _append_int_attribute(attributes, "onmc.usage.total_tokens", total)

    complete = measured_input is not None and measured_output is not None
    _append_bool_attribute(attributes, "onmc.usage.complete", complete)
    if complete:
        return attributes
    if total is not None and measured_input is None and measured_output is None:
        reason = "provider_reported_total_only"
    elif measured_input is None and measured_output is None:
        reason = "provider_did_not_report"
    elif measured_input is None:
        reason = "input_tokens_not_reported"
    else:
        reason = "output_tokens_not_reported"
    _append_string_attribute(attributes, "onmc.usage.incomplete_reason", reason)
    return attributes


def _cost_attributes(event: TraceEvent) -> list[dict[str, Any]]:
    if event.kind not in _USAGE_EVENT_KINDS:
        return []
    cost = _optional_float(event.payload, "cost_usd")
    attributes: list[dict[str, Any]] = []
    _append_bool_attribute(attributes, "onmc.cost.complete", cost is not None)
    if cost is None:
        _append_string_attribute(
            attributes,
            "onmc.cost.incomplete_reason",
            "provider_did_not_report",
        )
    else:
        _append_float_attribute(attributes, "onmc.usage.cost_usd", cost)
    return attributes


def _content_attributes(
    payload: dict[str, Any],
    *,
    privacy: TelemetryPrivacy,
) -> list[dict[str, Any]]:
    present = sorted(key for key in _CONTENT_KEYS if payload.get(key) is not None)
    attributes: list[dict[str, Any]] = []
    if not present:
        return attributes
    _append_bool_attribute(attributes, "onmc.content.redacted", True)
    if not privacy.capture_content:
        return attributes
    for key in present:
        value = privacy.redact(payload[key])
        attribute_key = "onmc.target" if key == "target" else f"onmc.content.{key}"
        _append_string_attribute(attributes, attribute_key, value)
    return attributes


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


def _append_float_attribute(
    attributes: list[dict[str, Any]],
    key: str,
    value: object,
) -> None:
    if isinstance(value, bool):
        return
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return
    attributes.append({"key": key, "value": {"doubleValue": parsed}})


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
    privacy: TelemetryPrivacy | None = None,
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
    privacy:
        Export privacy controls.  Content capture is disabled by default and
        common credential/path forms remain redacted when explicitly enabled.

    Returns
    -------
    list[dict[str, Any]]
        One span dict per event.  Serialise with ``json.dumps`` for OTLP JSON.
    """
    privacy_policy = privacy or TelemetryPrivacy()
    if isinstance(source, TraceReport):
        sid = session_id or source.session_id
        # Aggregated reports contain no real event timestamps or hierarchy.
        # Returning no spans is safer than fabricating telemetry.  Callers that
        # need export fidelity must pass the raw recorded events.
        events: list[TraceEvent] = []
    else:
        events = source
        sid = session_id

    spans = [
        _span_from_event(
            ev,
            session_id=sid,
            index=index,
            privacy=privacy_policy,
        )
        for index, ev in enumerate(events)
    ]
    return _attach_parentage_and_runtime_links(events, spans)


def _attach_parentage_and_runtime_links(
    events: list[TraceEvent],
    spans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    runtime_run_spans: dict[str, dict[str, Any]] = {}
    runtime_node_spans: dict[tuple[str, str], dict[str, Any]] = {}
    logical_spans: dict[str, dict[str, Any]] = {}
    for event, span in zip(events, spans, strict=True):
        if event.span_id is not None:
            logical_spans[event.span_id] = span
        if event.kind == TraceEventKind.RUNTIME_RUN:
            run_id = event.payload.get("run_id")
            if run_id is not None:
                runtime_run_spans[str(run_id)] = span
        elif event.kind == TraceEventKind.RUNTIME_NODE:
            run_id = event.payload.get("run_id")
            node_id = event.payload.get("node_id")
            if run_id is not None and node_id is not None:
                runtime_node_spans[(str(run_id), str(node_id))] = span

    for event, span in zip(events, spans, strict=True):
        if event.parent_span_id is not None:
            explicit_parent = logical_spans.get(event.parent_span_id)
            if explicit_parent is not None:
                span["parentSpanId"] = explicit_parent["spanId"]
        if event.kind != TraceEventKind.RUNTIME_NODE:
            continue
        run_id = event.payload.get("run_id")
        run_span = runtime_run_spans.get(str(run_id)) if run_id is not None else None
        if run_span is not None and "parentSpanId" not in span:
            span["parentSpanId"] = run_span["spanId"]
        dependencies = event.payload.get("dependencies")
        if run_id is None or not isinstance(dependencies, list | tuple):
            continue
        links = []
        for dependency in dependencies:
            dependency_id = str(dependency)
            dependency_span = runtime_node_spans.get((str(run_id), dependency_id))
            if dependency_span is None:
                continue
            links.append(
                {
                    "traceId": dependency_span["traceId"],
                    "spanId": dependency_span["spanId"],
                    "attributes": [
                        {
                            "key": "onmc.runtime.dependency",
                            "value": {"stringValue": dependency_id},
                        }
                    ],
                }
            )
        if links:
            span["links"] = links
    return spans
