"""OTLP protobuf encoding — the `observe` extra, for JSON-rejecting receivers.

Phoenix's OTLP receiver (and some collectors) accept only protobuf (measured:
415 on JSON). This module converts our OTLP-JSON payloads to serialized
``ExportTraceServiceRequest`` bytes.

The one real subtlety, so nobody re-learns it: OTLP-JSON and proto3-JSON
disagree about ids. OTLP-JSON carries ``traceId``/``spanId`` as **hex**;
``google.protobuf.json_format.Parse`` implements proto3-JSON, which reads
bytes fields as **base64**. Feeding hex straight in silently produces
wrong-length ids. We re-encode the id fields to base64 first, then Parse.

Import is guarded: without ``pip install 'oh-no-my-claudecode[observe]'``
callers get an install hint, never an ImportError mid-ship.
"""

from __future__ import annotations

import base64
import json
from typing import Any

_HINT = "protobuf encoding needs the 'observe' extra: pip install 'oh-no-my-claudecode[observe]'"

_ID_KEYS = {"traceId", "spanId", "parentSpanId"}


def _hex_ids_to_base64(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: (
                base64.b64encode(bytes.fromhex(value)).decode()
                if key in _ID_KEYS and isinstance(value, str) and value
                else _hex_ids_to_base64(value)
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_hex_ids_to_base64(item) for item in node]
    return node


def encode_protobuf(payload: dict[str, Any]) -> bytes:
    """OTLP-JSON dict → serialized ExportTraceServiceRequest bytes."""
    try:
        from google.protobuf.json_format import Parse  # type: ignore[import-untyped]
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
    except ImportError as error:  # pragma: no cover - exercised without the extra
        raise RuntimeError(_HINT) from error

    normalized = _hex_ids_to_base64(payload)
    request = Parse(json.dumps(normalized), ExportTraceServiceRequest())
    return bytes(request.SerializeToString())


def protobuf_available() -> bool:
    try:
        import opentelemetry.proto  # noqa: F401
    except ImportError:
        return False
    return True


__all__ = ["encode_protobuf", "protobuf_available"]
