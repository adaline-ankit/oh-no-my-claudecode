"""Protobuf extra: id re-encoding is correct, 415 triggers the fallback."""

from __future__ import annotations

import json

import pytest

from oh_no_my_claudecode.trace.otel_ledger import to_otlp, verdict_span
from oh_no_my_claudecode.trace.otel_ship import ship_payload

pytest.importorskip("opentelemetry.proto", reason="needs the 'observe' extra")

RECEIPT = {"receipt_hash": "a" * 64, "verified": True, "status": "completed"}


def test_hex_ids_survive_the_proto3_json_gap() -> None:
    # OTLP-JSON ids are hex; proto3-JSON wants base64 — encode_protobuf must
    # bridge that or ids silently corrupt.
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )

    from oh_no_my_claudecode.trace.otel_pb import encode_protobuf

    span = verdict_span(RECEIPT, when_ns=7)
    raw = encode_protobuf(to_otlp([span]))
    decoded = ExportTraceServiceRequest()
    decoded.ParseFromString(raw)
    wire_span = decoded.resource_spans[0].scope_spans[0].spans[0]
    assert wire_span.trace_id == bytes.fromhex(span["traceId"])  # 16 bytes, exact
    assert wire_span.span_id == bytes.fromhex(span["spanId"])
    assert wire_span.name == "onmc.verdict"


def test_415_falls_back_to_protobuf_transparently() -> None:
    calls: list[tuple[str, bytes | None]] = []

    def transport(method: str, url: str, headers: dict[str, str], body: bytes | None):
        calls.append((headers["Content-Type"], body))
        if headers["Content-Type"] == "application/json":
            return 415, "Unsupported content type: application/json"
        return 200, "{}"

    payload = to_otlp([verdict_span(RECEIPT, when_ns=7)])
    status, _ = ship_payload(payload, endpoint="http://x", headers={}, transport=transport)
    assert status == 200
    assert [content_type for content_type, _ in calls] == [
        "application/json",
        "application/x-protobuf",
    ]
    assert calls[0][1] is not None and json.loads(calls[0][1])  # first try was JSON
    assert calls[1][1] is not None and calls[1][1][:1] != b"{"  # retry was binary
