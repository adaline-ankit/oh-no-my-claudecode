"""Integrity tests for real ONMC telemetry and OTLP export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oh_no_my_claudecode.loop.adapters import ClaudeCliAdapter, CompletedProc
from oh_no_my_claudecode.telemetry.exporter import (
    ExportResponse,
    OtlpHttpExporter,
)
from oh_no_my_claudecode.trace.models import TraceEvent, TraceEventKind
from oh_no_my_claudecode.trace.otel import TelemetryPrivacy, to_otel_spans
from oh_no_my_claudecode.trace.recorder import (
    load_session_events,
    start_session,
    trace_parent,
)


def _attributes(span: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        item["key"]: item["value"]
        for item in span["attributes"]  # type: ignore[index,union-attr]
    }


def test_unknown_duration_is_zero_length_and_never_synthetic_one_ms() -> None:
    event = TraceEvent(kind=TraceEventKind.TOOL_CALL, ts=100.0, payload={"tool": "Read"})

    span = to_otel_spans([event], session_id="run-real-time")[0]
    attrs = _attributes(span)

    assert span["endTimeUnixNano"] == span["startTimeUnixNano"]
    assert attrs["onmc.duration.complete"]["boolValue"] is False
    assert "onmc.duration.estimated" not in attrs
    assert "onmc.duration.estimate_reason" not in attrs


def test_total_only_usage_stays_incomplete_and_is_never_split_60_40() -> None:
    event = TraceEvent(
        kind=TraceEventKind.MODEL_CALL,
        ts=100.0,
        payload={"provider": "codex", "total": 500},
    )

    attrs = _attributes(to_otel_spans([event], session_id="run-real-usage")[0])

    assert "gen_ai.usage.input_tokens" not in attrs
    assert "gen_ai.usage.output_tokens" not in attrs
    assert attrs["onmc.usage.total_tokens"]["intValue"] == 500
    assert attrs["onmc.usage.complete"]["boolValue"] is False
    assert attrs["onmc.usage.incomplete_reason"]["stringValue"] == "provider_reported_total_only"
    assert attrs["onmc.cost.complete"]["boolValue"] is False


def test_measured_usage_preserves_cache_tokens_and_provider_cost() -> None:
    event = TraceEvent(
        kind=TraceEventKind.MODEL_CALL,
        ts=100.0,
        payload={
            "provider": "anthropic",
            "input_tokens": 321,
            "output_tokens": 123,
            "cache_read_input_tokens": 200,
            "cache_creation_input_tokens": 20,
            "cost_usd": 0.0125,
            "end_ts": 100.25,
        },
    )

    attrs = _attributes(to_otel_spans([event], session_id="run-measured-usage")[0])

    assert attrs["gen_ai.usage.input_tokens"]["intValue"] == 321
    assert attrs["gen_ai.usage.output_tokens"]["intValue"] == 123
    assert attrs["gen_ai.usage.cache_read.input_tokens"]["intValue"] == 200
    assert attrs["gen_ai.usage.cache_creation.input_tokens"]["intValue"] == 20
    assert attrs["onmc.usage.complete"]["boolValue"] is True
    assert attrs["onmc.usage.cost_usd"]["doubleValue"] == pytest.approx(0.0125)
    assert attrs["onmc.cost.complete"]["boolValue"] is True


def test_explicit_parentage_covers_runtime_decision_span_kinds() -> None:
    events = [
        TraceEvent(
            kind=TraceEventKind.RUNTIME_RUN,
            ts=1.0,
            payload={"run_id": "run-1", "end_ts": 10.0},
            span_id="run",
        ),
        TraceEvent(
            kind=TraceEventKind.RUNTIME_NODE,
            ts=2.0,
            payload={"run_id": "run-1", "node_id": "execute", "end_ts": 9.0},
            span_id="node",
            parent_span_id="run",
        ),
    ]
    child_kinds = (
        TraceEventKind.TOOL_CALL,
        TraceEventKind.MODEL_CALL,
        TraceEventKind.RETRIEVAL,
        TraceEventKind.VERIFIER,
        TraceEventKind.POLICY_DECISION,
        TraceEventKind.ROUTE_DECISION,
    )
    for index, kind in enumerate(child_kinds, start=3):
        events.append(
            TraceEvent(
                kind=kind,
                ts=float(index),
                payload={"end_ts": float(index) + 0.1},
                span_id=f"child-{index}",
                parent_span_id="node",
            )
        )

    spans = to_otel_spans(events, session_id="run-real-tree")
    run_span, node_span, *children = spans

    assert node_span["parentSpanId"] == run_span["spanId"]
    assert {span["parentSpanId"] for span in children} == {node_span["spanId"]}
    assert all(span["endTimeUnixNano"] > span["startTimeUnixNano"] for span in spans)


def test_content_capture_is_off_by_default_and_opt_in_still_redacts_secrets() -> None:
    event = TraceEvent(
        kind=TraceEventKind.MODEL_CALL,
        ts=100.0,
        payload={
            "prompt": "debug with token sk-super-secret-value",
            "output": "authorization: Bearer private-token",
            "target": "/Users/example/private/repo.py",
        },
    )

    default_span = to_otel_spans([event], session_id="privacy-default")[0]
    default_json = json.dumps(default_span)
    default_attrs = _attributes(default_span)
    assert "sk-super-secret-value" not in default_json
    assert "private-token" not in default_json
    assert "/Users/example/private/repo.py" not in default_json
    assert default_attrs["onmc.content.capture_enabled"]["boolValue"] is False

    captured_span = to_otel_spans(
        [event],
        session_id="privacy-opt-in",
        privacy=TelemetryPrivacy(capture_content=True),
    )[0]
    captured_json = json.dumps(captured_span)
    captured_attrs = _attributes(captured_span)
    assert "sk-super-secret-value" not in captured_json
    assert "private-token" not in captured_json
    assert captured_attrs["onmc.content.capture_enabled"]["boolValue"] is True
    assert "[REDACTED]" in captured_json


def test_claude_adapter_records_real_measured_model_usage_under_current_node(
    tmp_path: Path,
) -> None:
    assert start_session(tmp_path) is not None

    def runner(command: list[str], cwd: str, timeout: int) -> CompletedProc:
        del cwd, timeout
        if command[:3] == ["git", "-C", str(tmp_path)]:
            return CompletedProc(returncode=0, stdout="", stderr="")
        return CompletedProc(
            returncode=0,
            stdout=json.dumps(
                {
                    "result": "done",
                    "usage": {
                        "input_tokens": 12,
                        "output_tokens": 4,
                        "cache_read_input_tokens": 7,
                    },
                    "total_cost_usd": 0.003,
                }
            ),
            stderr="",
        )

    adapter = ClaudeCliAdapter(tmp_path, command_runner=runner)
    with trace_parent("runtime-node"):
        adapter("private prompt", escalation_level=0)

    session_id = next((tmp_path / ".onmc" / "traces").glob("tr_*.jsonl")).stem
    _, events = load_session_events(tmp_path, session_id, include_notify_window=False)
    model_event = next(event for event in events if event.kind == TraceEventKind.MODEL_CALL)

    assert model_event.parent_span_id == "runtime-node"
    assert model_event.payload["input_tokens"] == 12
    assert model_event.payload["output_tokens"] == 4
    assert model_event.payload["cache_read_input_tokens"] == 7
    assert model_event.payload["cost_usd"] == pytest.approx(0.003)
    assert model_event.payload["end_ts"] > model_event.ts
    assert "private prompt" not in json.dumps(model_event.to_record())


def test_otlp_http_exporter_sends_standard_json_envelope_without_leaking_headers() -> None:
    calls: list[tuple[str, bytes, dict[str, str], float]] = []

    def transport(
        endpoint: str,
        body: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> ExportResponse:
        calls.append((endpoint, body, headers, timeout))
        return ExportResponse(status_code=200, body=b'{"partialSuccess":{}}')

    exporter = OtlpHttpExporter(
        "http://collector:4318",
        headers={"authorization": "Bearer private", "x-project-name": "onmc"},
        service_name="onmc-tests",
        transport=transport,
    )
    spans = to_otel_spans(
        [
            TraceEvent(
                kind=TraceEventKind.RUNTIME_RUN,
                ts=1.0,
                payload={"run_id": "run-1", "end_ts": 2.0},
            )
        ],
        session_id="run-export",
    )

    result = exporter.export(spans)

    assert result.success is True
    assert result.exported_spans == 1
    assert "private" not in repr(exporter)
    assert calls[0][0] == "http://collector:4318/v1/traces"
    assert calls[0][2]["content-type"] == "application/json"
    envelope = json.loads(calls[0][1])
    resource = envelope["resourceSpans"][0]
    service_name = resource["resource"]["attributes"][0]
    assert service_name == {"key": "service.name", "value": {"stringValue": "onmc-tests"}}
    assert resource["scopeSpans"][0]["spans"] == spans
